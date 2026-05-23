from __future__ import annotations

from typing import Optional
import pandas as pd


def _f(series: pd.Series, name: str, default: float = 0.0) -> float:
    try:
        return float(series.get(name, default))
    except Exception:
        return float(default)



def _safe_median_range(df: pd.DataFrame) -> float:
    try:
        if len(df) <= 0 or "high" not in df.columns or "low" not in df.columns:
            return 0.0
        return float((df["high"].astype(float) - df["low"].astype(float)).clip(lower=0).median())
    except Exception:
        return 0.0

def _momentum_ok(*, cfg, side: str, close: float, open_: float, high: float, low: float, prev_high: float, prev_low: float, atr_ltf: float) -> tuple[bool, str, dict]:
    body_atr = abs(close - open_) / max(atr_ltf, 1e-9)
    range_atr = max(high - low, 0.0) / max(atr_ltf, 1e-9)
    min_body = float(getattr(cfg, "V15_ETH_MIN_MOMENTUM_BODY_ATR", 0.32))
    min_range = float(getattr(cfg, "V15_ETH_MIN_MOMENTUM_RANGE_ATR", 0.55))
    break_atr = float(getattr(cfg, "V15_ETH_CLOSE_THROUGH_PREV_EXTREME_ATR", 0.02))
    require_break = bool(getattr(cfg, "V15_ETH_REQUIRE_CLOSE_THROUGH_PREV_EXTREME", True))
    meta = {"body_atr": body_atr, "range_atr": range_atr}
    if body_atr < min_body:
        return False, "momentum_body_too_small", meta
    if range_atr < min_range:
        return False, "momentum_range_too_small", meta
    if side == "long":
        if close <= open_:
            return False, "no_bullish_momentum", meta
        if require_break and close < (prev_high + break_atr * atr_ltf):
            return False, "no_momentum_break_prev_high", meta
    else:
        if close >= open_:
            return False, "no_bearish_momentum", meta
        if require_break and close > (prev_low - break_atr * atr_ltf):
            return False, "no_momentum_break_prev_low", meta
    return True, "momentum_confirmed", meta


