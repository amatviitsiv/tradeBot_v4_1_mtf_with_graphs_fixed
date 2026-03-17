import logging
from typing import Optional

import pandas as pd
import numpy as np

import config as cfg
from .base import BaseStrategy

logger = logging.getLogger(__name__)


class MTFBreakoutStrategy(BaseStrategy):
    """Multi-timeframe breakout-стратегия.

    HTF (H1) отвечает за направление тренда,
    LTF (M15) даёт точный вход по пробою диапазона.

    Ожидаемые колонки в df (M15-таймфрейм):
    - open, high, low, close, volume, RSI, ATR, ADX, EMA20/50/200 (LTF-индикаторы)
    - HTF_EMA20, HTF_EMA50, HTF_EMA200, HTF_ATR, HTF_ADX, HTF_RSI, HTF_SMA_TREND (добавляются раннером)
    """

    name: str = "mtf_breakout"

    def __init__(self):
        self.last_signal_meta = {"signal": None, "trade_type": None, "risk_multiplier": 1.0}

    def _set_signal(self, signal: Optional[str], trade_type: str | None = None, risk_multiplier: float = 1.0, **meta):
        self.last_signal_meta = {"signal": signal, "trade_type": trade_type, "risk_multiplier": float(risk_multiplier), **meta}
        return signal

    def _extract_bar_timestamp(self, df: pd.DataFrame):
        """Пытается достать timestamp последней свечи из open_time или DatetimeIndex."""
        try:
            last = df.iloc[-1]
            if "open_time" in df.columns:
                raw = last.get("open_time")
                ts = pd.to_datetime(raw, utc=True, unit="ms")
                if pd.isna(ts):
                    ts = pd.to_datetime(raw, utc=True)
                if not pd.isna(ts):
                    return ts
        except Exception:
            pass

        try:
            idx = df.index[-1]
            ts = pd.to_datetime(idx, utc=True)
            if not pd.isna(ts):
                return ts
        except Exception:
            pass
        return self._set_signal(None)

    def _is_allowed_trading_time(self, df: pd.DataFrame) -> tuple[bool, dict]:
        """Фильтр торговых часов. Использует время закрытой LTF-свечи."""
        try:
            enabled = bool(getattr(cfg, "SESSION_TIME_FILTER_ENABLED", False))
            if not enabled:
                return True, {"enabled": False}

            windows = getattr(cfg, "SESSION_ALLOWED_WINDOWS", [(0, 24)]) or [(0, 24)]
            timezone_name = str(getattr(cfg, "SESSION_TIME_FILTER_TIMEZONE", "UTC") or "UTC")
            ts = self._extract_bar_timestamp(df)
            if ts is None or pd.isna(ts):
                return True, {"enabled": True, "skipped": "no_timestamp"}

            if timezone_name and timezone_name.upper() != "UTC":
                try:
                    ts = ts.tz_convert(timezone_name)
                except Exception:
                    pass

            hour = int(ts.hour)
            minute = int(ts.minute)

            for start_hour, end_hour in windows:
                start_hour = int(start_hour)
                end_hour = int(end_hour)
                if start_hour == end_hour:
                    return True, {"enabled": True, "hour": hour, "minute": minute, "windows": windows}
                if start_hour < end_hour:
                    if start_hour <= hour < end_hour:
                        return True, {"enabled": True, "hour": hour, "minute": minute, "windows": windows}
                else:
                    if hour >= start_hour or hour < end_hour:
                        return True, {"enabled": True, "hour": hour, "minute": minute, "windows": windows}

            return False, {
                "reason": "outside_allowed_session",
                "hour": hour,
                "minute": minute,
                "timezone": timezone_name,
                "windows": windows,
            }
        except Exception as exc:
            return False, {"reason": "session_filter_exception", "error": str(exc)}


    def _calc_breakout_candle_quality(self, candle: pd.Series, atr_ltf: float, side: str) -> tuple[bool, dict]:
        """Проверка качества пробойной свечи.

        Идея:
        - тело должно быть достаточно большим относительно ATR;
        - закрытие должно быть возле экстремума свечи;
        - не входим по свече, где сигнал сформирован одним длинным фитилём.
        """
        try:
            open_ = float(candle.get("open"))
            high = float(candle.get("high"))
            low = float(candle.get("low"))
            close = float(candle.get("close"))
        except (TypeError, ValueError):
            return False, {"reason": "bad_ohlc"}

        candle_range = max(high - low, 0.0)
        body = abs(close - open_)
        if candle_range <= 0.0 or atr_ltf <= 0.0:
            return False, {"reason": "bad_range"}

        upper_wick = max(0.0, high - max(open_, close))
        lower_wick = max(0.0, min(open_, close) - low)

        min_body_atr = float(getattr(cfg, "BREAKOUT_MIN_BODY_ATR", 0.35))
        max_close_from_extreme = float(getattr(cfg, "BREAKOUT_MAX_CLOSE_FROM_EXTREME_PCT", 0.25))
        max_breakout_wick_body_ratio = float(getattr(cfg, "BREAKOUT_MAX_WICK_BODY_RATIO", 0.8))
        max_breakout_wick_range_ratio = float(getattr(cfg, "BREAKOUT_MAX_WICK_RANGE_RATIO", 0.35))

        if body < atr_ltf * min_body_atr:
            return False, {
                "reason": "small_body_vs_atr",
                "body": body,
                "atr": atr_ltf,
                "need": atr_ltf * min_body_atr,
            }

        if side == "long":
            if close <= open_:
                return False, {"reason": "no_bull_body"}
            distance_to_extreme = high - close
            breakout_wick = upper_wick
        else:
            if close >= open_:
                return False, {"reason": "no_bear_body"}
            distance_to_extreme = close - low
            breakout_wick = lower_wick

        if (distance_to_extreme / candle_range) > max_close_from_extreme:
            return False, {
                "reason": "close_not_near_extreme",
                "distance": distance_to_extreme,
                "range": candle_range,
            }

        if body <= 0.0:
            return False, {"reason": "zero_body"}

        if (breakout_wick / body) > max_breakout_wick_body_ratio:
            return False, {
                "reason": "wick_too_big_vs_body",
                "wick": breakout_wick,
                "body": body,
            }

        if (breakout_wick / candle_range) > max_breakout_wick_range_ratio:
            return False, {
                "reason": "wick_too_big_vs_range",
                "wick": breakout_wick,
                "range": candle_range,
            }

        return True, {
            "body": body,
            "range": candle_range,
            "upper_wick": upper_wick,
            "lower_wick": lower_wick,
        }

    def _check_htf_trend_vitality(self, df: pd.DataFrame, regime: str, close: float) -> tuple[bool, dict]:
        """Фильтр «живого» тренда на HTF.

        Проверяем, что старший тренд не стал слишком плоским:
        - EMA50 и EMA200 должны сохранять направленный наклон;
        - между EMA20 и EMA50 должна оставаться заметная дистанция.
        """
        try:
            lookback = int(getattr(cfg, "HTF_EMA_SLOPE_LOOKBACK_BARS", 8))
            min_slope_ema50 = float(getattr(cfg, "HTF_EMA50_MIN_SLOPE_PCT", 0.0008))
            min_slope_ema200 = float(getattr(cfg, "HTF_EMA200_MIN_SLOPE_PCT", 0.00025))
            min_dist_pct = float(getattr(cfg, "HTF_EMA20_EMA50_MIN_DIST_PCT", 0.0010))

            if len(df) < lookback + 1 or close <= 0:
                return False, {"reason": "not_enough_htf_history", "lookback": lookback}

            ema20_now = float(df["HTF_EMA20"].iloc[-1])
            ema50_now = float(df["HTF_EMA50"].iloc[-1])
            ema200_now = float(df["HTF_EMA200"].iloc[-1])
            ema50_prev = float(df["HTF_EMA50"].iloc[-lookback - 1])
            ema200_prev = float(df["HTF_EMA200"].iloc[-lookback - 1])

            if any(np.isnan(x) for x in [ema20_now, ema50_now, ema200_now, ema50_prev, ema200_prev]):
                return False, {"reason": "nan_in_htf_ema"}

            slope50 = (ema50_now - ema50_prev) / abs(ema50_now) if ema50_now else 0.0
            slope200 = (ema200_now - ema200_prev) / abs(ema200_now) if ema200_now else 0.0
            dist20_50_pct = abs(ema20_now - ema50_now) / close

            if regime == "bull":
                if slope50 < min_slope_ema50:
                    return False, {"reason": "ema50_flat_bull", "slope50": slope50, "min": min_slope_ema50}
                if slope200 < min_slope_ema200:
                    return False, {"reason": "ema200_flat_bull", "slope200": slope200, "min": min_slope_ema200}
            elif regime == "bear":
                if slope50 > -min_slope_ema50:
                    return False, {"reason": "ema50_flat_bear", "slope50": slope50, "max": -min_slope_ema50}
                if slope200 > -min_slope_ema200:
                    return False, {"reason": "ema200_flat_bear", "slope200": slope200, "max": -min_slope_ema200}

            if dist20_50_pct < min_dist_pct:
                return False, {
                    "reason": "ema20_ema50_too_close",
                    "dist20_50_pct": dist20_50_pct,
                    "min": min_dist_pct,
                }

            return True, {
                "slope50": slope50,
                "slope200": slope200,
                "dist20_50_pct": dist20_50_pct,
            }
        except Exception as exc:
            return False, {"reason": "htf_vitality_exception", "error": str(exc)}


    def _check_htf_overextension(self, close: float, ema20_h: float, ema50_h: float, atr_h: float, regime: str) -> tuple[bool, dict]:
        """Фильтр перегретого движения на HTF.

        Не входим, если цена уже слишком далеко ушла от HTF EMA20/EMA50 в ATR(H1):
        - для bull запрещаем запоздалые покупки слишком высоко над EMA;
        - для bear запрещаем запоздалые продажи слишком низко под EMA.
        """
        try:
            if close <= 0.0 or atr_h <= 0.0:
                return False, {"reason": "bad_close_or_atr", "close": close, "atr_h": atr_h}

            max_dist_ema20_atr = float(getattr(cfg, "HTF_MAX_DIST_FROM_EMA20_ATR", 1.6))
            max_dist_ema50_atr = float(getattr(cfg, "HTF_MAX_DIST_FROM_EMA50_ATR", 2.4))

            if regime == "bull":
                dist20_atr = (close - ema20_h) / atr_h
                dist50_atr = (close - ema50_h) / atr_h
            elif regime == "bear":
                dist20_atr = (ema20_h - close) / atr_h
                dist50_atr = (ema50_h - close) / atr_h
            else:
                return False, {"reason": "unknown_regime", "regime": regime}

            if dist20_atr > max_dist_ema20_atr:
                return False, {
                    "reason": "too_far_from_htf_ema20",
                    "dist20_atr": dist20_atr,
                    "max": max_dist_ema20_atr,
                }

            if dist50_atr > max_dist_ema50_atr:
                return False, {
                    "reason": "too_far_from_htf_ema50",
                    "dist50_atr": dist50_atr,
                    "max": max_dist_ema50_atr,
                }

            return True, {"dist20_atr": dist20_atr, "dist50_atr": dist50_atr}
        except Exception as exc:
            return False, {"reason": "htf_overextension_exception", "error": str(exc)}

    def _calc_breakout_volume_momentum(self, recent: pd.DataFrame, candle: pd.Series, atr_ltf: float, side: str) -> tuple[bool, dict]:
        """Более устойчивый фильтр объёма/импульса для breakout.

        Вместо грубого сравнения с простым средним используем комбинацию:
        - volume EMA по окну recent;
        - медиану объёма как более устойчивую базу;
        - score, который учитывает и объём, и качество/импульс свечи.
        """
        try:
            vol_series = recent["volume"].astype(float).replace([np.inf, -np.inf], np.nan).dropna()
            if len(vol_series) < 5:
                return False, {"reason": "not_enough_volume_history", "count": int(len(vol_series))}

            volume = float(candle.get("volume"))
            open_ = float(candle.get("open"))
            high = float(candle.get("high"))
            low = float(candle.get("low"))
            close = float(candle.get("close"))
        except (TypeError, ValueError, KeyError):
            return False, {"reason": "bad_volume_or_ohlc"}

        if atr_ltf <= 0.0:
            return False, {"reason": "bad_atr", "atr_ltf": atr_ltf}

        vol_ema_span = int(getattr(cfg, "BREAKOUT_VOLUME_EMA_SPAN", 20))
        symbol = self._extract_symbol(recent) or self._extract_symbol(pd.DataFrame([candle]))
        min_vs_ema = cfg.get_symbol_param_float(symbol, "BREAKOUT_VOLUME_MIN_RATIO_TO_EMA", float(getattr(cfg, "BREAKOUT_VOLUME_MIN_RATIO_TO_EMA", 1.10)))
        min_vs_median = cfg.get_symbol_param_float(symbol, "BREAKOUT_VOLUME_MIN_RATIO_TO_MEDIAN", float(getattr(cfg, "BREAKOUT_VOLUME_MIN_RATIO_TO_MEDIAN", 1.20)))
        min_impulse_score = float(getattr(cfg, "BREAKOUT_MIN_VOLUME_IMPULSE_SCORE", 0.55))
        strong_impulse_score = float(getattr(cfg, "BREAKOUT_STRONG_VOLUME_IMPULSE_SCORE", 0.95))

        vol_ema = float(vol_series.ewm(span=max(2, vol_ema_span), adjust=False).mean().iloc[-1])
        vol_median = float(vol_series.median())
        vol_p75 = float(vol_series.quantile(0.75))

        if vol_ema <= 0.0 or vol_median <= 0.0:
            return False, {"reason": "bad_volume_baseline", "vol_ema": vol_ema, "vol_median": vol_median}

        range_ = max(high - low, 0.0)
        body = abs(close - open_)
        body_atr = body / atr_ltf if atr_ltf > 0 else 0.0
        close_pos = 0.5
        if range_ > 0:
            close_pos = (close - low) / range_

        if side == "long":
            close_extreme_score = close_pos
        else:
            close_extreme_score = 1.0 - close_pos

        vol_ratio_ema = volume / vol_ema
        vol_ratio_median = volume / vol_median
        robust_vol_ratio = min(vol_ratio_ema, vol_ratio_median)
        impulse_score = robust_vol_ratio * body_atr * close_extreme_score

        if vol_ratio_ema < min_vs_ema and vol_ratio_median < min_vs_median:
            return False, {
                "reason": "weak_volume",
                "volume": volume,
                "vol_ema": vol_ema,
                "vol_median": vol_median,
                "vol_p75": vol_p75,
                "vol_ratio_ema": vol_ratio_ema,
                "vol_ratio_median": vol_ratio_median,
                "impulse_score": impulse_score,
            }

        if impulse_score < min_impulse_score:
            return False, {
                "reason": "weak_volume_impulse",
                "volume": volume,
                "vol_ema": vol_ema,
                "vol_median": vol_median,
                "vol_ratio_ema": vol_ratio_ema,
                "vol_ratio_median": vol_ratio_median,
                "body_atr": body_atr,
                "close_extreme_score": close_extreme_score,
                "impulse_score": impulse_score,
            }

        return True, {
            "volume": volume,
            "vol_ema": vol_ema,
            "vol_median": vol_median,
            "vol_p75": vol_p75,
            "vol_ratio_ema": vol_ratio_ema,
            "vol_ratio_median": vol_ratio_median,
            "body_atr": body_atr,
            "close_extreme_score": close_extreme_score,
            "impulse_score": impulse_score,
            "is_strong_impulse": impulse_score >= strong_impulse_score,
        }

    def _extract_symbol(self, df: pd.DataFrame) -> str:
        try:
            if "symbol" in df.columns and len(df) > 0:
                return str(df["symbol"].iloc[-1])
        except Exception:
            pass
        return ""

    def _resolve_regime_from_values(self, ema20: float, ema50: float, ema200: float) -> str:
        if ema20 > ema50 > ema200:
            return "bull"
        if ema20 < ema50 < ema200:
            return "bear"
        return "none"

    def _calc_recent_wickiness(self, recent: pd.DataFrame) -> float:
        try:
            highs = recent["high"].astype(float)
            lows = recent["low"].astype(float)
            opens = recent["open"].astype(float)
            closes = recent["close"].astype(float)
            ranges = (highs - lows).replace(0.0, np.nan)
            bodies = (closes - opens).abs()
            wick_share = ((ranges - bodies).clip(lower=0.0) / ranges).replace([np.inf, -np.inf], np.nan)
            value = float(wick_share.tail(min(20, len(wick_share))).mean())
            if np.isnan(value):
                return 1.0
            return max(0.0, min(1.0, value))
        except Exception:
            return 1.0

    def _calc_false_breakout_ratio(self, recent: pd.DataFrame, lookback: int = 12) -> float:
        try:
            if len(recent) < lookback + 3:
                return 0.0
            recent = recent.tail(max(lookback + 6, 18)).copy()
            highs = recent["high"].astype(float).reset_index(drop=True)
            lows = recent["low"].astype(float).reset_index(drop=True)
            closes = recent["close"].astype(float).reset_index(drop=True)
            events = 0
            failures = 0
            for i in range(lookback, len(recent) - 1):
                prev_high = float(highs.iloc[i - lookback:i].max())
                prev_low = float(lows.iloc[i - lookback:i].min())
                close_i = float(closes.iloc[i])
                next_close = float(closes.iloc[i + 1])
                if close_i > prev_high:
                    events += 1
                    if next_close <= prev_high:
                        failures += 1
                elif close_i < prev_low:
                    events += 1
                    if next_close >= prev_low:
                        failures += 1
            return float(failures / events) if events > 0 else 0.0
        except Exception:
            return 0.0

    def _classify_market_state(self, symbol: str, recent: pd.DataFrame, close: float, atr_ltf: float, atr_h: float, adx_h: float, drift: float, regime: str) -> tuple[str, dict]:
        atr_pct_h = (atr_h / close) if close > 0 else 0.0
        atr_pct_ltf = (atr_ltf / close) if close > 0 else 0.0
        wickiness = self._calc_recent_wickiness(recent)
        false_breakout_ratio = self._calc_false_breakout_ratio(recent, lookback=min(12, max(6, len(recent) // 5)))
        range_width = 0.0
        compression_ratio = 0.0
        try:
            range_width = float((recent["high"].astype(float).max() - recent["low"].astype(float).min()) / close) if close > 0 else 0.0
            atr_roll = recent["ATR"].astype(float).dropna() if "ATR" in recent.columns else pd.Series(dtype=float)
            if len(atr_roll) >= 10 and atr_ltf > 0:
                compression_ratio = float(atr_ltf / max(float(atr_roll.tail(10).mean()), 1e-9))
        except Exception:
            pass

        trend_adx_min = float(getattr(cfg, "MARKET_STATE_TREND_ADX_MIN", 22.0))
        range_adx_max = float(getattr(cfg, "MARKET_STATE_RANGE_ADX_MAX", 18.0))
        panic_atr_pct = cfg.get_symbol_param_float(symbol, "MARKET_STATE_PANIC_ATR_PCT", float(getattr(cfg, "MARKET_STATE_PANIC_ATR_PCT", 0.028)))
        panic_wickiness = float(getattr(cfg, "MARKET_STATE_PANIC_WICKINESS", 0.72))
        range_max_width = cfg.get_symbol_param_float(symbol, "RANGE_MAX_WIDTH_PCT", float(getattr(cfg, "RANGE_MAX_WIDTH_PCT", 0.08)))
        trend_drift_floor = float(getattr(cfg, "MARKET_STATE_TREND_DRIFT_MIN", 0.004))

        if atr_pct_h >= panic_atr_pct or (wickiness >= panic_wickiness and false_breakout_ratio >= 0.45):
            return "panic", {
                "atr_pct_h": atr_pct_h,
                "atr_pct_ltf": atr_pct_ltf,
                "wickiness": wickiness,
                "false_breakout_ratio": false_breakout_ratio,
                "range_width": range_width,
                "compression_ratio": compression_ratio,
            }

        if regime != "none" and adx_h >= trend_adx_min and drift >= trend_drift_floor and false_breakout_ratio <= 0.55:
            return "trend", {
                "atr_pct_h": atr_pct_h,
                "atr_pct_ltf": atr_pct_ltf,
                "wickiness": wickiness,
                "false_breakout_ratio": false_breakout_ratio,
                "range_width": range_width,
                "compression_ratio": compression_ratio,
            }

        if adx_h <= range_adx_max and range_width <= range_max_width and compression_ratio <= float(getattr(cfg, "RANGE_MAX_COMPRESSION_RATIO", 1.12)):
            return "range", {
                "atr_pct_h": atr_pct_h,
                "atr_pct_ltf": atr_pct_ltf,
                "wickiness": wickiness,
                "false_breakout_ratio": false_breakout_ratio,
                "range_width": range_width,
                "compression_ratio": compression_ratio,
            }

        transition_false_breakout = float(getattr(cfg, "MARKET_STATE_TRANSITION_FALSE_BREAKOUT_MIN", 0.58))
        transition_wickiness = float(getattr(cfg, "MARKET_STATE_TRANSITION_WICKINESS_MIN", 0.62))
        if regime == "none" or false_breakout_ratio >= transition_false_breakout or wickiness >= transition_wickiness:
            return "transition", {
                "atr_pct_h": atr_pct_h,
                "atr_pct_ltf": atr_pct_ltf,
                "wickiness": wickiness,
                "false_breakout_ratio": false_breakout_ratio,
                "range_width": range_width,
                "compression_ratio": compression_ratio,
            }

        return "trend", {
            "atr_pct_h": atr_pct_h,
            "atr_pct_ltf": atr_pct_ltf,
            "wickiness": wickiness,
            "false_breakout_ratio": false_breakout_ratio,
            "range_width": range_width,
            "compression_ratio": compression_ratio,
        }

    def _check_relative_strength_filter(self, df: pd.DataFrame, symbol: str, side: str) -> tuple[bool, dict]:
        btc_symbol = str(getattr(cfg, "BTC_REGIME_FILTER_SYMBOL", "BTCUSDT"))
        if not symbol or symbol == btc_symbol:
            return True, {"skipped": True, "score": 1.0}
        if "BTC_close" not in df.columns:
            return True, {"skipped": True, "reason": "missing_btc_close"}
        try:
            lookback = int(cfg.get_symbol_param_int(symbol, "REL_STRENGTH_LOOKBACK", int(getattr(cfg, "REL_STRENGTH_LOOKBACK", 48))))
            ema_span = int(cfg.get_symbol_param_int(symbol, "REL_STRENGTH_EMA", int(getattr(cfg, "REL_STRENGTH_EMA", 34))))
            min_ratio = float(cfg.get_symbol_param_float(symbol, "REL_STRENGTH_MIN_RATIO", float(getattr(cfg, "REL_STRENGTH_MIN_RATIO", 1.002))))
            min_slope = float(cfg.get_symbol_param_float(symbol, "REL_STRENGTH_MIN_SLOPE", float(getattr(cfg, "REL_STRENGTH_MIN_SLOPE", 0.0))))
            short_max_ratio = float(cfg.get_symbol_param_float(symbol, "REL_STRENGTH_SHORT_MAX_RATIO", float(getattr(cfg, "REL_STRENGTH_SHORT_MAX_RATIO", 0.998))))
            short_min_slope = float(cfg.get_symbol_param_float(symbol, "REL_STRENGTH_SHORT_MIN_SLOPE", float(getattr(cfg, "REL_STRENGTH_SHORT_MIN_SLOPE", 0.0))))
            recent = df.tail(max(lookback + 5, ema_span + 5)).copy()
            alt_close = recent["close"].astype(float)
            btc_close = recent["BTC_close"].astype(float)
            rs = (alt_close / btc_close.replace(0.0, np.nan)).replace([np.inf, -np.inf], np.nan).dropna()
            if len(rs) < max(lookback // 2, 12):
                return True, {"skipped": True, "reason": "short_rs_history"}
            rs_now = float(rs.iloc[-1])
            rs_ema = float(rs.ewm(span=max(5, ema_span), adjust=False).mean().iloc[-1])
            rs_prev = float(rs.iloc[-min(len(rs), lookback)])
            slope = (rs_now - rs_prev) / abs(rs_prev) if rs_prev != 0 else 0.0
        except Exception as exc:
            return True, {"skipped": True, "reason": "rs_exception", "error": str(exc)}

        ratio = rs_now / rs_ema if rs_ema != 0 else 1.0
        if side == "long":
            ok = ratio >= min_ratio and slope >= min_slope
        else:
            ok = ratio <= short_max_ratio and slope <= short_min_slope
        return ok, {
            "rs_now": rs_now,
            "rs_ema": rs_ema,
            "ratio": ratio,
            "slope": slope,
            "side": side,
        }

    def _check_impulse_breakout(self, symbol: str, recent: pd.DataFrame, candle: pd.Series, side: str, trigger: float, atr_ltf: float) -> tuple[bool, dict]:
        try:
            open_ = float(candle.get("open"))
            high = float(candle.get("high"))
            low = float(candle.get("low"))
            close = float(candle.get("close"))
        except (TypeError, ValueError):
            return False, {"reason": "bad_impulse_ohlc"}
        if atr_ltf <= 0:
            return False, {"reason": "bad_atr"}

        body = abs(close - open_)
        rng = max(high - low, 0.0)
        excursion = (close - trigger) if side == "long" else (trigger - close)
        min_body_atr = cfg.get_symbol_param_float(symbol, "IMPULSE_BREAKOUT_MIN_BODY_ATR", float(getattr(cfg, "IMPULSE_BREAKOUT_MIN_BODY_ATR", 0.85)))
        min_range_atr = cfg.get_symbol_param_float(symbol, "IMPULSE_BREAKOUT_MIN_RANGE_ATR", float(getattr(cfg, "IMPULSE_BREAKOUT_MIN_RANGE_ATR", 1.20)))
        min_excursion_atr = cfg.get_symbol_param_float(symbol, "IMPULSE_BREAKOUT_MIN_EXCURSION_ATR", float(getattr(cfg, "IMPULSE_BREAKOUT_MIN_EXCURSION_ATR", 0.18)))
        min_close_pos = cfg.get_symbol_param_float(symbol, "IMPULSE_BREAKOUT_MIN_CLOSE_POS", float(getattr(cfg, "IMPULSE_BREAKOUT_MIN_CLOSE_POS", 0.68)))
        if rng <= 0.0:
            return False, {"reason": "zero_range"}
        close_pos = (close - low) / rng
        if side == "short":
            close_pos = 1.0 - close_pos

        atr_series = recent["ATR"].astype(float).dropna() if "ATR" in recent.columns else pd.Series(dtype=float)
        atr_ma = float(atr_series.tail(min(12, len(atr_series))).mean()) if len(atr_series) > 0 else atr_ltf
        atr_expanding = atr_ltf >= atr_ma * float(getattr(cfg, "IMPULSE_BREAKOUT_MIN_ATR_EXPANSION", 1.02))

        ok = (
            body >= atr_ltf * min_body_atr
            and rng >= atr_ltf * min_range_atr
            and excursion >= atr_ltf * min_excursion_atr
            and close_pos >= min_close_pos
            and atr_expanding
        )
        return ok, {
            "body": body,
            "range": rng,
            "excursion": excursion,
            "close_pos": close_pos,
            "atr": atr_ltf,
            "atr_ma": atr_ma,
            "atr_expanding": atr_expanding,
        }

    def _calc_alt_quality_score(self, symbol: str, recent: pd.DataFrame, atr_ltf: float, side: str) -> tuple[bool, dict]:
        btc_symbol = str(getattr(cfg, "BTC_REGIME_FILTER_SYMBOL", "BTCUSDT"))
        if not symbol or symbol == btc_symbol:
            return True, {"score": 1.0, "skipped": True}

        wickiness = self._calc_recent_wickiness(recent)
        false_breakout_ratio = self._calc_false_breakout_ratio(recent)
        try:
            closes = recent["close"].astype(float)
            directional_eff = abs(float(closes.iloc[-1]) - float(closes.iloc[0])) / max(float((closes.diff().abs()).sum()), 1e-9)
        except Exception:
            directional_eff = 0.0
        try:
            ranges = (recent["high"].astype(float) - recent["low"].astype(float)).replace(0.0, np.nan)
            body_share = ((recent["close"].astype(float) - recent["open"].astype(float)).abs() / ranges).replace([np.inf, -np.inf], np.nan)
            body_share = float(body_share.tail(min(20, len(body_share))).mean())
        except Exception:
            body_share = 0.0
        price_ref = float(recent["close"].astype(float).iloc[-1]) if len(recent) > 0 else 0.0
        atr_pct = (atr_ltf / price_ref) if price_ref > 0 else 0.0
        atr_low = float(getattr(cfg, "ALT_QUALITY_ATR_LOW_PCT", 0.004))
        atr_high = float(getattr(cfg, "ALT_QUALITY_ATR_HIGH_PCT", 0.03))
        if atr_pct <= atr_low:
            atr_score = max(0.0, atr_pct / max(atr_low, 1e-9))
        elif atr_pct >= atr_high:
            atr_score = max(0.0, 1.0 - min(1.0, (atr_pct - atr_high) / max(atr_high, 1e-9)))
        else:
            atr_score = 1.0
        score = (
            0.34 * max(0.0, 1.0 - wickiness) +
            0.30 * max(0.0, 1.0 - false_breakout_ratio) +
            0.18 * max(0.0, min(1.0, directional_eff)) +
            0.10 * max(0.0, min(1.0, body_share * 1.8)) +
            0.08 * atr_score
        )
        threshold = cfg.get_symbol_param_float(symbol, "ALT_QUALITY_MIN_SCORE", float(getattr(cfg, "ALT_QUALITY_MIN_SCORE", 0.48)))
        return score >= threshold, {
            "score": score,
            "threshold": threshold,
            "wickiness": wickiness,
            "false_breakout_ratio": false_breakout_ratio,
            "directional_eff": directional_eff,
            "body_share": body_share,
            "atr_pct": atr_pct,
            "side": side,
        }

    def _check_breakout_confirmation(self, symbol: str, df: pd.DataFrame, side: str, trigger: float, range_high: float, range_low: float, atr_ltf: float) -> tuple[bool, dict]:
        confirm_enabled = bool(getattr(cfg, "BREAKOUT_CONFIRMATION_ENABLED", True))
        if not confirm_enabled or len(df) < 3:
            return True, {"enabled": False}
        prev = df.iloc[-2]
        last = df.iloc[-1]
        close_prev = float(prev.get("close", np.nan))
        close_now = float(last.get("close", np.nan))
        low_now = float(last.get("low", np.nan))
        high_now = float(last.get("high", np.nan))
        strength_buffer_atr = cfg.get_symbol_param_float(symbol, "BREAKOUT_CONFIRM_BUFFER_ATR", float(getattr(cfg, "BREAKOUT_CONFIRM_BUFFER_ATR", 0.12)))
        min_hold_atr = cfg.get_symbol_param_float(symbol, "BREAKOUT_HOLD_BUFFER_ATR", float(getattr(cfg, "BREAKOUT_HOLD_BUFFER_ATR", 0.05)))
        strength_buffer = strength_buffer_atr * max(atr_ltf, 0.0)
        hold_buffer = min_hold_atr * max(atr_ltf, 0.0)
        require_two_close_alts = bool(getattr(cfg, "BREAKOUT_CONFIRM_TWO_CLOSES_FOR_ALTS", True))
        btc_symbol = str(getattr(cfg, "BTC_REGIME_FILTER_SYMBOL", "BTCUSDT"))
        is_alt = bool(symbol and symbol != btc_symbol)

        if side == "long":
            fast_ok = close_now > trigger + strength_buffer
            hold_ok = close_prev > trigger and close_now > range_high and low_now >= (range_high - hold_buffer)
        else:
            fast_ok = close_now < trigger - strength_buffer
            hold_ok = close_prev < trigger and close_now < range_low and high_now <= (range_low + hold_buffer)

        if is_alt and require_two_close_alts:
            ok = hold_ok or fast_ok
        else:
            ok = fast_ok or hold_ok
        return ok, {
            "fast_ok": fast_ok,
            "hold_ok": hold_ok,
            "close_prev": close_prev,
            "close_now": close_now,
            "trigger": trigger,
            "strength_buffer": strength_buffer,
            "hold_buffer": hold_buffer,
        }

    def _check_btc_regime_filter(self, df: pd.DataFrame, symbol: str, side: str) -> tuple[bool, dict]:
        enabled = bool(getattr(cfg, "BTC_REGIME_FILTER_ENABLED", True))
        if not enabled:
            return True, {"enabled": False}

        btc_symbol = str(getattr(cfg, "BTC_REGIME_FILTER_SYMBOL", "BTCUSDT"))
        alt_symbols = set(getattr(cfg, "BTC_REGIME_ALT_SYMBOLS", ["ETHUSDT", "SOLUSDT", "BNBUSDT", "AVAXUSDT"]) or [])
        if not symbol or symbol == btc_symbol or symbol not in alt_symbols:
            return True, {"enabled": True, "skipped": True}

        needed = ["BTC_HTF_EMA20", "BTC_HTF_EMA50", "BTC_HTF_EMA200", "BTC_HTF_ADX"]
        if not all(c in df.columns for c in needed):
            return False, {"reason": "missing_btc_htf_cols"}
        try:
            ema20 = float(df["BTC_HTF_EMA20"].iloc[-1])
            ema50 = float(df["BTC_HTF_EMA50"].iloc[-1])
            ema200 = float(df["BTC_HTF_EMA200"].iloc[-1])
            adx = float(df["BTC_HTF_ADX"].iloc[-1])
            btc_close = float(df["close"].iloc[-1]) if symbol == btc_symbol else float(df.get("BTC_close", pd.Series([np.nan])).iloc[-1])
        except Exception:
            btc_close = np.nan
            try:
                ema20 = float(df["BTC_HTF_EMA20"].iloc[-1])
                ema50 = float(df["BTC_HTF_EMA50"].iloc[-1])
                ema200 = float(df["BTC_HTF_EMA200"].iloc[-1])
                adx = float(df["BTC_HTF_ADX"].iloc[-1])
            except Exception:
                return False, {"reason": "bad_btc_htf_values"}

        if any(np.isnan(x) for x in [ema20, ema50, ema200, adx]):
            return False, {"reason": "nan_btc_htf_values"}

        btc_regime = self._resolve_regime_from_values(ema20, ema50, ema200)
        soft_adx_min = float(getattr(cfg, "BTC_REGIME_SOFT_ADX_MIN", 14.0))
        hard_adx_min = float(getattr(cfg, "BTC_REGIME_HARD_ADX_MIN", 20.0))
        allow_neutral = bool(getattr(cfg, "BTC_REGIME_ALLOW_NEUTRAL_IF_ADX_OK", True))
        score = 0.0
        expected = "bull" if side == "long" else "bear"

        if btc_regime == expected:
            score += 1.0
        elif btc_regime == "none" and allow_neutral:
            score += 0.45

        if side == "long":
            if ema20 > ema50:
                score += 0.35
            if ema50 > ema200:
                score += 0.35
        else:
            if ema20 < ema50:
                score += 0.35
            if ema50 < ema200:
                score += 0.35

        if adx >= hard_adx_min:
            score += 0.45
        elif adx >= soft_adx_min:
            score += 0.20

        threshold = float(getattr(cfg, "BTC_REGIME_MIN_SCORE_LONG", getattr(cfg, "BTC_REGIME_MIN_SCORE", 0.80))) if side == "long" else float(getattr(cfg, "BTC_REGIME_MIN_SCORE_SHORT", max(float(getattr(cfg, "BTC_REGIME_MIN_SCORE", 0.80)), 1.05)))
        ok = score >= threshold
        return ok, {
            "btc_regime": btc_regime,
            "expected": expected,
            "btc_ema20": ema20,
            "btc_ema50": ema50,
            "btc_ema200": ema200,
            "btc_adx": adx,
            "score": score,
            "threshold": threshold,
            "btc_close": None if np.isnan(btc_close) else btc_close,
        }

    def _check_continuation_entry(self, symbol: str, df: pd.DataFrame, side: str, atr_ltf: float) -> tuple[bool, dict]:
        if len(df) < 120 or atr_ltf <= 0:
            return False, {"reason": "not_enough_continuation_history"}
        need_cols = {"EMA20", "EMA50", "EMA200", "open", "high", "low", "close", "volume", "RSI", "HTF_ADX"}
        if not need_cols.issubset(df.columns):
            return False, {"reason": "missing_continuation_cols"}
        try:
            last = df.iloc[-1]
            prev = df.iloc[-2]
            ema20 = float(last.get("EMA20", np.nan))
            ema50 = float(last.get("EMA50", np.nan))
            ema200 = float(last.get("EMA200", np.nan))
            close = float(last.get("close", np.nan))
            open_ = float(last.get("open", np.nan))
            high = float(last.get("high", np.nan))
            low = float(last.get("low", np.nan))
            prev_close = float(prev.get("close", np.nan))
            prev_open = float(prev.get("open", np.nan))
            prev_ema20 = float(prev.get("EMA20", np.nan))
            prev_high = float(prev.get("high", np.nan))
            prev_low = float(prev.get("low", np.nan))
            rsi = float(last.get("RSI", np.nan))
            htf_adx = float(last.get("HTF_ADX", np.nan))
        except Exception:
            return False, {"reason": "bad_continuation_values"}

        vals = [ema20, ema50, ema200, close, open_, high, low, prev_close, prev_open, prev_ema20, prev_high, prev_low, rsi, htf_adx]
        if any(np.isnan(x) for x in vals):
            return False, {"reason": "nan_continuation_values"}

        body = abs(close - open_)
        prev_body = abs(prev_close - prev_open)
        rng = max(high - low, 0.0)
        prev_rng = max(prev_high - prev_low, 0.0)
        if rng <= 0 or prev_rng <= 0:
            return False, {"reason": "zero_range"}

        trend_ok = (ema20 > ema50 > ema200) if side == "long" else (ema20 < ema50 < ema200)
        if not trend_ok:
            return False, {"reason": "ltf_alignment_fail"}

        touch_atr = cfg.get_symbol_param_float(symbol, "CONTINUATION_TOUCH_ATR", float(getattr(cfg, "CONTINUATION_TOUCH_ATR", 0.28)))
        body_atr = cfg.get_symbol_param_float(symbol, "CONTINUATION_MIN_BODY_ATR", float(getattr(cfg, "CONTINUATION_MIN_BODY_ATR", 0.38)))
        close_pos_min = cfg.get_symbol_param_float(symbol, "CONTINUATION_MIN_CLOSE_POS", float(getattr(cfg, "CONTINUATION_MIN_CLOSE_POS", 0.62)))
        require_prev_pullback = bool(getattr(cfg, "CONTINUATION_REQUIRE_PREV_PULLBACK", True))
        min_htf_adx = cfg.get_symbol_param_float(symbol, "CONTINUATION_MIN_HTF_ADX", float(getattr(cfg, "CONTINUATION_MIN_HTF_ADX", 21.0)))
        min_vol_ratio = cfg.get_symbol_param_float(symbol, "CONTINUATION_MIN_VOL_RATIO", float(getattr(cfg, "CONTINUATION_MIN_VOL_RATIO", 0.98)))
        max_rsi_long = cfg.get_symbol_param_float(symbol, "CONTINUATION_RSI_LONG_MAX", float(getattr(cfg, "CONTINUATION_RSI_LONG_MAX", 63.0)))
        min_rsi_long = cfg.get_symbol_param_float(symbol, "CONTINUATION_RSI_LONG_MIN", float(getattr(cfg, "CONTINUATION_RSI_LONG_MIN", 48.0)))
        min_rsi_short = cfg.get_symbol_param_float(symbol, "CONTINUATION_RSI_SHORT_MIN", float(getattr(cfg, "CONTINUATION_RSI_SHORT_MIN", 37.0)))
        max_rsi_short = cfg.get_symbol_param_float(symbol, "CONTINUATION_RSI_SHORT_MAX", float(getattr(cfg, "CONTINUATION_RSI_SHORT_MAX", 52.0)))
        pullback_depth_atr = cfg.get_symbol_param_float(symbol, "CONTINUATION_PULLBACK_DEPTH_ATR", float(getattr(cfg, "CONTINUATION_PULLBACK_DEPTH_ATR", 0.9)))

        close_pos = (close - low) / rng
        prev_close_pos = (prev_close - prev_low) / prev_rng
        if side == "short":
            close_pos = 1.0 - close_pos
            prev_close_pos = 1.0 - prev_close_pos

        recent = df.tail(min(len(df), 30)).copy()
        try:
            vol = recent["volume"].astype(float)
            vol_ratio = float(last.get("volume", 0.0)) / max(float(vol.ewm(span=12, adjust=False).mean().iloc[-1]), 1e-9)
        except Exception:
            vol_ratio = 1.0

        if side == "long":
            touch_ok = low <= ema20 + atr_ltf * touch_atr
            reclaim_ok = close >= ema20 and close > open_ and close > prev_close and close_pos >= close_pos_min
            prev_pullback_ok = (prev_low <= prev_ema20 + atr_ltf * touch_atr) or (prev_close <= prev_ema20 + atr_ltf * touch_atr)
            pullback_depth_ok = abs(min(prev_low, low) - ema20) <= atr_ltf * pullback_depth_atr
            rsi_ok = min_rsi_long <= rsi <= max_rsi_long
            rejection_ok = prev_close < prev_open and close > open_ and close > prev_open and close > prev_close and prev_close_pos <= 0.55
        else:
            touch_ok = high >= ema20 - atr_ltf * touch_atr
            reclaim_ok = close <= ema20 and close < open_ and close < prev_close and close_pos >= close_pos_min
            prev_pullback_ok = (prev_high >= prev_ema20 - atr_ltf * touch_atr) or (prev_close >= prev_ema20 - atr_ltf * touch_atr)
            pullback_depth_ok = abs(max(prev_high, high) - ema20) <= atr_ltf * pullback_depth_atr
            rsi_ok = min_rsi_short <= rsi <= max_rsi_short
            rejection_ok = prev_close > prev_open and close < open_ and close < prev_open and close < prev_close and prev_close_pos <= 0.55

        ok = (
            touch_ok
            and reclaim_ok
            and prev_pullback_ok if require_prev_pullback else touch_ok and reclaim_ok
        )
        ok = bool(ok and pullback_depth_ok and rejection_ok and body >= atr_ltf * body_atr and rsi_ok and vol_ratio >= min_vol_ratio and htf_adx >= min_htf_adx and body >= prev_body * 0.85)

        return ok, {
            "touch_ok": touch_ok,
            "reclaim_ok": reclaim_ok,
            "prev_pullback_ok": prev_pullback_ok,
            "pullback_depth_ok": pullback_depth_ok,
            "rejection_ok": rejection_ok,
            "body": body,
            "prev_body": prev_body,
            "atr": atr_ltf,
            "rsi": rsi,
            "close_pos": close_pos,
            "prev_close_pos": prev_close_pos,
            "vol_ratio": vol_ratio,
            "ema20": ema20,
            "ema50": ema50,
            "ema200": ema200,
            "htf_adx": htf_adx,
            "side": side,
        }

    def _range_signal(self, symbol: str, df: pd.DataFrame, recent: pd.DataFrame, close: float, atr_ltf: float, adx_h: float, market_meta: dict) -> tuple[Optional[str], dict]:
        if len(recent) < 20 or atr_ltf <= 0 or close <= 0:
            return None, {"reason": "not_enough_range_history"}
        try:
            recent_close = recent["close"].astype(float)
            recent_high = recent["high"].astype(float)
            recent_low = recent["low"].astype(float)
            mean_price = float(recent_close.ewm(span=20, adjust=False).mean().iloc[-1])
            range_high = float(recent_high.max())
            range_low = float(recent_low.min())
            range_mid = (range_high + range_low) * 0.5
            last = df.iloc[-1]
            prev = df.iloc[-2]
            rsi_ltf = float(last.get("RSI", np.nan))
            prev_close = float(prev.get("close", np.nan))
            open_now = float(last.get("open", np.nan))
        except Exception:
            return None, {"reason": "bad_range_inputs"}

        if np.isnan(rsi_ltf) or np.isnan(prev_close) or np.isnan(open_now):
            return None, {"reason": "nan_range_inputs"}

        entry_zone_atr = cfg.get_symbol_param_float(symbol, "RANGE_ENTRY_ZONE_ATR", float(getattr(cfg, "RANGE_ENTRY_ZONE_ATR", 0.8)))
        target_buffer_atr = cfg.get_symbol_param_float(symbol, "RANGE_TARGET_BUFFER_ATR", float(getattr(cfg, "RANGE_TARGET_BUFFER_ATR", 0.35)))
        rsi_long_max = cfg.get_symbol_param_float(symbol, "RANGE_RSI_LONG_MAX", float(getattr(cfg, "RANGE_RSI_LONG_MAX", 28.0)))
        rsi_short_min = cfg.get_symbol_param_float(symbol, "RANGE_RSI_SHORT_MIN", float(getattr(cfg, "RANGE_RSI_SHORT_MIN", 72.0)))
        min_bounce_body_atr = cfg.get_symbol_param_float(symbol, "RANGE_MIN_BOUNCE_BODY_ATR", float(getattr(cfg, "RANGE_MIN_BOUNCE_BODY_ATR", 0.38)))
        min_stretch_atr = cfg.get_symbol_param_float(symbol, "RANGE_MIN_STRETCH_FROM_MEAN_ATR", float(getattr(cfg, "RANGE_MIN_STRETCH_FROM_MEAN_ATR", 1.45)))
        max_state_wickiness = float(getattr(cfg, "RANGE_MAX_STATE_WICKINESS", 0.58))
        max_state_false_breakout = float(getattr(cfg, "RANGE_MAX_STATE_FALSE_BREAKOUT", 0.45))
        max_compression_ratio = float(getattr(cfg, "RANGE_MAX_COMPRESSION_RATIO", 1.12))
        max_adx = float(getattr(cfg, "RANGE_ENTRY_ADX_MAX", getattr(cfg, "MARKET_STATE_RANGE_ADX_MAX", 18.0)))
        bounce_close_pos_min = cfg.get_symbol_param_float(symbol, "RANGE_BOUNCE_MIN_CLOSE_POS", float(getattr(cfg, "RANGE_BOUNCE_MIN_CLOSE_POS", 0.58)))

        lower_zone = range_low + entry_zone_atr * atr_ltf
        upper_zone = range_high - entry_zone_atr * atr_ltf
        body = abs(close - open_now)
        bounce_ok = body >= min_bounce_body_atr * atr_ltf
        stretch_atr = abs(close - mean_price) / atr_ltf if atr_ltf > 0 else 0.0
        candle_range = max(float(last.get("high", close)) - float(last.get("low", close)), 0.0)
        close_pos = ((close - float(last.get("low", close))) / candle_range) if candle_range > 0 else 0.5
        lower_close_ok = close_pos >= bounce_close_pos_min
        upper_close_ok = (1.0 - close_pos) >= bounce_close_pos_min
        state_wickiness = float(market_meta.get("wickiness", 0.0))
        state_false_breakout = float(market_meta.get("false_breakout_ratio", 0.0))
        state_compression = float(market_meta.get("compression_ratio", 0.0))
        state_ok = state_wickiness <= max_state_wickiness and state_false_breakout <= max_state_false_breakout and state_compression <= max_compression_ratio and adx_h <= max_adx

        if close <= lower_zone and rsi_ltf <= rsi_long_max and close > prev_close and bounce_ok and lower_close_ok and stretch_atr >= min_stretch_atr and state_ok and close < (range_mid - target_buffer_atr * atr_ltf):
            return "buy", {
                "range_low": range_low,
                "range_high": range_high,
                "range_mid": range_mid,
                "rsi_ltf": rsi_ltf,
                "adx_h": adx_h,
                "stretch_atr": stretch_atr,
                "state": market_meta,
            }
        if close >= upper_zone and rsi_ltf >= rsi_short_min and close < prev_close and bounce_ok and upper_close_ok and stretch_atr >= min_stretch_atr and state_ok and close > (range_mid + target_buffer_atr * atr_ltf):
            return "sell", {
                "range_low": range_low,
                "range_high": range_high,
                "range_mid": range_mid,
                "rsi_ltf": rsi_ltf,
                "adx_h": adx_h,
                "stretch_atr": stretch_atr,
                "state": market_meta,
            }
        return None, {
            "range_low": range_low,
            "range_high": range_high,
            "range_mid": range_mid,
            "rsi_ltf": rsi_ltf,
            "adx_h": adx_h,
            "state": market_meta,
        }

    def signal(self, df: pd.DataFrame) -> Optional[str]:
        self.last_signal_meta = {"signal": None, "trade_type": None, "risk_multiplier": 1.0}
        if df is None or len(df) < 100:
            return None

        last = df.iloc[-1]

        # --- LTF (M15) ---
        try:
            close = float(last.get("close"))
            high = float(last.get("high"))
            low = float(last.get("low"))
            volume = float(last.get("volume"))
            rsi_ltf = float(last.get("RSI"))
            atr_ltf = float(last.get("ATR"))
        except (TypeError, ValueError):
            return None

        # --- HTF (H1), префикс HTF_ ---
        htf_cols = [
            "HTF_EMA20",
            "HTF_EMA50",
            "HTF_EMA200",
            "HTF_ATR",
            "HTF_ADX",
            "HTF_RSI",
            "HTF_SMA_TREND",
        ]
        for c in htf_cols:
            if c not in df.columns:
                logger.debug("[MTF] Missing column %s, skip signal", c)
                return None

        htf_row = last
        try:
            ema20_h = float(htf_row["HTF_EMA20"])
            ema50_h = float(htf_row["HTF_EMA50"])
            ema200_h = float(htf_row["HTF_EMA200"])
            atr_h = float(htf_row["HTF_ATR"])
            adx_h = float(htf_row["HTF_ADX"])
            rsi_h = float(htf_row["HTF_RSI"])
            sma_trend_h = float(htf_row["HTF_SMA_TREND"])
        except (TypeError, ValueError):
            return None

        import math
        if any(math.isnan(x) for x in [close, ema20_h, ema50_h, ema200_h, atr_h, adx_h, rsi_h, sma_trend_h]):
            return None

        # ======================================================
        # 1) HTF/market state
        # ======================================================
        regime = self._resolve_regime_from_values(ema20_h, ema50_h, ema200_h)
        symbol = self._extract_symbol(df)

        session_ok, session_meta = self._is_allowed_trading_time(df)
        if not session_ok:
            logger.debug("[MTF] skip disallowed trading session: %s", session_meta)
            return None

        if close <= 0 or atr_h <= 0:
            return None

        atr_pct_h = atr_h / close
        min_atr_pct = float(getattr(cfg, "ANTI_CHOP_MIN_ATR_PCT", 0.0005))
        if atr_pct_h < min_atr_pct:
            return None

        # Drift-фильтр по суточному движению цены (примерно 96 баров M15).
        drift_lookback = int(getattr(cfg, "MTF_DRIFT_LOOKBACK_BARS", 96))
        drift_min_pct = float(getattr(cfg, "MTF_DRIFT_MIN_PCT", 0.003))
        drift_strong_pct = float(getattr(cfg, "MTF_DRIFT_STRONG_TREND_PCT", 0.01))

        drift = 0.0
        if len(df) > drift_lookback + 1:
            try:
                close_series = df["close"].astype(float)
                last_price = float(close_series.iloc[-1])
                prev_price = float(close_series.iloc[-drift_lookback - 1])
                if last_price > 0 and prev_price > 0:
                    drift = abs(last_price - prev_price) / last_price
            except Exception:
                drift = 0.0

        # HTF volatile-trendless filter
        htf_volatile_atr = float(getattr(cfg, "HTF_VOLATILE_ATR_PCT", 0.008))
        htf_volatile_drift = float(getattr(cfg, "HTF_VOLATILE_DRIFT_PCT", 0.006))
        htf_volatile_adx = float(getattr(cfg, "HTF_VOLATILE_ADX_MAX", 22))
        drift_h = 0.0
        htf_drift_lookback = int(getattr(cfg, "HTF_DRIFT_LOOKBACK_BARS", 16))
        if len(df) > htf_drift_lookback + 1:
            try:
                close_series_h = df["close"].astype(float)
                last_h = float(close_series_h.iloc[-1])
                prev_h = float(close_series_h.iloc[-htf_drift_lookback - 1])
                if last_h > 0 and prev_h > 0:
                    drift_h = abs(last_h - prev_h) / last_h
            except Exception:
                drift_h = 0.0
        if atr_pct_h > htf_volatile_atr and drift_h < htf_volatile_drift and adx_h < htf_volatile_adx:
            logger.debug("[MTF] skip volatile driftless HTF regime")
            return None

        super_high_atr_pct = float(getattr(cfg, "MTF_ATR_SUPER_HIGH_PCT", 0.02))

        # Фильтры vitality / overextension применяем только к trend-mode, не к range-mode.
        htf_vitality_enabled = bool(getattr(cfg, "HTF_TREND_VITALITY_ENABLED", True))
        if htf_vitality_enabled and regime != "none":
            vitality_ok, vitality_meta = self._check_htf_trend_vitality(df, regime=regime, close=close)
        else:
            vitality_ok, vitality_meta = True, {}

        htf_overextension_enabled = bool(getattr(cfg, "HTF_OVEREXTENSION_FILTER_ENABLED", True))
        if htf_overextension_enabled and regime != "none":
            overext_ok, overext_meta = self._check_htf_overextension(
                close=close, ema20_h=ema20_h, ema50_h=ema50_h, atr_h=atr_h, regime=regime
            )
        else:
            overext_ok, overext_meta = True, {}

        base_recent = df.iloc[-min(max(24, int(getattr(cfg, "RANGE_LOOKBACK", 48))), len(df)):]
        market_state, market_meta = self._classify_market_state(
            symbol=symbol,
            recent=base_recent,
            close=close,
            atr_ltf=atr_ltf,
            atr_h=atr_h,
            adx_h=adx_h,
            drift=drift,
            regime=regime,
        )

        if getattr(cfg, "MTF_DISABLE_VOLATILE_FLAT", True) and atr_pct_h > super_high_atr_pct and market_state != "range":
            logger.debug(
                "[MTF] skip super-high ATR non-range state: atr_pct_h=%.5f > super_high_atr_pct=%.5f",
                atr_pct_h,
                super_high_atr_pct,
            )
            return None

        transition_state = False
        if market_state == "panic":
            logger.debug("[MTF] skip panic market state: %s", market_meta)
            return None
        if market_state == "transition":
            transition_state = True
            logger.debug("[MTF] transition market state: %s", market_meta)

        # Для trend-mode всё ещё требуем достаточно живой HTF-тренд.
        if market_state == "trend":
            if regime == "none":
                return None
            if not vitality_ok:
                logger.debug("[MTF] skip flat HTF trend: %s", vitality_meta)
                return None
            if not overext_ok:
                logger.debug("[MTF] skip overheated HTF move: %s", overext_meta)
                return None

            drift_min_eff = drift_min_pct
            if bool(getattr(cfg, "MTF_DRIFT_ADAPTIVE_ENABLED", True)):
                try:
                    adx_min = float(getattr(cfg, "BREAKOUT_ADX_MIN", 18.0))
                    loosen_factor = float(getattr(cfg, "MTF_DRIFT_MIN_LOOSEN_FACTOR", 0.7))
                    strong_trend_adx_margin = float(getattr(cfg, "MTF_STRONG_TREND_ADX_MARGIN", 5.0))
                    strong_trend = (
                        adx_h >= adx_min + strong_trend_adx_margin
                        and atr_pct_h >= min_atr_pct * 1.5
                        and atr_pct_h <= htf_volatile_atr
                    )
                    if strong_trend:
                        drift_min_eff = drift_min_pct * loosen_factor
                except Exception:
                    drift_min_eff = drift_min_pct
            if drift < drift_min_eff:
                logger.debug(
                    "[MTF] skip low drift trend regime: drift=%.5f < drift_min_eff=%.5f (base=%.5f)",
                    drift,
                    drift_min_eff,
                    drift_min_pct,
                )
                return None

        # ======================================================
        # 2) LTF breakout (M15)
        # ======================================================
        # Динамический lookback на LTF в зависимости от HTF-волатильности.
        # Базовое значение берём из конфигурации, но сужаем/расширяем при высокой/низкой волатильности.
        base_lookback = cfg.get_symbol_param_int(symbol, "MTF_LTF_LOOKBACK", int(getattr(cfg, "MTF_LTF_LOOKBACK", getattr(cfg, "BREAKOUT_LOOKBACK", 20))))
        low_vol_pct = float(getattr(cfg, "MTF_ATR_LOW_VOL_PCT", 0.003))
        high_vol_pct = float(getattr(cfg, "MTF_ATR_HIGH_VOL_PCT", 0.015))
        lb_min = int(getattr(cfg, "MTF_LOOKBACK_MIN", 40))
        lb_max = int(getattr(cfg, "MTF_LOOKBACK_MAX", 80))

        lookback_ltf = base_lookback
        # atr_pct_h уже посчитан выше как atr_h / close
        if atr_pct_h < low_vol_pct:
            # рынок очень спокойный -> расширяем диапазон
            lookback_ltf = min(lb_max, int(base_lookback * 1.3))
        elif atr_pct_h > high_vol_pct:
            # рынок очень волатильный -> чуть сужаем диапазон
            lookback_ltf = max(lb_min, int(base_lookback * 0.7))

        # Дополнительная адаптация lookback по силе тренда (дрейфу).
        # При слабом тренде расширяем диапазон, чтобы реже ловить шумовые пробои.
        # При сильном тренде слегка сужаем, чтобы входить раньше.
        if drift > drift_min_pct and drift < drift_strong_pct:
            lookback_ltf = min(lb_max, int(lookback_ltf * 1.2))
        elif drift >= drift_strong_pct:
            lookback_ltf = max(lb_min, int(lookback_ltf * 0.85))

        if len(df) < lookback_ltf + 2:
            return None

        recent = df.iloc[-lookback_ltf - 1:-1]
        range_high = float(recent["high"].max())
        range_low = float(recent["low"].min())

        # Буфер по цене: BREAKOUT_BUFFER_PCT трактуем как долю (0.001 = 0.1%)
        buf = cfg.get_symbol_param_float(symbol, "BREAKOUT_BUFFER_PCT", float(getattr(cfg, "BREAKOUT_BUFFER_PCT", 0.001)))
        long_trigger = range_high * (1.0 + buf)
        short_trigger = range_low * (1.0 - buf)

        if market_state == "range":
            range_sig, range_meta = self._range_signal(
                symbol=symbol,
                df=df,
                recent=recent,
                close=close,
                atr_ltf=atr_ltf,
                adx_h=adx_h,
                market_meta=market_meta,
            )
            if range_sig is not None:
                logger.debug("[MTF] RANGE %s state=%s meta=%s", range_sig.upper(), market_state, range_meta)
                return self._set_signal(range_sig, trade_type="range", risk_multiplier=float(getattr(cfg, "RISK_MULTIPLIER_RANGE", 0.45)), market_state=market_state, range_meta=range_meta)

        # Более устойчивый volume / momentum фильтр на LTF.
        volume_filter_enabled = bool(getattr(cfg, "BREAKOUT_VOLUME_FILTER_V2_ENABLED", True))
        if volume_filter_enabled:
            volume_ok, volume_meta = self._calc_breakout_volume_momentum(recent=recent, candle=last, atr_ltf=atr_ltf, side="long" if regime == "bull" else "short")
        else:
            volume_ok = True
            volume_meta = {
                "volume": volume,
                "vol_ema": float(recent["volume"].astype(float).ewm(span=20, adjust=False).mean().iloc[-1]),
                "vol_median": float(recent["volume"].median()),
                "impulse_score": 0.0,
                "is_strong_impulse": False,
            }

        # ======================================================
        # 3) LTF ATR-фильтр + RSI-фильтр (вариант B — сбалансированный)
        # ======================================================
        # Фильтруем слишком тихий рынок на M15 по ATR
        if close <= 0 or atr_ltf <= 0:
            return None
        atr_pct_ltf = atr_ltf / close
        ltf_atr_min = float(getattr(cfg, "LTF_ATR_MIN_PCT", 0.0002))
        if atr_pct_ltf < ltf_atr_min:
            return None

        # Дополнительный micro-noise фильтр: если волатильность очень мала и цена почти не двигается,
        # то считаем, что это локальный флэт и пропускаем сигналы.
        micro_atr_pct = float(getattr(cfg, "LTF_MICRO_ATR_PCT", 0.0015))
        slope_lookback = int(getattr(cfg, "LTF_SLOPE_LOOKBACK", 30))
        slope_min_abs = float(getattr(cfg, "LTF_SLOPE_MIN_ABS", 0.001))

        try:
            close_series_ltf = df["close"].astype(float)
            last_price_ltf = float(close_series_ltf.iloc[-1])
            prev_price_ltf = float(close_series_ltf.iloc[-slope_lookback-1]) if len(df) > slope_lookback + 1 else None
        except Exception:
            last_price_ltf = None
            prev_price_ltf = None

        if (
            last_price_ltf is not None
            and prev_price_ltf is not None
            and last_price_ltf > 0.0
        ):
            slope_abs = abs(last_price_ltf - prev_price_ltf) / last_price_ltf
        else:
            slope_abs = None

        # Volatile driftless filter: высокая ATR, но низкий наклон -> волатильная пила без направления.
        volatile_slope_factor = float(getattr(cfg, "LTF_VOLATILE_SLOPE_FACTOR", 5.0))
        if (
            slope_abs is not None
            and atr_pct_ltf > micro_atr_pct
            and slope_abs < slope_min_abs * volatile_slope_factor
        ):
            return None

        rsi_long_min = cfg.get_symbol_param_float(symbol, "MTF_RSI_LONG_MIN", float(getattr(cfg, "MTF_RSI_LONG_MIN", 50.0)))
        rsi_long_max = cfg.get_symbol_param_float(symbol, "MTF_RSI_LONG_MAX", float(getattr(cfg, "MTF_RSI_LONG_MAX", 85.0)))
        rsi_short_min = cfg.get_symbol_param_float(symbol, "MTF_RSI_SHORT_MIN", float(getattr(cfg, "MTF_RSI_SHORT_MIN", 15.0)))
        rsi_short_max = cfg.get_symbol_param_float(symbol, "MTF_RSI_SHORT_MAX", float(getattr(cfg, "MTF_RSI_SHORT_MAX", 55.0)))

        # Адаптивные RSI-диапазоны в зависимости от силы тренда (дрейфа).
        rsi_long_tighten = float(getattr(cfg, "MTF_RSI_LONG_TIGHTEN", 5.0))
        rsi_short_tighten = float(getattr(cfg, "MTF_RSI_SHORT_TIGHTEN", 5.0))

        # При слабом тренде (дрейф ближе к минимальному) ужесточаем фильтры:
        # LONG берём только при более "заряженном" RSI,
        # SHORT берём только при более "разряженном" RSI.
        if drift > drift_min_pct and drift < drift_strong_pct:
            rsi_long_min += rsi_long_tighten
            rsi_short_max -= rsi_short_tighten

        # При очень сильном тренде можно немного ослабить фильтры,
        # чтобы не пропускать хорошие пробои.
        elif drift >= drift_strong_pct:
            rsi_long_min = max(40.0, rsi_long_min - rsi_long_tighten * 0.5)
            rsi_short_max = min(60.0, rsi_short_max + rsi_short_tighten * 0.5)

        # Дополнительная адаптация RSI под силу объёмного импульса пробоя.
        # Слабый импульс -> вход требовательнее. Сильный импульс -> можно чуть смягчить.
        if bool(getattr(cfg, "BREAKOUT_RSI_ADAPT_BY_VOLUME_ENABLED", True)):
            weak_tighten = float(getattr(cfg, "BREAKOUT_RSI_WEAK_VOLUME_TIGHTEN", 2.5))
            strong_loosen = float(getattr(cfg, "BREAKOUT_RSI_STRONG_VOLUME_LOOSEN", 1.5))
            impulse_score = float(volume_meta.get("impulse_score", 0.0))
            strong_impulse = bool(volume_meta.get("is_strong_impulse", False))
            min_impulse_score = float(getattr(cfg, "BREAKOUT_MIN_VOLUME_IMPULSE_SCORE", 0.55))

            if impulse_score < min_impulse_score * 1.15:
                rsi_long_min += weak_tighten
                rsi_short_max -= weak_tighten
            elif strong_impulse:
                rsi_long_min = max(40.0, rsi_long_min - strong_loosen)
                rsi_short_max = min(60.0, rsi_short_max + strong_loosen)

        # ======================================================
        # 4) Итоговые сигналы
        # ======================================================

        breakout_quality_enabled = bool(getattr(cfg, "BREAKOUT_CANDLE_QUALITY_ENABLED", True))

        # Continuation entry: available in trend and transition states.
        continuation_states = {"trend"}
        if bool(getattr(cfg, "CONTINUATION_ALLOW_IN_TRANSITION", True)):
            continuation_states.add("transition")

        if market_state in continuation_states or transition_state:
            if regime == "bull":
                btc_ok, btc_meta = self._check_btc_regime_filter(df, symbol=symbol, side="long")
                alt_ok, alt_meta = self._calc_alt_quality_score(symbol=symbol, recent=recent, atr_ltf=atr_ltf, side="long")
                rs_ok, rs_meta = self._check_relative_strength_filter(df=df, symbol=symbol, side="long")
                cont_ok, cont_meta = self._check_continuation_entry(symbol=symbol, df=df, side="long", atr_ltf=atr_ltf)
                if btc_ok and alt_ok and rs_ok and cont_ok:
                    logger.debug("[MTF] BUY continuation: state=%s rsi=%.2f alt_score=%.3f btc_score=%.3f rs_ratio=%.3f cont=%s", market_state, rsi_ltf, float(alt_meta.get("score", 1.0)), float(btc_meta.get("score", 1.0)), float(rs_meta.get("ratio", 1.0)), cont_meta)
                    return self._set_signal("buy", trade_type="continuation", risk_multiplier=float(cfg.get_symbol_param_float(symbol, "RISK_MULTIPLIER_CONTINUATION", float(getattr(cfg, "RISK_MULTIPLIER_CONTINUATION", 0.65)))), market_state=market_state, cont_meta=cont_meta, side="long")
            elif regime == "bear":
                btc_ok, btc_meta = self._check_btc_regime_filter(df, symbol=symbol, side="short")
                alt_ok, alt_meta = self._calc_alt_quality_score(symbol=symbol, recent=recent, atr_ltf=atr_ltf, side="short")
                rs_ok, rs_meta = self._check_relative_strength_filter(df=df, symbol=symbol, side="short")
                cont_ok, cont_meta = self._check_continuation_entry(symbol=symbol, df=df, side="short", atr_ltf=atr_ltf)
                allow_short = True
                if symbol != str(getattr(cfg, "BTC_REGIME_FILTER_SYMBOL", "BTCUSDT")) and bool(getattr(cfg, "ALT_SHORTS_REQUIRE_STRONG_BTC_BEAR", True)):
                    btc_short_min = float(getattr(cfg, "BTC_REGIME_MIN_SCORE_SHORT", max(float(getattr(cfg, "BTC_REGIME_MIN_SCORE", 0.95)), 1.05)))
                    allow_short = float(btc_meta.get("score", 0.0)) >= btc_short_min
                if btc_ok and alt_ok and rs_ok and cont_ok and allow_short:
                    logger.debug("[MTF] SELL continuation: state=%s rsi=%.2f alt_score=%.3f btc_score=%.3f rs_ratio=%.3f cont=%s", market_state, rsi_ltf, float(alt_meta.get("score", 1.0)), float(btc_meta.get("score", 1.0)), float(rs_meta.get("ratio", 1.0)), cont_meta)
                    return self._set_signal("sell", trade_type="continuation", risk_multiplier=float(cfg.get_symbol_param_float(symbol, "RISK_MULTIPLIER_CONTINUATION", float(getattr(cfg, "RISK_MULTIPLIER_CONTINUATION", 0.65)))), market_state=market_state, cont_meta=cont_meta, side="short")

        if market_state != "trend":
            return None

        if volume_filter_enabled and not volume_ok and not bool(getattr(cfg, "BREAKOUT_ALLOW_WITHOUT_VOLUME_IF_CONTINUATION_ONLY", False)):
            logger.debug("[MTF] skip weak breakout volume/momentum: %s", volume_meta)
            return None

        # LONG: H1 bull-тренд + подтверждённое закрытие M15 выше диапазона
        if regime == "bull" and close > long_trigger and rsi_long_min <= rsi_ltf <= rsi_long_max:
            btc_ok, btc_meta = self._check_btc_regime_filter(df, symbol=symbol, side="long")
            if not btc_ok:
                logger.debug("[MTF] skip BUY by BTC regime filter: %s", btc_meta)
                return None
            alt_ok, alt_meta = self._calc_alt_quality_score(symbol=symbol, recent=recent, atr_ltf=atr_ltf, side="long")
            if not alt_ok:
                logger.debug("[MTF] skip BUY by alt quality: %s", alt_meta)
                return None
            confirm_ok, confirm_meta = self._check_breakout_confirmation(
                symbol=symbol, df=df, side="long", trigger=long_trigger, range_high=range_high, range_low=range_low, atr_ltf=atr_ltf
            )
            if not confirm_ok:
                logger.debug("[MTF] skip BUY by breakout confirmation: %s", confirm_meta)
                return None
            rs_ok, rs_meta = self._check_relative_strength_filter(df=df, symbol=symbol, side="long")
            if not rs_ok:
                logger.debug("[MTF] skip BUY by relative strength: %s", rs_meta)
                return None
            impulse_ok, impulse_meta = self._check_impulse_breakout(symbol=symbol, recent=recent, candle=last, side="long", trigger=long_trigger, atr_ltf=atr_ltf)
            if not impulse_ok:
                logger.debug("[MTF] skip BUY by impulse breakout: %s", impulse_meta)
                return None
            if breakout_quality_enabled:
                quality_ok, quality_meta = self._calc_breakout_candle_quality(last, atr_ltf, side="long")
                if not quality_ok:
                    logger.debug("[MTF] skip BUY poor breakout candle: %s", quality_meta)
                    return None
            else:
                quality_meta = {}

            logger.debug(
                "[MTF] BUY: state=%s close=%.2f rh=%.2f vol=%.0f vol_ema=%.0f vol_med=%.0f imp=%.3f adx_h=%.2f atr_pct_h=%.5f rsi_ltf=%.2f alt_score=%.3f btc_score=%.3f rs_ratio=%.3f exc=%.5f body=%.5f uw=%.5f lw=%.5f",
                market_state,
                close,
                range_high,
                volume,
                float(volume_meta.get("vol_ema", 0.0)),
                float(volume_meta.get("vol_median", 0.0)),
                float(volume_meta.get("impulse_score", 0.0)),
                adx_h,
                atr_pct_h,
                rsi_ltf,
                float(alt_meta.get("score", 1.0)),
                float(btc_meta.get("score", 1.0)),
                float(rs_meta.get("ratio", 1.0)),
                float(impulse_meta.get("excursion", 0.0)),
                float(quality_meta.get("body", 0.0)),
                float(quality_meta.get("upper_wick", 0.0)),
                float(quality_meta.get("lower_wick", 0.0)),
            )
            return self._set_signal("buy", trade_type="impulse", risk_multiplier=float(cfg.get_symbol_param_float(symbol, "RISK_MULTIPLIER_IMPULSE", float(getattr(cfg, "RISK_MULTIPLIER_IMPULSE", 1.00)))), market_state=market_state, impulse_meta=impulse_meta, side="long")

        # SHORT: H1 bear-тренд + подтверждённое закрытие M15 ниже диапазона
        if regime == "bear" and close < short_trigger and rsi_short_min <= rsi_ltf <= rsi_short_max:
            btc_ok, btc_meta = self._check_btc_regime_filter(df, symbol=symbol, side="short")
            if not btc_ok:
                logger.debug("[MTF] skip SELL by BTC regime filter: %s", btc_meta)
                return None
            alt_ok, alt_meta = self._calc_alt_quality_score(symbol=symbol, recent=recent, atr_ltf=atr_ltf, side="short")
            if not alt_ok:
                logger.debug("[MTF] skip SELL by alt quality: %s", alt_meta)
                return None
            if symbol != str(getattr(cfg, "BTC_REGIME_FILTER_SYMBOL", "BTCUSDT")) and bool(getattr(cfg, "ALT_SHORTS_REQUIRE_STRONG_BTC_BEAR", True)):
                btc_short_min = float(getattr(cfg, "BTC_REGIME_MIN_SCORE_SHORT", max(float(getattr(cfg, "BTC_REGIME_MIN_SCORE", 0.95)), 1.05)))
                if float(btc_meta.get("score", 0.0)) < btc_short_min:
                    logger.debug("[MTF] skip SELL weak BTC bear context: %s", btc_meta)
                    return None
            confirm_ok, confirm_meta = self._check_breakout_confirmation(
                symbol=symbol, df=df, side="short", trigger=short_trigger, range_high=range_high, range_low=range_low, atr_ltf=atr_ltf
            )
            if not confirm_ok:
                logger.debug("[MTF] skip SELL by breakout confirmation: %s", confirm_meta)
                return None
            rs_ok, rs_meta = self._check_relative_strength_filter(df=df, symbol=symbol, side="short")
            if not rs_ok:
                logger.debug("[MTF] skip SELL by relative strength: %s", rs_meta)
                return None
            impulse_ok, impulse_meta = self._check_impulse_breakout(symbol=symbol, recent=recent, candle=last, side="short", trigger=short_trigger, atr_ltf=atr_ltf)
            if not impulse_ok:
                logger.debug("[MTF] skip SELL by impulse breakout: %s", impulse_meta)
                return None
            if breakout_quality_enabled:
                quality_ok, quality_meta = self._calc_breakout_candle_quality(last, atr_ltf, side="short")
                if not quality_ok:
                    logger.debug("[MTF] skip SELL poor breakout candle: %s", quality_meta)
                    return None
            else:
                quality_meta = {}

            logger.debug(
                "[MTF] SELL: state=%s close=%.2f rl=%.2f vol=%.0f vol_ema=%.0f vol_med=%.0f imp=%.3f adx_h=%.2f atr_pct_h=%.5f rsi_ltf=%.2f alt_score=%.3f btc_score=%.3f rs_ratio=%.3f exc=%.5f body=%.5f uw=%.5f lw=%.5f",
                market_state,
                close,
                range_low,
                volume,
                float(volume_meta.get("vol_ema", 0.0)),
                float(volume_meta.get("vol_median", 0.0)),
                float(volume_meta.get("impulse_score", 0.0)),
                adx_h,
                atr_pct_h,
                rsi_ltf,
                float(alt_meta.get("score", 1.0)),
                float(btc_meta.get("score", 1.0)),
                float(rs_meta.get("ratio", 1.0)),
                float(impulse_meta.get("excursion", 0.0)),
                float(quality_meta.get("body", 0.0)),
                float(quality_meta.get("upper_wick", 0.0)),
                float(quality_meta.get("lower_wick", 0.0)),
            )
            return self._set_signal("sell", trade_type="impulse", risk_multiplier=float(cfg.get_symbol_param_float(symbol, "RISK_MULTIPLIER_IMPULSE", float(getattr(cfg, "RISK_MULTIPLIER_IMPULSE", 1.00)))), market_state=market_state, impulse_meta=impulse_meta, side="short")

        return None
