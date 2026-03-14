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

    def _check_btc_regime_filter(self, df: pd.DataFrame, symbol: str, side: str) -> tuple[bool, dict]:
        enabled = bool(getattr(cfg, "BTC_REGIME_FILTER_ENABLED", True))
        if not enabled:
            return True, {"enabled": False}

        btc_symbol = str(getattr(cfg, "BTC_REGIME_FILTER_SYMBOL", "BTCUSDT"))
        alt_symbols = set(getattr(cfg, "BTC_REGIME_ALT_SYMBOLS", ["ETHUSDT", "SOLUSDT", "BNBUSDT", "AVAXUSDT"]) or [])
        if not symbol or symbol == btc_symbol or symbol not in alt_symbols:
            return True, {"enabled": True, "skipped": True}

        needed = ["BTC_HTF_EMA20", "BTC_HTF_EMA50", "BTC_HTF_EMA200"]
        if not all(c in df.columns for c in needed):
            return False, {"reason": "missing_btc_htf_cols"}

        try:
            ema20 = float(df["BTC_HTF_EMA20"].iloc[-1])
            ema50 = float(df["BTC_HTF_EMA50"].iloc[-1])
            ema200 = float(df["BTC_HTF_EMA200"].iloc[-1])
        except Exception:
            return False, {"reason": "bad_btc_htf_values"}

        import math
        if any(math.isnan(x) for x in [ema20, ema50, ema200]):
            return False, {"reason": "nan_btc_htf_values"}

        btc_regime = self._resolve_regime_from_values(ema20, ema50, ema200)
        expected = "bull" if side == "long" else "bear"
        ok = btc_regime == expected
        return ok, {
            "btc_regime": btc_regime,
            "expected": expected,
            "btc_ema20": ema20,
            "btc_ema50": ema50,
            "btc_ema200": ema200,
        }

    def signal(self, df: pd.DataFrame) -> Optional[str]:
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
        # 1) HTF-тренд (строгий вариант C)
        # ======================================================
        regime = self._resolve_regime_from_values(ema20_h, ema50_h, ema200_h)

        if regime == "none":
            return None

        symbol = self._extract_symbol(df)

        # Фильтр «живого» HTF-тренда: не входим, если EMA уже выстроены,
        # но наклон и дистанция между ними указывают на выдыхающийся тренд.
        htf_vitality_enabled = bool(getattr(cfg, "HTF_TREND_VITALITY_ENABLED", True))
        if htf_vitality_enabled:
            vitality_ok, vitality_meta = self._check_htf_trend_vitality(df, regime=regime, close=close)
            if not vitality_ok:
                logger.debug("[MTF] skip flat HTF trend: %s", vitality_meta)
                return None
        else:
            vitality_meta = {}

        # Фильтр слишком тихого рынка по HTF ATR
        if close <= 0 or atr_h <= 0:
            return None

        htf_overextension_enabled = bool(getattr(cfg, "HTF_OVEREXTENSION_FILTER_ENABLED", True))
        if htf_overextension_enabled:
            overext_ok, overext_meta = self._check_htf_overextension(
                close=close, ema20_h=ema20_h, ema50_h=ema50_h, atr_h=atr_h, regime=regime
            )
            if not overext_ok:
                logger.debug("[MTF] skip overheated HTF move: %s", overext_meta)
                return None
        else:
            overext_meta = {}

        atr_pct_h = atr_h / close
        min_atr_pct = float(getattr(cfg, "ANTI_CHOP_MIN_ATR_PCT", 0.0005))
        if atr_pct_h < min_atr_pct:
            return None

        # Фильтр силы тренда по HTF ADX
        adx_min = float(getattr(cfg, "BREAKOUT_ADX_MIN", 18.0))
        if adx_h < adx_min:
            return None


        # HTF volatile-trendless filter
        htf_volatile_atr=float(getattr(cfg,"HTF_VOLATILE_ATR_PCT",0.008))
        htf_volatile_drift=float(getattr(cfg,"HTF_VOLATILE_DRIFT_PCT",0.006))
        htf_volatile_adx=float(getattr(cfg,"HTF_VOLATILE_ADX_MAX",22))

        # compute "HTF-like" drift using M15 closes as approximation
        drift_h = 0.0
        htf_drift_lookback = int(getattr(cfg, "HTF_DRIFT_LOOKBACK_BARS", 16))
        if len(df) > htf_drift_lookback + 1:
            try:
                close_series_h = df["close"].astype(float)
                last_h = float(close_series_h.iloc[-1])
                prev_h = float(close_series_h.iloc[-htf_drift_lookback-1])
                if last_h > 0 and prev_h > 0:
                    drift_h = abs(last_h - prev_h) / last_h
            except Exception:
                drift_h = 0.0

        if atr_pct_h > htf_volatile_atr and drift_h < htf_volatile_drift and adx_h < htf_volatile_adx:
            return None

        # Дополнительный фильтр "взрывного флэта" по HTF ATR.
        # При экстремально высокой волатильности на H1 стратегия по бэктестам
        # начинает ухудшать результат, поэтому блокируем новые входы.
        super_high_atr_pct = float(getattr(cfg, "MTF_ATR_SUPER_HIGH_PCT", 0.02))
        if getattr(cfg, "MTF_DISABLE_VOLATILE_FLAT", True) and atr_pct_h > super_high_atr_pct:
            logger.debug(
                "[MTF] skip volatile flat: atr_pct_h=%.5f > super_high_atr_pct=%.5f",
                atr_pct_h,
                super_high_atr_pct,
            )
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

        # Адаптивный порог дрейфа: в хорошем тренде можно слегка ослабить фильтр,
        # чтобы не выкидывать "почти достаточные" движения.
        drift_min_eff = drift_min_pct
        if bool(getattr(cfg, "MTF_DRIFT_ADAPTIVE_ENABLED", True)):
            try:
                # сильный тренд: ADX заметно выше минимума и ATR не в "супер-тихом" режиме
                adx_min = float(getattr(cfg, "BREAKOUT_ADX_MIN", 18.0))
                loosen_factor = float(getattr(cfg, "MTF_DRIFT_MIN_LOOSEN_FACTOR", 0.7))
                strong_trend_adx_margin = float(getattr(cfg, "MTF_STRONG_TREND_ADX_MARGIN", 5.0))
                # Используем уже посчитанный atr_pct_h и пороги ANTI_CHOP / HTF_VOLATILE_ATR_PCT,
                # чтобы не раздувать сделки в экстремальном флэте.
                min_atr_pct = float(getattr(cfg, "ANTI_CHOP_MIN_ATR_PCT", 0.0005))
                htf_volatile_atr = float(getattr(cfg, "HTF_VOLATILE_ATR_PCT", 0.008))
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
                "[MTF] skip low drift regime: drift=%.5f < drift_min_eff=%.5f (base=%.5f)",
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
        base_lookback = int(getattr(cfg, "MTF_LTF_LOOKBACK", getattr(cfg, "BREAKOUT_LOOKBACK", 20)))
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
        buf = float(getattr(cfg, "BREAKOUT_BUFFER_PCT", 0.001))
        long_trigger = range_high * (1.0 + buf)
        short_trigger = range_low * (1.0 - buf)

        # Объёмный фильтр на LTF
        vol_ma = float(recent["volume"].mean())
        vol_mult = float(getattr(cfg, "BREAKOUT_VOLUME_MULT", 1.5))
        if vol_ma > 0 and volume < vol_ma * vol_mult:
            return None

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

        rsi_long_min = float(getattr(cfg, "MTF_RSI_LONG_MIN", 50.0))
        rsi_long_max = float(getattr(cfg, "MTF_RSI_LONG_MAX", 85.0))
        rsi_short_min = float(getattr(cfg, "MTF_RSI_SHORT_MIN", 15.0))
        rsi_short_max = float(getattr(cfg, "MTF_RSI_SHORT_MAX", 55.0))

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

        # ======================================================
        # 4) Итоговые сигналы
        # ======================================================

        breakout_quality_enabled = bool(getattr(cfg, "BREAKOUT_CANDLE_QUALITY_ENABLED", True))

        # LONG: H1 bull-тренд + подтверждённое закрытие M15 выше диапазона
        if regime == "bull" and close > long_trigger and rsi_long_min <= rsi_ltf <= rsi_long_max:
            btc_ok, btc_meta = self._check_btc_regime_filter(df, symbol=symbol, side="long")
            if not btc_ok:
                logger.debug("[MTF] skip BUY by BTC regime filter: %s", btc_meta)
                return None
            if breakout_quality_enabled:
                quality_ok, quality_meta = self._calc_breakout_candle_quality(last, atr_ltf, side="long")
                if not quality_ok:
                    logger.debug("[MTF] skip BUY poor breakout candle: %s", quality_meta)
                    return None
            else:
                quality_meta = {}

            logger.debug(
                "[MTF] BUY: close=%.2f rh=%.2f vol=%.0f vol_ma=%.0f adx_h=%.2f atr_pct_h=%.5f rsi_ltf=%.2f htf_s50=%.5f htf_s200=%.5f htf_d20_50=%.5f htf_d20_atr=%.3f htf_d50_atr=%.3f body=%.5f uw=%.5f lw=%.5f",
                close,
                range_high,
                volume,
                vol_ma,
                adx_h,
                atr_pct_h,
                rsi_ltf,
                float(vitality_meta.get("slope50", 0.0)),
                float(vitality_meta.get("slope200", 0.0)),
                float(vitality_meta.get("dist20_50_pct", 0.0)),
                float(overext_meta.get("dist20_atr", 0.0)),
                float(overext_meta.get("dist50_atr", 0.0)),
                float(quality_meta.get("body", 0.0)),
                float(quality_meta.get("upper_wick", 0.0)),
                float(quality_meta.get("lower_wick", 0.0)),
            )
            return "buy"

        # SHORT: H1 bear-тренд + подтверждённое закрытие M15 ниже диапазона
        if regime == "bear" and close < short_trigger and rsi_short_min <= rsi_ltf <= rsi_short_max:
            btc_ok, btc_meta = self._check_btc_regime_filter(df, symbol=symbol, side="short")
            if not btc_ok:
                logger.debug("[MTF] skip SELL by BTC regime filter: %s", btc_meta)
                return None
            if breakout_quality_enabled:
                quality_ok, quality_meta = self._calc_breakout_candle_quality(last, atr_ltf, side="short")
                if not quality_ok:
                    logger.debug("[MTF] skip SELL poor breakout candle: %s", quality_meta)
                    return None
            else:
                quality_meta = {}

            logger.debug(
                "[MTF] SELL: close=%.2f rl=%.2f vol=%.0f vol_ma=%.0f adx_h=%.2f atr_pct_h=%.5f rsi_ltf=%.2f htf_s50=%.5f htf_s200=%.5f htf_d20_50=%.5f htf_d20_atr=%.3f htf_d50_atr=%.3f body=%.5f uw=%.5f lw=%.5f",
                close,
                range_low,
                volume,
                vol_ma,
                adx_h,
                atr_pct_h,
                rsi_ltf,
                float(vitality_meta.get("slope50", 0.0)),
                float(vitality_meta.get("slope200", 0.0)),
                float(vitality_meta.get("dist20_50_pct", 0.0)),
                float(overext_meta.get("dist20_atr", 0.0)),
                float(overext_meta.get("dist50_atr", 0.0)),
                float(quality_meta.get("body", 0.0)),
                float(quality_meta.get("upper_wick", 0.0)),
                float(quality_meta.get("lower_wick", 0.0)),
            )
            return "sell"

        return None