def _eth_trend_momentum(*, cfg, symbol: str, market_state: str, regime: str, recent: pd.DataFrame, last: pd.Series, close: float, atr_ltf: float, adx_h: float, drift: float, range_high: float, range_low: float) -> tuple[Optional[str], Optional[str], float, dict]:
    if not bool(getattr(cfg, "V17_ETH_TREND_ENGINE_ENABLED", False)):
        return None, None, 1.0, {"reason": "eth_trend_engine_disabled"}

    symbol_u = str(symbol or "").upper()
    alt_symbols = set(getattr(cfg, "V27_ALT_TREND_SYMBOLS", []) or [])
    is_v27_alt = bool(getattr(cfg, "V27_MULTI_ASSET_TREND_ENABLED", False)) and symbol_u in alt_symbols

    v30_expand = bool(getattr(cfg, "V30_EXPAND_TREND_ENABLED", False)) and not bool(getattr(cfg, "V32_FORCE_DISABLE_EXPANDED_TREND", False))

    if is_v27_alt:
        prefix = "V27_ALT_TREND"
        reason_prefix = "alt_trend"
        engine_name = "alt_trend_v30" if v30_expand else "alt_trend_v27"
        trade_type = str(getattr(cfg, "V27_ALT_TREND_TRADE_TYPE", "alt_trend_momentum"))
        allowed_states = set(getattr(cfg, "V30_ALT_TREND_ALLOWED_MARKET_STATES" if v30_expand else "V27_ALT_TREND_ALLOWED_MARKET_STATES", ["trend"]) or ["trend"])
        min_adx = float(getattr(cfg, "V30_ALT_TREND_MIN_ADX" if v30_expand else "V27_ALT_TREND_MIN_ADX", 29.0))
        min_drift = float(getattr(cfg, "V30_ALT_TREND_MIN_DRIFT_PCT" if v30_expand else "V27_ALT_TREND_MIN_DRIFT_PCT", 0.018))
        max_drift = float(getattr(cfg, "V30_ALT_TREND_MAX_DRIFT_PCT" if v30_expand else "V27_ALT_TREND_MAX_DRIFT_PCT", 0.095))
        min_body = float(getattr(cfg, "V30_ALT_TREND_MIN_BODY_ATR" if v30_expand else "V27_ALT_TREND_MIN_BODY_ATR", 0.42))
        min_range = float(getattr(cfg, "V30_ALT_TREND_MIN_RANGE_ATR" if v30_expand else "V27_ALT_TREND_MIN_RANGE_ATR", 0.72))
        break_buf_atr = float(getattr(cfg, "V30_ALT_TREND_BREAKOUT_BUFFER_ATR" if v30_expand else "V27_ALT_TREND_BREAKOUT_BUFFER_ATR", 0.075))
        align = bool(getattr(cfg, "V30_ALT_TREND_REQUIRE_REGIME_ALIGNMENT" if v30_expand else "V27_ALT_TREND_REQUIRE_REGIME_ALIGNMENT", True))
        allow_long = bool(getattr(cfg, "V27_ALT_TREND_ALLOW_LONG", True))
        allow_short = bool(getattr(cfg, "V27_ALT_TREND_ALLOW_SHORT", True))
        long_risk = float(getattr(cfg, "V30_ALT_TREND_LONG_RISK_MULT" if v30_expand else "V27_ALT_TREND_LONG_RISK_MULT", 0.020))
        short_risk = float(getattr(cfg, "V30_ALT_TREND_SHORT_RISK_MULT" if v30_expand else "V27_ALT_TREND_SHORT_RISK_MULT", 0.012))
        short_min_adx = float(getattr(cfg, "V30_ALT_TREND_SHORT_MIN_ADX" if v30_expand else "V27_ALT_TREND_SHORT_MIN_ADX", 34.0))
        short_min_drift = float(getattr(cfg, "V30_ALT_TREND_SHORT_MIN_DRIFT_PCT" if v30_expand else "V27_ALT_TREND_SHORT_MIN_DRIFT_PCT", 0.026))
        short_min_body = float(getattr(cfg, "V30_ALT_TREND_SHORT_MIN_BODY_ATR" if v30_expand else "V27_ALT_TREND_SHORT_MIN_BODY_ATR", 0.52))
    else:
        reason_prefix = "eth_trend"
        engine_name = "eth_trend_v30" if v30_expand else "eth_trend_v18"
        allowed_states = set(getattr(cfg, "V30_ETH_TREND_ALLOWED_MARKET_STATES" if v30_expand else "V17_ETH_TREND_ALLOWED_MARKET_STATES", ["trend"]) or ["trend"])
        min_adx = float(getattr(cfg, "V30_ETH_TREND_MIN_ADX" if v30_expand else "V18_ETH_TREND_MIN_ADX", getattr(cfg, "V17_ETH_TREND_MIN_ADX", 24.0)))
        min_drift = float(getattr(cfg, "V30_ETH_TREND_MIN_DRIFT_PCT" if v30_expand else "V18_ETH_TREND_MIN_DRIFT_PCT", getattr(cfg, "V17_ETH_TREND_MIN_DRIFT_PCT", 0.0100)))
        max_drift = float(getattr(cfg, "V30_ETH_TREND_MAX_DRIFT_PCT" if v30_expand else "V18_ETH_TREND_MAX_DRIFT_PCT", getattr(cfg, "V17_ETH_TREND_MAX_DRIFT_PCT", 0.0700)))
        min_body = float(getattr(cfg, "V30_ETH_TREND_MIN_BODY_ATR" if v30_expand else "V18_ETH_TREND_MIN_BODY_ATR", getattr(cfg, "V17_ETH_TREND_MIN_BODY_ATR", 0.22)))
        min_range = float(getattr(cfg, "V30_ETH_TREND_MIN_RANGE_ATR" if v30_expand else "V18_ETH_TREND_MIN_RANGE_ATR", getattr(cfg, "V17_ETH_TREND_MIN_RANGE_ATR", 0.45)))
        break_buf_atr = float(getattr(cfg, "V30_ETH_TREND_BREAKOUT_BUFFER_ATR" if v30_expand else "V18_ETH_TREND_BREAKOUT_BUFFER_ATR", getattr(cfg, "V17_ETH_TREND_BREAKOUT_BUFFER_ATR", 0.05)))
        align = bool(getattr(cfg, "V30_ETH_TREND_REQUIRE_REGIME_ALIGNMENT" if v30_expand else "V18_ETH_TREND_REQUIRE_REGIME_ALIGNMENT", getattr(cfg, "V17_ETH_TREND_REQUIRE_REGIME_ALIGNMENT", True)))
        allow_long = bool(getattr(cfg, "V18_ETH_TREND_ALLOW_LONG", getattr(cfg, "V17_ETH_TREND_ALLOW_LONG", True)))
        allow_short = bool(getattr(cfg, "V18_ETH_TREND_ALLOW_SHORT", getattr(cfg, "V17_ETH_TREND_ALLOW_SHORT", True)))
        trade_type = str(getattr(cfg, "V18_ETH_TREND_TRADE_TYPE", getattr(cfg, "V17_ETH_TREND_TRADE_TYPE", "eth_trend_momentum")))
        long_risk = float(getattr(cfg, "V30_ETH_TREND_LONG_RISK_MULT" if v30_expand else "V18_ETH_TREND_LONG_RISK_MULT", getattr(cfg, "V17_ETH_TREND_LONG_RISK_MULT", 0.040)))
        short_risk = float(getattr(cfg, "V30_ETH_TREND_SHORT_RISK_MULT" if v30_expand else "V18_ETH_TREND_SHORT_RISK_MULT", getattr(cfg, "V17_ETH_TREND_SHORT_RISK_MULT", 0.030)))
        short_min_adx = float(getattr(cfg, "V30_ETH_TREND_SHORT_MIN_ADX" if v30_expand else "V18_ETH_TREND_SHORT_MIN_ADX", 30.0))
        short_min_drift = float(getattr(cfg, "V30_ETH_TREND_SHORT_MIN_DRIFT_PCT" if v30_expand else "V18_ETH_TREND_SHORT_MIN_DRIFT_PCT", 0.0180))
        short_min_body = float(getattr(cfg, "V30_ETH_TREND_SHORT_MIN_BODY_ATR" if v30_expand else "V18_ETH_TREND_SHORT_MIN_BODY_ATR", 0.34))

    if market_state not in allowed_states:
        return None, None, 1.0, {"reason": f"{reason_prefix}_state_not_allowed", "market_state": market_state}
    if adx_h < min_adx:
        return None, None, 1.0, {"reason": f"{reason_prefix}_adx_too_low", "adx_h": adx_h}

    abs_drift = abs(float(drift))
    if abs_drift < min_drift:
        return None, None, 1.0, {"reason": f"{reason_prefix}_drift_too_low", "drift": drift}
    if abs_drift > max_drift:
        return None, None, 1.0, {"reason": f"{reason_prefix}_drift_too_high", "drift": drift}

    open_ = _f(last, "open", close)
    high = _f(last, "high", close)
    low = _f(last, "low", close)
    body_atr = abs(close - open_) / max(atr_ltf, 1e-9)
    range_atr = max(high - low, 0.0) / max(atr_ltf, 1e-9)
    if body_atr < min_body:
        return None, None, 1.0, {"reason": f"{reason_prefix}_body_too_small", "body_atr": body_atr}
    if range_atr < min_range:
        return None, None, 1.0, {"reason": f"{reason_prefix}_range_too_small", "range_atr": range_atr}

    break_buf = break_buf_atr * max(atr_ltf, 1e-9)
    long_ok = allow_long and close > open_ and close > (range_high + break_buf)
    if long_ok and align and str(regime).lower() == "bear":
        long_ok = False
    if long_ok:
        return "buy", trade_type, long_risk, {"reason": f"{reason_prefix}_momentum_long", "engine": engine_name, "side": "long", "market_state": market_state, "regime": regime, "body_atr": body_atr, "range_atr": range_atr, "adx_h": adx_h, "drift": drift}

    short_ok = allow_short and close < open_ and close < (range_low - break_buf)
    if short_ok and align and str(regime).lower() == "bull":
        short_ok = False
    if short_ok and adx_h < short_min_adx:
        return None, None, 1.0, {"reason": f"{reason_prefix}_short_adx_too_low", "adx_h": adx_h}
    if short_ok and abs_drift < short_min_drift:
        return None, None, 1.0, {"reason": f"{reason_prefix}_short_drift_too_low", "drift": drift}
    if short_ok and body_atr < short_min_body:
        return None, None, 1.0, {"reason": f"{reason_prefix}_short_body_too_small", "body_atr": body_atr}
    if short_ok:
        return "sell", trade_type, short_risk, {"reason": f"{reason_prefix}_momentum_short", "engine": engine_name, "side": "short", "market_state": market_state, "regime": regime, "body_atr": body_atr, "range_atr": range_atr, "adx_h": adx_h, "drift": drift}

    return None, None, 1.0, {"reason": f"{reason_prefix}_no_breakout", "body_atr": body_atr, "range_atr": range_atr, "adx_h": adx_h, "drift": drift}




