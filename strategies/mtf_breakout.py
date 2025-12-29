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
        regime = "none"
        if ema20_h > ema50_h > ema200_h:
            regime = "bull"
        elif ema20_h < ema50_h < ema200_h:
            regime = "bear"

        if regime == "none":
            return None

        # Фильтр слишком тихого рынка по HTF ATR
        if close <= 0 or atr_h <= 0:
            return None
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

        # LONG: H1 bull-тренд + пробой вверх на M15
        if regime == "bull" and close > long_trigger and rsi_long_min <= rsi_ltf <= rsi_long_max:
            logger.debug(
                "[MTF] BUY: close=%.2f rh=%.2f vol=%.0f vol_ma=%.0f adx_h=%.2f atr_pct_h=%.5f rsi_ltf=%.2f",
                close, range_high, volume, vol_ma, adx_h, atr_pct_h, rsi_ltf,
            )
            return "buy"

        # SHORT: H1 bear-тренд + пробой вниз на M15
        if regime == "bear" and close < short_trigger and rsi_short_min <= rsi_ltf <= rsi_short_max:
            logger.debug(
                "[MTF] SELL: close=%.2f rl=%.2f vol=%.0f vol_ma=%.0f adx_h=%.2f atr_pct_h=%.5f rsi_ltf=%.2f",
                close, range_low, volume, vol_ma, adx_h, atr_pct_h, rsi_ltf,
            )
            return "sell"

        return None
