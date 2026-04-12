import numpy as np
import pandas as pd

from .mtf_market_helpers import calc_false_breakout_ratio, calc_recent_wickiness


def check_htf_trend_vitality(*, cfg, df: pd.DataFrame, regime: str, close: float) -> tuple[bool, dict]:
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
            return False, {"reason": "ema20_ema50_too_close", "dist20_50_pct": dist20_50_pct, "min": min_dist_pct}

        return True, {"slope50": slope50, "slope200": slope200, "dist20_50_pct": dist20_50_pct}
    except Exception as exc:
        return False, {"reason": "htf_vitality_exception", "error": str(exc)}


def check_htf_overextension(*, cfg, close: float, ema20_h: float, ema50_h: float, atr_h: float, regime: str) -> tuple[bool, dict]:
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
            return False, {"reason": "too_far_from_htf_ema20", "dist20_atr": dist20_atr, "max": max_dist_ema20_atr}
        if dist50_atr > max_dist_ema50_atr:
            return False, {"reason": "too_far_from_htf_ema50", "dist50_atr": dist50_atr, "max": max_dist_ema50_atr}

        return True, {"dist20_atr": dist20_atr, "dist50_atr": dist50_atr}
    except Exception as exc:
        return False, {"reason": "htf_overextension_exception", "error": str(exc)}


def classify_market_state(*, cfg, symbol: str, recent: pd.DataFrame, close: float, atr_ltf: float, atr_h: float, adx_h: float, drift: float, regime: str) -> tuple[str, dict]:
    atr_pct_h = (atr_h / close) if close > 0 else 0.0
    atr_pct_ltf = (atr_ltf / close) if close > 0 else 0.0
    wickiness = calc_recent_wickiness(recent)
    false_breakout_ratio = calc_false_breakout_ratio(recent, lookback=min(12, max(6, len(recent) // 5)))
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

    payload = {
        "atr_pct_h": atr_pct_h,
        "atr_pct_ltf": atr_pct_ltf,
        "wickiness": wickiness,
        "false_breakout_ratio": false_breakout_ratio,
        "range_width": range_width,
        "compression_ratio": compression_ratio,
    }
    if atr_pct_h >= panic_atr_pct or (wickiness >= panic_wickiness and false_breakout_ratio >= 0.45):
        return "panic", payload

    if regime != "none" and adx_h >= trend_adx_min and drift >= trend_drift_floor and false_breakout_ratio <= 0.55:
        return "trend", payload

    if adx_h <= range_adx_max and range_width <= range_max_width and compression_ratio <= float(getattr(cfg, "RANGE_MAX_COMPRESSION_RATIO", 1.12)):
        return "range", payload

    transition_false_breakout = float(getattr(cfg, "MARKET_STATE_TRANSITION_FALSE_BREAKOUT_MIN", 0.58))
    transition_wickiness = float(getattr(cfg, "MARKET_STATE_TRANSITION_WICKINESS_MIN", 0.62))
    if regime == "none" or false_breakout_ratio >= transition_false_breakout or wickiness >= transition_wickiness:
        return "transition", payload

    return "trend", payload