def _v36_trend_pullback(*, cfg, symbol: str, market_state: str, regime: str, recent: pd.DataFrame, last: pd.Series, close: float, atr_ltf: float, adx_h: float, drift: float, range_high: float, range_low: float) -> tuple[Optional[str], Optional[str], float, dict]:
    """v36 pullback entry inside an existing HTF trend.

    This is deliberately NOT a breakout/range/micro fallback. It only enters when
    the higher-timeframe trend is already strong enough, price has pulled back
    toward a short EMA, and the current candle reclaims/rejects that EMA.
    BTC is not routed here.
    """
    symbol_u = str(symbol or "").upper()
    if not bool(getattr(cfg, "V36_PULLBACK_ENGINE_ENABLED", False)):
        return None, None, 1.0, {"reason": "v36_pullback_disabled"}
    if symbol_u not in set(getattr(cfg, "V36_PULLBACK_SYMBOLS", []) or []):
        return None, None, 1.0, {"reason": "v36_symbol_not_allowed", "symbol": symbol_u}
    if market_state not in set(getattr(cfg, "V36_PULLBACK_ALLOWED_MARKET_STATES", ["trend"]) or ["trend"]):
        return None, None, 1.0, {"reason": "v36_state_not_allowed", "market_state": market_state}
    if atr_ltf <= 0 or close <= 0 or len(recent) < int(getattr(cfg, "V36_PULLBACK_MIN_RECENT_BARS", 48)):
        return None, None, 1.0, {"reason": "v36_bad_inputs"}

    is_alt = symbol_u not in {"ETHUSDT"}
    min_adx = float(getattr(cfg, "V36_PULLBACK_MIN_ADX_ALT" if is_alt else "V36_PULLBACK_MIN_ADX_ETH", 28.0))
    min_drift = float(getattr(cfg, "V36_PULLBACK_MIN_DRIFT_ALT" if is_alt else "V36_PULLBACK_MIN_DRIFT_ETH", 0.018))
    max_drift = float(getattr(cfg, "V36_PULLBACK_MAX_DRIFT", 0.105))
    if adx_h < min_adx:
        return None, None, 1.0, {"reason": "v36_adx_too_low", "adx_h": adx_h}
    if abs(float(drift)) < min_drift:
        return None, None, 1.0, {"reason": "v36_drift_too_low", "drift": drift}
    if abs(float(drift)) > max_drift:
        return None, None, 1.0, {"reason": "v36_drift_too_high", "drift": drift}

    try:
        closes = pd.concat([recent["close"].astype(float), pd.Series([float(close)])], ignore_index=True)
        ema_fast = float(closes.ewm(span=int(getattr(cfg, "V36_PULLBACK_FAST_EMA", 20)), adjust=False).mean().iloc[-1])
        ema_slow = float(closes.ewm(span=int(getattr(cfg, "V36_PULLBACK_SLOW_EMA", 50)), adjust=False).mean().iloc[-1])
    except Exception:
        return None, None, 1.0, {"reason": "v36_ema_failed"}

    open_ = _f(last, "open", close)
    high = _f(last, "high", close)
    low = _f(last, "low", close)
    candle_range = max(high - low, 1e-9)
    body = abs(close - open_)
    body_atr = body / max(atr_ltf, 1e-9)
    range_atr = candle_range / max(atr_ltf, 1e-9)
    body_ratio = body / candle_range

    min_body = float(getattr(cfg, "V36_PULLBACK_MIN_BODY_ATR_ALT" if is_alt else "V36_PULLBACK_MIN_BODY_ATR_ETH", 0.18))
    max_body = float(getattr(cfg, "V36_PULLBACK_MAX_BODY_ATR_ALT" if is_alt else "V36_PULLBACK_MAX_BODY_ATR_ETH", 1.35))
    max_range = float(getattr(cfg, "V36_PULLBACK_MAX_RANGE_ATR_ALT" if is_alt else "V36_PULLBACK_MAX_RANGE_ATR_ETH", 2.25))
    min_body_ratio = float(getattr(cfg, "V36_PULLBACK_MIN_BODY_RATIO", 0.34))
    if body_atr < min_body:
        return None, None, 1.0, {"reason": "v36_body_too_small", "body_atr": body_atr}
    if body_atr > max_body:
        return None, None, 1.0, {"reason": "v36_body_too_large", "body_atr": body_atr}
    if range_atr > max_range:
        return None, None, 1.0, {"reason": "v36_range_too_large", "range_atr": range_atr}
    if body_ratio < min_body_ratio:
        return None, None, 1.0, {"reason": "v36_body_ratio_too_low", "body_ratio": body_ratio}

    touch_atr = float(getattr(cfg, "V36_PULLBACK_TOUCH_EMA_ATR", 0.32)) * max(atr_ltf, 1e-9)
    reclaim_atr = float(getattr(cfg, "V36_PULLBACK_RECLAIM_EMA_ATR", 0.04)) * max(atr_ltf, 1e-9)
    max_extension = float(getattr(cfg, "V36_PULLBACK_MAX_EXTENSION_ATR", 0.85)) * max(atr_ltf, 1e-9)

    trade_type = str(getattr(cfg, "V36_PULLBACK_TRADE_TYPE_ALT" if is_alt else "V36_PULLBACK_TRADE_TYPE_ETH", "trend_pullback"))
    meta = {
        "engine": "v36_trend_pullback",
        "symbol": symbol_u,
        "market_state": market_state,
        "regime": regime,
        "adx_h": adx_h,
        "drift": drift,
        "ema_fast": ema_fast,
        "ema_slow": ema_slow,
        "body_atr": body_atr,
        "range_atr": range_atr,
        "body_ratio": body_ratio,
    }

    # Long pullback: HTF bull / positive drift, price pulled into a mean zone and starts turning back up.
    # v38 relaxes v37: EMA touch is a zone (EMA20/EMA50), confirmation can be shallow,
    # and reclaim may be slightly below EMA20 so we do not miss the early turn.
    v38_relaxed = bool(getattr(cfg, "V38_RELAXED_PULLBACK_ENABLED", False)) and symbol_u in set(getattr(cfg, "V38_RELAXED_PULLBACK_SYMBOLS", []) or [])
    ema_zone_low = min(ema_fast, ema_slow) if bool(getattr(cfg, "V38_PULLBACK_ZONE_USES_EMA50", True)) else ema_fast
    ema_zone_high = max(ema_fast, ema_slow) if bool(getattr(cfg, "V38_PULLBACK_ZONE_USES_EMA50", True)) else ema_fast

    long_touch = low <= (ema_zone_high + touch_atr) and low >= (ema_zone_low - (touch_atr * (1.25 if v38_relaxed else 1.0)))
    long_reclaim = close >= (ema_fast + reclaim_atr)
    long_turn = (close > open_) or (v38_relaxed and close > float(recent["close"].astype(float).iloc[-1]))
    long_trend_align = ema_fast >= ema_slow or (v38_relaxed and close >= ema_slow)

    long_ok = bool(getattr(cfg, "V36_PULLBACK_ALLOW_LONG", True))
    long_ok = long_ok and float(drift) > 0 and str(regime).lower() != "bear" and long_trend_align
    long_ok = long_ok and long_touch and long_reclaim
    long_ok = long_ok and long_turn and (close - ema_zone_low) <= max_extension
    long_ok = long_ok and close < (range_high + float(getattr(cfg, "V36_PULLBACK_REJECT_LATE_BREAKOUT_ATR", 0.10)) * max(atr_ltf, 1e-9))
    if long_ok:
        risk = float(getattr(cfg, "V36_PULLBACK_LONG_RISK_ALT" if is_alt else "V36_PULLBACK_LONG_RISK_ETH", 0.014))
        return "buy", trade_type, risk, {**meta, "reason": "v38_relaxed_pullback_long" if v38_relaxed else "v36_pullback_long", "side": "long", "v38_relaxed": v38_relaxed}

    short_ok = bool(getattr(cfg, "V36_PULLBACK_ALLOW_SHORT", True))
    short_min_adx = float(getattr(cfg, "V36_PULLBACK_SHORT_MIN_ADX_ALT" if is_alt else "V36_PULLBACK_SHORT_MIN_ADX_ETH", min_adx + 3.0))
    short_min_drift = float(getattr(cfg, "V36_PULLBACK_SHORT_MIN_DRIFT_ALT" if is_alt else "V36_PULLBACK_SHORT_MIN_DRIFT_ETH", min_drift * 1.25))
    short_touch = high >= (ema_zone_low - touch_atr) and high <= (ema_zone_high + (touch_atr * (1.25 if v38_relaxed else 1.0)))
    short_reclaim = close <= (ema_fast - reclaim_atr)
    short_turn = (close < open_) or (v38_relaxed and close < float(recent["close"].astype(float).iloc[-1]))
    short_trend_align = ema_fast <= ema_slow or (v38_relaxed and close <= ema_slow)
    short_ok = short_ok and adx_h >= short_min_adx and abs(float(drift)) >= short_min_drift
    short_ok = short_ok and float(drift) < 0 and str(regime).lower() != "bull" and short_trend_align
    short_ok = short_ok and short_touch and short_reclaim
    short_ok = short_ok and short_turn and (ema_zone_high - close) <= max_extension
    short_ok = short_ok and close > (range_low - float(getattr(cfg, "V36_PULLBACK_REJECT_LATE_BREAKOUT_ATR", 0.10)) * max(atr_ltf, 1e-9))
    if short_ok:
        risk = float(getattr(cfg, "V36_PULLBACK_SHORT_RISK_ALT" if is_alt else "V36_PULLBACK_SHORT_RISK_ETH", 0.009))
        return "sell", trade_type, risk, {**meta, "reason": "v38_relaxed_pullback_short" if v38_relaxed else "v36_pullback_short", "side": "short", "v38_relaxed": v38_relaxed}

    return None, None, 1.0, {**meta, "reason": "v36_no_pullback_setup"}

def _eth_volatility_breakout(*, cfg, symbol: str, market_state: str, regime: str, recent: pd.DataFrame, last: pd.Series, close: float, atr_ltf: float, adx_h: float, drift: float, range_high: float, range_low: float) -> tuple[Optional[str], Optional[str], float, dict]:
    """Strict ETH volatility breakout trigger.

    v23 proved that using breakout as a broad fallback creates too many noise trades.
    v24 keeps the same live/backtest route, but makes breakout a rare event:
    consolidation -> previous candle inside box -> current candle closes decisively outside.
    """
    v24_enabled = bool(getattr(cfg, "V24_ETH_CLEAN_BREAKOUT_ENABLED", False))
    v25_enabled = bool(getattr(cfg, "V25_ETH_PRE_BREAKOUT_ENABLED", False))
    v26_enabled = bool(getattr(cfg, "V26_ETH_LIQUIDITY_BREAKOUT_ENABLED", False))
    if not bool(getattr(cfg, "V23_ETH_VOL_BREAKOUT_ENABLED", False)) and not v24_enabled and not v25_enabled and not v26_enabled:
        return None, None, 1.0, {"reason": "eth_vol_breakout_disabled"}

    def gv(name: str, default):
        if v26_enabled:
            return getattr(cfg, "V26_" + name, getattr(cfg, "V25_" + name, getattr(cfg, "V24_" + name, getattr(cfg, "V23_" + name, default))))
        if v25_enabled:
            return getattr(cfg, "V25_" + name, getattr(cfg, "V24_" + name, getattr(cfg, "V23_" + name, default)))
        if v24_enabled:
            return getattr(cfg, "V24_" + name, getattr(cfg, "V23_" + name, default))
        return getattr(cfg, "V23_" + name, default)

    allowed_states = set(gv("ETH_VOL_BREAKOUT_ALLOWED_MARKET_STATES", ["range", "transition", "flat"]) or ["range", "transition", "flat"])
    if market_state not in allowed_states:
        return None, None, 1.0, {"reason": "eth_vol_breakout_state_not_allowed", "market_state": market_state}
    min_recent = int(gv("ETH_VOL_BREAKOUT_MIN_RECENT_BARS", 24))
    if len(recent) < min_recent:
        return None, None, 1.0, {"reason": "eth_vol_breakout_not_enough_bars"}
    if atr_ltf <= 0 or close <= 0:
        return None, None, 1.0, {"reason": "eth_vol_breakout_bad_inputs"}

    # v25/v26 pre-breakout: require a real compression box BEFORE the current breakout candle.
    pre_box_high = float(range_high)
    pre_box_low = float(range_low)
    pre_box_width_pct = max(pre_box_high - pre_box_low, 1e-9) / max(close, 1e-9)
    compression_ratio = None
    if v25_enabled or v26_enabled:
        squeeze_lookback = max(8, int(gv("ETH_VOL_BREAKOUT_SQUEEZE_LOOKBACK", 18)))
        pre_window = recent.tail(squeeze_lookback).copy()
        if len(pre_window) < squeeze_lookback or "high" not in pre_window.columns or "low" not in pre_window.columns:
            return None, None, 1.0, {"reason": "eth_pre_breakout_not_enough_squeeze_bars"}
        pre_box_high = float(pre_window["high"].astype(float).max())
        pre_box_low = float(pre_window["low"].astype(float).min())
        pre_box_width_pct = max(pre_box_high - pre_box_low, 1e-9) / max(close, 1e-9)
        max_squeeze_width = float(gv("ETH_VOL_BREAKOUT_MAX_SQUEEZE_WIDTH_PCT", 0.030))
        min_squeeze_width = float(gv("ETH_VOL_BREAKOUT_MIN_SQUEEZE_WIDTH_PCT", 0.0035))
        if pre_box_width_pct > max_squeeze_width:
            return None, None, 1.0, {"reason": "eth_pre_breakout_box_not_tight", "range_width_pct": pre_box_width_pct}
        if pre_box_width_pct < min_squeeze_width:
            return None, None, 1.0, {"reason": "eth_pre_breakout_box_too_tight", "range_width_pct": pre_box_width_pct}
        compression_lookback = max(6, int(gv("ETH_VOL_BREAKOUT_COMPRESSION_LOOKBACK", 12)))
        if len(recent) >= squeeze_lookback + compression_lookback:
            recent_ranges = _safe_median_range(recent.tail(compression_lookback))
            prev_ranges = _safe_median_range(recent.iloc[-(squeeze_lookback + compression_lookback):-squeeze_lookback])
            if prev_ranges > 0 and recent_ranges > 0:
                compression_ratio = recent_ranges / max(prev_ranges, 1e-9)
                max_compression_ratio = float(gv("ETH_VOL_BREAKOUT_MAX_COMPRESSION_RATIO", 0.82))
                if compression_ratio > max_compression_ratio:
                    return None, None, 1.0, {"reason": "eth_pre_breakout_not_compressed", "compression_ratio": compression_ratio}

    min_adx = float(gv("ETH_VOL_BREAKOUT_MIN_ADX", 14.0))
    max_adx = float(gv("ETH_VOL_BREAKOUT_MAX_ADX", 42.0))
    if adx_h < min_adx:
        return None, None, 1.0, {"reason": "eth_vol_breakout_adx_too_low", "adx_h": adx_h}
    if adx_h > max_adx:
        return None, None, 1.0, {"reason": "eth_vol_breakout_adx_too_high", "adx_h": adx_h}

    abs_drift = abs(float(drift))
    max_drift = float(gv("ETH_VOL_BREAKOUT_MAX_DRIFT_PCT", 0.055))
    if abs_drift > max_drift:
        return None, None, 1.0, {"reason": "eth_vol_breakout_drift_too_high", "drift": drift}

    open_ = _f(last, "open", close)
    high = _f(last, "high", close)
    low = _f(last, "low", close)
    body = abs(close - open_)
    candle_range = max(high - low, 1e-9)
    body_atr = body / max(atr_ltf, 1e-9)
    range_atr = candle_range / max(atr_ltf, 1e-9)
    close_pos = (close - low) / candle_range

    min_body = float(gv("ETH_VOL_BREAKOUT_MIN_BODY_ATR", 0.24))
    min_range = float(gv("ETH_VOL_BREAKOUT_MIN_RANGE_ATR", 0.42))
    if body_atr < min_body:
        return None, None, 1.0, {"reason": "eth_vol_breakout_body_too_small", "body_atr": body_atr}
    if range_atr < min_range:
        return None, None, 1.0, {"reason": "eth_vol_breakout_range_too_small", "range_atr": range_atr}

    if v25_enabled or v26_enabled:
        range_high, range_low = pre_box_high, pre_box_low
    width = max(range_high - range_low, 1e-9)
    width_pct = width / max(close, 1e-9)
    min_width = float(gv("ETH_VOL_BREAKOUT_MIN_BOX_WIDTH_PCT", 0.0045))
    max_width = float(gv("ETH_VOL_BREAKOUT_MAX_BOX_WIDTH_PCT", 0.085))
    if width_pct < min_width:
        return None, None, 1.0, {"reason": "eth_vol_breakout_box_too_small", "range_width_pct": width_pct}
    if width_pct > max_width:
        return None, None, 1.0, {"reason": "eth_vol_breakout_box_too_large", "range_width_pct": width_pct}

    if bool(gv("ETH_VOL_BREAKOUT_REQUIRE_PREV_INSIDE_BOX", False)):
        prev = recent.iloc[-1]
        prev_close = _f(prev, "close", close)
        box_low_for_prev = pre_box_low if (v25_enabled or v26_enabled) else range_low
        box_high_for_prev = pre_box_high if (v25_enabled or v26_enabled) else range_high
        if not (box_low_for_prev <= prev_close <= box_high_for_prev):
            return None, None, 1.0, {"reason": "eth_vol_breakout_prev_not_inside_box", "prev_close": prev_close, "range_high": box_high_for_prev, "range_low": box_low_for_prev}

    if bool(gv("ETH_VOL_BREAKOUT_REQUIRE_VOLUME_SPIKE", False)):
        vol_col = None
        for c in ("volume", "Volume", "quote_volume", "QuoteVolume"):
            if c in recent.columns or c in last.index:
                vol_col = c
                break
        if vol_col is None:
            return None, None, 1.0, {"reason": "eth_vol_breakout_no_volume_column"}
        lookback = max(5, int(gv("ETH_VOL_BREAKOUT_VOLUME_LOOKBACK", 24)))
        vals = recent[vol_col].tail(lookback) if vol_col in recent.columns else pd.Series(dtype=float)
        try:
            med_vol = float(vals.median()) if len(vals) else 0.0
            last_vol = _f(last, vol_col, 0.0)
        except Exception:
            med_vol, last_vol = 0.0, 0.0
        min_ratio = float(gv("ETH_VOL_BREAKOUT_MIN_VOLUME_RATIO", 1.15))
        if med_vol <= 0 or last_vol / max(med_vol, 1e-9) < min_ratio:
            return None, None, 1.0, {"reason": "eth_vol_breakout_volume_too_low", "last_volume": last_vol, "median_volume": med_vol}

    break_buf = float(gv("ETH_VOL_BREAKOUT_BUFFER_ATR", 0.035)) * max(atr_ltf, 1e-9)
    trade_type = str(gv("ETH_VOL_BREAKOUT_TRADE_TYPE", "eth_vol_breakout"))
    align = bool(gv("ETH_VOL_BREAKOUT_REQUIRE_REGIME_ALIGNMENT", False))
    long_ok = bool(gv("ETH_VOL_BREAKOUT_ALLOW_LONG", True)) and close > open_ and close > (range_high + break_buf)
    short_ok = bool(gv("ETH_VOL_BREAKOUT_ALLOW_SHORT", True)) and close < open_ and close < (range_low - break_buf)

    if v25_enabled or v26_enabled:
        max_extension_atr = float(gv("ETH_VOL_BREAKOUT_MAX_EXTENSION_ATR", 0.62))
        if long_ok and (close - range_high) / max(atr_ltf, 1e-9) > max_extension_atr:
            long_ok = False
        if short_ok and (range_low - close) / max(atr_ltf, 1e-9) > max_extension_atr:
            short_ok = False

    # v26 liquidity breakout: do NOT buy the first breakout.
    # Require a prior false break/sweep on the opposite side of the compression box,
    # reclaim back inside, then current candle breaks the other side.
    liquidity_meta = {}
    if v26_enabled:
        sweep_lookback = max(3, int(getattr(cfg, "V26_ETH_LIQUIDITY_SWEEP_LOOKBACK", 10)))
        min_ago = max(1, int(getattr(cfg, "V26_ETH_LIQUIDITY_SWEEP_MIN_BARS_AGO", 1)))
        max_ago = max(min_ago, int(getattr(cfg, "V26_ETH_LIQUIDITY_SWEEP_MAX_BARS_AGO", 8)))
        sweep_buf = float(getattr(cfg, "V26_ETH_LIQUIDITY_SWEEP_BUFFER_ATR", 0.035)) * max(atr_ltf, 1e-9)
        require_close_back = bool(getattr(cfg, "V26_ETH_LIQUIDITY_REQUIRE_SWEEP_CLOSE_BACK_INSIDE", True))
        max_post_retest = float(getattr(cfg, "V26_ETH_LIQUIDITY_MAX_POST_SWEEP_RETEST_ATR", 0.18)) * max(atr_ltf, 1e-9)
        window = recent.tail(sweep_lookback).copy()

        def _find_sweep(side: str):
            if len(window) < min_ago + 1:
                return None
            rows = list(window.iterrows())
            for ago in range(min_ago, min(max_ago, len(rows)) + 1):
                _, row = rows[-ago]
                h = _f(row, "high", close)
                l = _f(row, "low", close)
                c = _f(row, "close", close)
                if side == "long":
                    swept = l < (range_low - sweep_buf)
                    reclaimed = c >= range_low if require_close_back else True
                    if swept and reclaimed:
                        after = window.iloc[-ago + 1:] if ago > 1 else window.iloc[0:0]
                        if len(after) and float(after["low"].astype(float).min()) < (range_low - max_post_retest):
                            continue
                        return {"sweep_side": "down", "sweep_bars_ago": ago, "sweep_low": l, "sweep_close": c}
                else:
                    swept = h > (range_high + sweep_buf)
                    reclaimed = c <= range_high if require_close_back else True
                    if swept and reclaimed:
                        after = window.iloc[-ago + 1:] if ago > 1 else window.iloc[0:0]
                        if len(after) and float(after["high"].astype(float).max()) > (range_high + max_post_retest):
                            continue
                        return {"sweep_side": "up", "sweep_bars_ago": ago, "sweep_high": h, "sweep_close": c}
            return None

        if long_ok:
            sweep = _find_sweep("long")
            if sweep is None:
                long_ok = False
            else:
                liquidity_meta.update(sweep)
        if short_ok:
            sweep = _find_sweep("short")
            if sweep is None:
                short_ok = False
            else:
                liquidity_meta.update(sweep)
        if not long_ok and not short_ok:
            return None, None, 1.0, {"reason": "no_eth_liquidity_breakout_sweep", "range_width_pct": width_pct, "adx_h": adx_h, "drift": drift, "compression_ratio": compression_ratio}

    if long_ok and close_pos < float(gv("ETH_VOL_BREAKOUT_LONG_MIN_CLOSE_POS", 0.62)):
        long_ok = False
    if short_ok and close_pos > float(gv("ETH_VOL_BREAKOUT_SHORT_MAX_CLOSE_POS", 0.38)):
        short_ok = False
    if align:
        reg = str(regime).lower()
        if long_ok and reg == "bear":
            long_ok = False
        if short_ok and reg == "bull":
            short_ok = False
    if short_ok and adx_h < float(gv("ETH_VOL_BREAKOUT_SHORT_MIN_ADX", 18.0)):
        short_ok = False
    if short_ok and abs_drift < float(gv("ETH_VOL_BREAKOUT_SHORT_MIN_DRIFT_PCT", 0.0060)):
        short_ok = False
    if short_ok and body_atr < float(gv("ETH_VOL_BREAKOUT_SHORT_MIN_BODY_ATR", min_body)):
        short_ok = False

    if v26_enabled:
        engine_name = "eth_liquidity_breakout_v26"
    elif v25_enabled:
        engine_name = "eth_pre_breakout_v25"
    else:
        engine_name = "eth_vol_breakout_v24" if v24_enabled else "eth_vol_breakout_v23"
    base_meta = {"engine": engine_name, "market_state": market_state, "regime": regime, "body_atr": body_atr, "range_atr": range_atr, "range_width_pct": width_pct, "adx_h": adx_h, "drift": drift, "compression_ratio": compression_ratio}
    base_meta.update(liquidity_meta if 'liquidity_meta' in locals() else {})
    if long_ok:
        risk = float(gv("ETH_VOL_BREAKOUT_LONG_RISK_MULT", 0.020))
        reason = "eth_liquidity_breakout_long" if v26_enabled else ("eth_pre_breakout_long" if v25_enabled else "eth_vol_breakout_long")
        m = dict(base_meta); m.update({"reason": reason, "side": "long"})
        return "buy", trade_type, risk, m
    if short_ok:
        risk = float(gv("ETH_VOL_BREAKOUT_SHORT_RISK_MULT", 0.014))
        reason = "eth_liquidity_breakout_short" if v26_enabled else ("eth_pre_breakout_short" if v25_enabled else "eth_vol_breakout_short")
        m = dict(base_meta); m.update({"reason": reason, "side": "short"})
        return "sell", trade_type, risk, m
    no_reason = "no_eth_liquidity_breakout_setup" if v26_enabled else ("no_eth_pre_breakout_setup" if v25_enabled else "no_eth_vol_breakout_setup")
    return None, None, 1.0, {"reason": no_reason, **base_meta}


def _micro_range_engine(*, cfg, symbol: str, market_state: str, regime: str, recent: pd.DataFrame, last: pd.Series, close: float, atr_ltf: float, adx_h: float, drift: float, range_high: float, range_low: float) -> tuple[Optional[str], Optional[str], float, dict]:
    """v28 controlled micro range engine.

    This is deliberately NOT the old legacy range/reaction layer. It is a tiny-risk,
    fast-exit activity engine for quiet non-trend regimes only. The goal is to create
    a steady flow of small trades without interfering with the higher-edge trend engines.
    """
    if not bool(getattr(cfg, "V28_MICRO_ENGINE_ENABLED", False)):
        return None, None, 1.0, {"reason": "micro_engine_disabled"}

    symbol_u = str(symbol or "").upper()
    allowed_symbols = set(getattr(cfg, "V28_MICRO_SYMBOLS", []) or [])
    if symbol_u not in allowed_symbols:
        return None, None, 1.0, {"reason": "micro_symbol_not_allowed", "symbol": symbol_u}

    allowed_states = set(getattr(cfg, "V28_MICRO_ALLOWED_MARKET_STATES", ["range", "transition", "flat"]) or ["range", "transition", "flat"])
    if str(market_state) not in allowed_states:
        return None, None, 1.0, {"reason": "micro_state_not_allowed", "market_state": market_state}

    if atr_ltf <= 0 or close <= 0 or len(recent) < int(getattr(cfg, "V28_MICRO_MIN_RECENT_BARS", 18)):
        return None, None, 1.0, {"reason": "micro_bad_inputs"}

    max_adx = float(getattr(cfg, "V28_MICRO_MAX_ADX", 24.0))
    max_drift = float(getattr(cfg, "V28_MICRO_MAX_DRIFT_PCT", 0.018))
    if adx_h > max_adx:
        return None, None, 1.0, {"reason": "micro_adx_too_high", "adx_h": adx_h}
    if abs(float(drift)) > max_drift:
        return None, None, 1.0, {"reason": "micro_drift_too_high", "drift": drift}

    box_bars = int(getattr(cfg, "V28_MICRO_BOX_BARS", 18))
    box = recent.tail(max(6, box_bars))
    try:
        box_high = float(box["high"].astype(float).max())
        box_low = float(box["low"].astype(float).min())
    except Exception:
        return None, None, 1.0, {"reason": "micro_box_invalid"}
    width = max(box_high - box_low, 1e-9)
    width_pct = width / max(close, 1e-9)
    min_width = float(getattr(cfg, "V28_MICRO_MIN_BOX_WIDTH_PCT", 0.0035))
    max_width = float(getattr(cfg, "V28_MICRO_MAX_BOX_WIDTH_PCT", 0.040))
    if width_pct < min_width or width_pct > max_width:
        return None, None, 1.0, {"reason": "micro_box_width_invalid", "box_width_pct": width_pct}

    median_range = _safe_median_range(box)
    if median_range <= 0:
        return None, None, 1.0, {"reason": "micro_median_range_invalid"}
    current_range = max(_f(last, "high", close) - _f(last, "low", close), 0.0)
    max_current_range_atr = float(getattr(cfg, "V28_MICRO_MAX_CURRENT_RANGE_ATR", 1.25))
    if current_range / max(atr_ltf, 1e-9) > max_current_range_atr:
        return None, None, 1.0, {"reason": "micro_current_range_too_large"}

    compression_max = float(getattr(cfg, "V28_MICRO_COMPRESSION_MAX_MEDIAN_RANGE_ATR", 0.78))
    if median_range / max(atr_ltf, 1e-9) > compression_max:
        return None, None, 1.0, {"reason": "micro_not_compressed", "median_range_atr": median_range / max(atr_ltf, 1e-9)}

    open_ = _f(last, "open", close)
    high = _f(last, "high", close)
    low = _f(last, "low", close)
    body_atr = abs(close - open_) / max(atr_ltf, 1e-9)
    max_body_atr = float(getattr(cfg, "V28_MICRO_MAX_BODY_ATR", 0.85))
    if body_atr > max_body_atr:
        return None, None, 1.0, {"reason": "micro_body_too_large", "body_atr": body_atr}

    edge_zone = float(getattr(cfg, "V28_MICRO_EDGE_ZONE_PCT", 0.18))
    close_pos = (close - box_low) / width
    reclaim_atr = float(getattr(cfg, "V28_MICRO_RECLAIM_ATR", 0.02))
    require_reaction = bool(getattr(cfg, "V28_MICRO_REQUIRE_REACTION_CANDLE", True))
    trade_type = str(getattr(cfg, "V28_MICRO_TRADE_TYPE", "micro_range"))

    # Mean-reversion only near edges. We avoid the middle of the range and avoid strong candles.
    long_ok = close_pos <= edge_zone and low <= (box_low + edge_zone * width)
    if long_ok and close < (box_low + reclaim_atr * atr_ltf):
        long_ok = False
    if long_ok and require_reaction and close <= open_:
        long_ok = False
    if long_ok and str(regime).lower() == "bear" and bool(getattr(cfg, "V28_MICRO_REJECT_COUNTER_REGIME_LONG", False)):
        long_ok = False

    short_ok = close_pos >= (1.0 - edge_zone) and high >= (box_high - edge_zone * width)
    if short_ok and close > (box_high - reclaim_atr * atr_ltf):
        short_ok = False
    if short_ok and require_reaction and close >= open_:
        short_ok = False
    if short_ok and str(regime).lower() == "bull" and bool(getattr(cfg, "V28_MICRO_REJECT_COUNTER_REGIME_SHORT", False)):
        short_ok = False

    base_meta = {
        "engine": "micro_range_v28",
        "market_state": market_state,
        "regime": regime,
        "box_width_pct": width_pct,
        "close_pos": close_pos,
        "body_atr": body_atr,
        "adx_h": adx_h,
        "drift": drift,
    }
    if long_ok:
        risk = float(getattr(cfg, "V28_MICRO_LONG_RISK_MULT", 0.008))
        return "buy", trade_type, risk, {**base_meta, "reason": "micro_range_long", "side": "long"}
    if short_ok:
        risk = float(getattr(cfg, "V28_MICRO_SHORT_RISK_MULT", 0.006))
        return "sell", trade_type, risk, {**base_meta, "reason": "micro_range_short", "side": "short"}

    return None, None, 1.0, {**base_meta, "reason": "no_micro_range_setup"}

def run_eth_liquidity_engine_v1(*, cfg, symbol: str, market_state: str, regime: str, df: pd.DataFrame, recent: pd.DataFrame, last: pd.Series, close: float, atr_ltf: float, adx_h: float, drift: float, range_high: float, range_low: float, market_meta: dict | None = None) -> tuple[Optional[str], Optional[str], float, dict]:
    meta = {"reason": "eth_engine_disabled"}
    symbol_u = str(symbol or "").upper()
    if bool(getattr(cfg, "V32_SMART_ROTATION_ENABLED", False)) and symbol_u in set(getattr(cfg, "V32_DISABLED_SYMBOLS", []) or []):
        return None, None, 1.0, {"reason": "v32_symbol_disabled", "symbol": symbol_u}
    allowed_symbols = set(getattr(cfg, "V14_ETH_ENGINE_SYMBOLS", ["ETHUSDT"]) or ["ETHUSDT"])
    if not bool(getattr(cfg, "V14_ETH_LIQUIDITY_ENGINE_ENABLED", False)) or symbol not in allowed_symbols:
        return None, None, 1.0, meta
    if atr_ltf <= 0 or close <= 0 or len(recent) < 6:
        return None, None, 1.0, {"reason": "bad_inputs"}

    # v37: pullback-only route for ETH/ALT symbols.
    # Do not fall back to momentum, breakout, micro, or legacy range.
    if bool(getattr(cfg, "V37_PULLBACK_ONLY_ENABLED", False)):
        if symbol_u in set(getattr(cfg, "V37_PULLBACK_ONLY_SYMBOLS", []) or []):
            pb_signal, pb_trade_type, pb_risk, pb_meta = _v36_trend_pullback(
                cfg=cfg, symbol=symbol, market_state=market_state, regime=regime,
                recent=recent, last=last, close=close, atr_ltf=atr_ltf,
                adx_h=adx_h, drift=drift, range_high=range_high, range_low=range_low,
            )
            if pb_signal is not None:
                pb_meta["v37_pullback_only"] = True
                return pb_signal, pb_trade_type, pb_risk, pb_meta
            pb_meta["v37_pullback_only"] = True
            return None, None, 1.0, pb_meta

    if bool(getattr(cfg, "V17_ETH_HYBRID_ENABLED", False)) and market_state in set(getattr(cfg, "V17_ETH_TREND_ALLOWED_MARKET_STATES", ["trend"]) or ["trend"]):
        trend_signal, trend_trade_type, trend_risk, trend_meta = _eth_trend_momentum(cfg=cfg, symbol=symbol, market_state=market_state, regime=regime, recent=recent, last=last, close=close, atr_ltf=atr_ltf, adx_h=adx_h, drift=drift, range_high=range_high, range_low=range_low)
        if trend_signal is not None:
            return trend_signal, trend_trade_type, trend_risk, trend_meta
        if bool(getattr(cfg, "V26_ETH_LIQUIDITY_BREAKOUT_ENABLED", getattr(cfg, "V25_ETH_PRE_BREAKOUT_ENABLED", getattr(cfg, "V24_ETH_CLEAN_BREAKOUT_ENABLED", getattr(cfg, "V23_ETH_VOL_BREAKOUT_ENABLED", False))))) and bool(getattr(cfg, "V26_ETH_VOL_BREAKOUT_ALLOW_AFTER_TREND_MISS", getattr(cfg, "V25_ETH_VOL_BREAKOUT_ALLOW_AFTER_TREND_MISS", getattr(cfg, "V24_ETH_VOL_BREAKOUT_ALLOW_AFTER_TREND_MISS", getattr(cfg, "V23_ETH_VOL_BREAKOUT_ALLOW_AFTER_TREND_MISS", True))))):
            bo_signal, bo_trade_type, bo_risk, bo_meta = _eth_volatility_breakout(cfg=cfg, symbol=symbol, market_state=market_state, regime=regime, recent=recent, last=last, close=close, atr_ltf=atr_ltf, adx_h=adx_h, drift=drift, range_high=range_high, range_low=range_low)
            if bo_signal is not None:
                bo_meta["trend_miss_reason"] = trend_meta.get("reason")
                return bo_signal, bo_trade_type, bo_risk, bo_meta
        if bool(getattr(cfg, "V36_PULLBACK_ENGINE_ENABLED", False)):
            pb_signal, pb_trade_type, pb_risk, pb_meta = _v36_trend_pullback(cfg=cfg, symbol=symbol, market_state=market_state, regime=regime, recent=recent, last=last, close=close, atr_ltf=atr_ltf, adx_h=adx_h, drift=drift, range_high=range_high, range_low=range_low)
            if pb_signal is not None:
                pb_meta["trend_miss_reason"] = trend_meta.get("reason")
                return pb_signal, pb_trade_type, pb_risk, pb_meta
        return None, None, 1.0, trend_meta

    if bool(getattr(cfg, "V36_PULLBACK_ENGINE_ENABLED", False)):
        pb_signal, pb_trade_type, pb_risk, pb_meta = _v36_trend_pullback(cfg=cfg, symbol=symbol, market_state=market_state, regime=regime, recent=recent, last=last, close=close, atr_ltf=atr_ltf, adx_h=adx_h, drift=drift, range_high=range_high, range_low=range_low)
        if pb_signal is not None:
            return pb_signal, pb_trade_type, pb_risk, pb_meta

    if bool(getattr(cfg, "V28_MICRO_ENGINE_ENABLED", False)) and not bool(getattr(cfg, "V32_FORCE_DISABLE_MICRO_RANGE", False)):
        micro_signal, micro_trade_type, micro_risk, micro_meta = _micro_range_engine(cfg=cfg, symbol=symbol, market_state=market_state, regime=regime, recent=recent, last=last, close=close, atr_ltf=atr_ltf, adx_h=adx_h, drift=drift, range_high=range_high, range_low=range_low)
        if micro_signal is not None:
            return micro_signal, micro_trade_type, micro_risk, micro_meta

    if bool(getattr(cfg, "V26_ETH_LIQUIDITY_BREAKOUT_ENABLED", getattr(cfg, "V25_ETH_PRE_BREAKOUT_ENABLED", getattr(cfg, "V24_ETH_CLEAN_BREAKOUT_ENABLED", getattr(cfg, "V23_ETH_VOL_BREAKOUT_ENABLED", False))))):
        bo_signal, bo_trade_type, bo_risk, bo_meta = _eth_volatility_breakout(cfg=cfg, symbol=symbol, market_state=market_state, regime=regime, recent=recent, last=last, close=close, atr_ltf=atr_ltf, adx_h=adx_h, drift=drift, range_high=range_high, range_low=range_low)
        if bo_signal is not None:
            return bo_signal, bo_trade_type, bo_risk, bo_meta

    if bool(getattr(cfg, "V18_ETH_TREND_ONLY", False)) or bool(getattr(cfg, "V18_ETH_DISABLE_LIQUIDITY_LAYER", False)):
        return None, None, 1.0, {"reason": "eth_liquidity_disabled_v18_trend_only", "market_state": market_state, "adx_h": adx_h, "drift": drift}

    if market_state not in set(getattr(cfg, "V14_ETH_ALLOWED_MARKET_STATES", ["range", "transition"]) or ["range", "transition"]):
        return None, None, 1.0, {"reason": "market_state_not_allowed", "market_state": market_state}
    if adx_h > float(getattr(cfg, "V14_ETH_MAX_ADX", 35.0)):
        return None, None, 1.0, {"reason": "adx_too_high", "adx_h": adx_h}
    if abs(drift) > float(getattr(cfg, "V14_ETH_MAX_DRIFT_PCT", 0.0250)):
        return None, None, 1.0, {"reason": "drift_too_high", "drift": drift}

    width = max(range_high - range_low, 1e-9)
    width_pct = width / max(close, 1e-9)
    if width_pct < float(getattr(cfg, "V14_ETH_MIN_RANGE_WIDTH_PCT", 0.008)) or width_pct > float(getattr(cfg, "V14_ETH_MAX_RANGE_WIDTH_PCT", 0.060)):
        return None, None, 1.0, {"reason": "range_width_invalid", "range_width_pct": width_pct}

    edge_zone = float(getattr(cfg, "V14_ETH_EDGE_ZONE_PCT", 0.28))
    reclaim_atr = float(getattr(cfg, "V14_ETH_RECLAIM_ATR", 0.06))
    min_body_atr = float(getattr(cfg, "V14_ETH_MIN_BODY_ATR", 0.06))
    require_prev_opp = bool(getattr(cfg, "V14_ETH_REQUIRE_PREV_OPPOSITE_CANDLE", True))
    hl_buffer_atr = float(getattr(cfg, "V14_ETH_HL_BUFFER_ATR", 0.02))

    open_ = _f(last, "open", close)
    high = _f(last, "high", close)
    low = _f(last, "low", close)
    rsi = _f(last, "RSI", 50.0)
    prev = recent.iloc[-1]
    prev_open = _f(prev, "open", close)
    prev_close = _f(prev, "close", close)
    prev_high = _f(prev, "high", close)
    prev_low = _f(prev, "low", close)

    body_atr = abs(close - open_) / max(atr_ltf, 1e-9)
    close_pos = (close - range_low) / width
    long_edge = close_pos <= edge_zone
    short_edge = close_pos >= 1.0 - edge_zone
    trade_type = str(getattr(cfg, "V15_ETH_TRADE_TYPE", "eth_liquidity_momentum"))

    long_ok = long_edge
    long_reason = "candidate_false"
    mom_meta = {"body_atr": body_atr}
    if long_ok and body_atr < min_body_atr:
        long_ok = False; long_reason = "body_too_small"
    if long_ok and close < (range_low + reclaim_atr * atr_ltf):
        long_ok = False; long_reason = "not_reclaimed_inside_range"
    if long_ok and close <= open_:
        long_ok = False; long_reason = "no_bullish_reaction"
    if long_ok and require_prev_opp and prev_close >= prev_open:
        long_ok = False; long_reason = "prev_not_bearish"
    if long_ok and low < (prev_low - hl_buffer_atr * atr_ltf):
        long_ok = False; long_reason = "no_higher_low"
    if long_ok and rsi > float(getattr(cfg, "V14_ETH_LONG_RSI_MAX", 62.0)):
        long_ok = False; long_reason = "rsi_too_high"
    if long_ok and bool(getattr(cfg, "V15_ETH_LIQUIDITY_MOMENTUM_ENABLED", True)):
        long_ok, long_reason, mom_meta = _momentum_ok(cfg=cfg, side="long", close=close, open_=open_, high=high, low=low, prev_high=prev_high, prev_low=prev_low, atr_ltf=atr_ltf)
    if long_ok:
        risk = float(getattr(cfg, "V15_ETH_LONG_RISK_MULT", getattr(cfg, "V14_ETH_RISK_MULT", 0.05)))
        return "buy", trade_type, risk, {"reason": "eth_liquidity_trap_momentum_long", "engine": "eth_liquidity_v15", "side": "long", "market_state": market_state, "range_width_pct": width_pct, "close_pos": close_pos, "body_atr": body_atr, **mom_meta}

    short_ok = short_edge
    short_reason = "candidate_false"
    mom_meta = {"body_atr": body_atr}
    if short_ok and adx_h > float(getattr(cfg, "V15_ETH_SHORT_ADX_MAX", 28.0)):
        short_ok = False; short_reason = "short_adx_too_high"
    if short_ok and abs(drift) > float(getattr(cfg, "V15_ETH_SHORT_DRIFT_MAX", 0.0200)):
        short_ok = False; short_reason = "short_drift_too_high"
    if short_ok and body_atr < min_body_atr:
        short_ok = False; short_reason = "body_too_small"
    if short_ok and close > (range_high - reclaim_atr * atr_ltf):
        short_ok = False; short_reason = "not_reclaimed_inside_range"
    if short_ok and close >= open_:
        short_ok = False; short_reason = "no_bearish_reaction"
    if short_ok and require_prev_opp and prev_close <= prev_open:
        short_ok = False; short_reason = "prev_not_bullish"
    if short_ok and high > (prev_high + hl_buffer_atr * atr_ltf):
        short_ok = False; short_reason = "no_lower_high"
    if short_ok and rsi < float(getattr(cfg, "V14_ETH_SHORT_RSI_MIN", 38.0)):
        short_ok = False; short_reason = "rsi_too_low"
    if short_ok and bool(getattr(cfg, "V15_ETH_LIQUIDITY_MOMENTUM_ENABLED", True)):
        short_ok, short_reason, mom_meta = _momentum_ok(cfg=cfg, side="short", close=close, open_=open_, high=high, low=low, prev_high=prev_high, prev_low=prev_low, atr_ltf=atr_ltf)
    if short_ok:
        risk = float(getattr(cfg, "V15_ETH_SHORT_RISK_MULT", getattr(cfg, "V14_ETH_SHORT_RISK_MULT", 0.05)))
        return "sell", trade_type, risk, {"reason": "eth_liquidity_trap_momentum_short", "engine": "eth_liquidity_v15", "side": "short", "market_state": market_state, "range_width_pct": width_pct, "close_pos": close_pos, "body_atr": body_atr, **mom_meta}

    return None, None, 1.0, {"reason": "no_eth_liquidity_setup", "long_candidate_reason": long_reason, "short_candidate_reason": short_reason, "market_state": market_state, "range_width_pct": width_pct, "close_pos": close_pos, "adx_h": adx_h, "drift": drift}
