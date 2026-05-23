from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd


from .mtf_market_helpers import calc_false_breakout_ratio, calc_recent_wickiness
from .mtf_special_entries_helpers import check_fakeout_reversal_entry, range_signal


def detect_btc_range_regime_v1(*, cfg, recent: pd.DataFrame, close: float, atr_ltf: float, adx_h: float, drift: float) -> tuple[str, dict]:
    """Granular range regime classifier that preserves the legacy market_state contract.

    Returns one of: quiet_range, volatile_range, liquidity_sweep_range, transition_range.
    """
    wickiness = calc_recent_wickiness(recent)
    false_breakout_ratio = calc_false_breakout_ratio(recent, lookback=min(12, max(6, len(recent) // 5)))
    atr_roll = recent["ATR"].astype(float).dropna() if "ATR" in recent.columns else pd.Series(dtype=float)
    compression_ratio = 1.0
    if len(atr_roll) >= 10 and atr_ltf > 0:
        compression_ratio = float(atr_ltf / max(float(atr_roll.tail(10).mean()), 1e-9))
    range_width_pct = 0.0
    if close > 0 and len(recent) > 0:
        range_width_pct = float((recent["high"].astype(float).max() - recent["low"].astype(float).min()) / close)

    quiet_adx_max = float(getattr(cfg, "BTC_RANGE_ENGINE_V1_QUIET_ADX_MAX", 17.5))
    quiet_drift_max = float(getattr(cfg, "BTC_RANGE_ENGINE_V1_QUIET_DRIFT_MAX", 0.0038))
    quiet_wickiness_max = float(getattr(cfg, "BTC_RANGE_ENGINE_V1_QUIET_WICKINESS_MAX", 0.57))
    sweep_false_breakout_min = float(getattr(cfg, "BTC_RANGE_ENGINE_V1_SWEEP_FALSE_BREAKOUT_MIN", 0.28))
    sweep_wickiness_min = float(getattr(cfg, "BTC_RANGE_ENGINE_V1_SWEEP_WICKINESS_MIN", 0.54))
    volatile_adx_max = float(getattr(cfg, "BTC_RANGE_ENGINE_V1_VOLATILE_ADX_MAX", 22.0))
    volatile_width_min = float(getattr(cfg, "BTC_RANGE_ENGINE_V1_VOLATILE_WIDTH_MIN", 0.020))
    volatile_compression_max = float(getattr(cfg, "BTC_RANGE_ENGINE_V1_VOLATILE_COMPRESSION_MAX", 1.20))

    payload = {
        "adx_h": adx_h,
        "drift": drift,
        "wickiness": wickiness,
        "false_breakout_ratio": false_breakout_ratio,
        "compression_ratio": compression_ratio,
        "range_width_pct": range_width_pct,
    }

    if adx_h <= quiet_adx_max and drift <= quiet_drift_max and wickiness <= quiet_wickiness_max and compression_ratio <= 1.08:
        return "quiet_range", payload
    if false_breakout_ratio >= sweep_false_breakout_min and wickiness >= sweep_wickiness_min:
        return "liquidity_sweep_range", payload
    if adx_h <= volatile_adx_max and range_width_pct >= volatile_width_min and compression_ratio <= volatile_compression_max:
        return "volatile_range", payload
    return "transition_range", payload


def check_reclaim_after_flush_entry(*, cfg, symbol: str, recent: pd.DataFrame, candle: pd.Series, atr_ltf: float, range_high: float, range_low: float) -> tuple[Optional[str], dict]:
    if len(recent) < 24 or atr_ltf <= 0:
        return None, {"reason": "not_enough_reclaim_history"}

    def _f(name: str, default: float = float("nan")) -> float:
        try:
            return float(candle.get(name, default))
        except Exception:
            return float(default)

    close = _f("close")
    open_ = _f("open", close)
    high = _f("high", close)
    low = _f("low", close)
    ema20 = _f("EMA20", close)
    rsi = _f("RSI", 50.0)
    volume = _f("volume", 0.0)
    if any(np.isnan(v) for v in [close, open_, high, low, ema20, rsi]) or close <= 0:
        return None, {"reason": "nan_reclaim_inputs"}

    prev = recent.tail(min(len(recent), 6)).copy()
    recent_high = prev["high"].astype(float)
    recent_low = prev["low"].astype(float)
    vol_ma = float(recent["volume"].astype(float).tail(12).mean()) if "volume" in recent.columns else max(volume, 1.0)
    vol_ratio = (volume / vol_ma) if vol_ma > 0 else 1.0
    candle_range = max(high - low, 1e-9)
    body_atr = abs(close - open_) / max(atr_ltf, 1e-9)
    close_pos = (close - low) / candle_range
    flush_lookback = int(getattr(cfg, "BTC_RANGE_ENGINE_V1_RECLAIM_FLUSH_LOOKBACK", 6))
    flush_lows = recent["low"].astype(float).tail(max(flush_lookback, 3))
    flush_highs = recent["high"].astype(float).tail(max(flush_lookback, 3))
    lower_break = max(0.0, range_low - float(flush_lows.min()))
    upper_break = max(0.0, float(flush_highs.max()) - range_high)
    lower_break_atr = lower_break / max(atr_ltf, 1e-9)
    upper_break_atr = upper_break / max(atr_ltf, 1e-9)
    reclaim_dist_atr = abs(close - ema20) / max(atr_ltf, 1e-9)

    min_flush_atr = float(getattr(cfg, "BTC_RANGE_ENGINE_V1_RECLAIM_MIN_FLUSH_ATR", 0.45))
    min_body_atr = float(getattr(cfg, "BTC_RANGE_ENGINE_V1_RECLAIM_MIN_BODY_ATR", 0.28))
    min_vol_ratio = float(getattr(cfg, "BTC_RANGE_ENGINE_V1_RECLAIM_MIN_VOL_RATIO", 0.95))
    long_rsi_max = float(getattr(cfg, "BTC_RANGE_ENGINE_V1_RECLAIM_LONG_RSI_MAX", 45.0))
    short_rsi_min = float(getattr(cfg, "BTC_RANGE_ENGINE_V1_RECLAIM_SHORT_RSI_MIN", 55.0))
    max_reclaim_dist_atr = float(getattr(cfg, "BTC_RANGE_ENGINE_V1_RECLAIM_MAX_DIST_TO_EMA20_ATR", 0.75))
    long_close_pos_min = float(getattr(cfg, "BTC_RANGE_ENGINE_V1_RECLAIM_LONG_CLOSE_POS_MIN", 0.58))
    short_close_pos_min = float(getattr(cfg, "BTC_RANGE_ENGINE_V1_RECLAIM_SHORT_CLOSE_POS_MIN", 0.58))

    common = {
        "vol_ratio": vol_ratio,
        "body_atr": body_atr,
        "reclaim_dist_atr": reclaim_dist_atr,
        "lower_break_atr": lower_break_atr,
        "upper_break_atr": upper_break_atr,
        "rsi": rsi,
        "range_low": range_low,
        "range_high": range_high,
        "ema20": ema20,
    }

    long_ok = (
        lower_break_atr >= min_flush_atr
        and close >= ema20
        and close >= range_low
        and close > open_
        and close_pos >= long_close_pos_min
        and rsi <= long_rsi_max
        and body_atr >= min_body_atr
        and vol_ratio >= min_vol_ratio
        and reclaim_dist_atr <= max_reclaim_dist_atr
    )
    if long_ok:
        return "buy", {**common, "reason": "range_reclaim_after_flush_long"}

    short_close_pos = 1.0 - close_pos
    short_ok = (
        upper_break_atr >= min_flush_atr
        and close <= ema20
        and close <= range_high
        and close < open_
        and short_close_pos >= short_close_pos_min
        and rsi >= short_rsi_min
        and body_atr >= min_body_atr
        and vol_ratio >= min_vol_ratio
        and reclaim_dist_atr <= max_reclaim_dist_atr
    )
    if short_ok:
        return "sell", {**common, "close_pos_short": short_close_pos, "reason": "range_reclaim_after_flush_short"}

    return None, {**common, "reason": "reclaim_after_flush_not_ready"}


def _validate_range_signal_v2(*, cfg, signal: str, trade_type: str, last: pd.Series, close: float, atr_ltf: float, range_high: float, range_low: float, range_regime: str, range_regime_meta: dict, drift: float = 0.0) -> tuple[bool, dict]:
    if atr_ltf <= 0 or close <= 0:
        return False, {"reason": "bad_validate_inputs"}
    try:
        ema20 = float(last.get("EMA20", close))
        high = float(last.get("high", close))
        low = float(last.get("low", close))
        open_ = float(last.get("open", close))
        rsi = float(last.get("RSI", 50.0))
    except Exception:
        return False, {"reason": "bad_validate_parse"}

    range_mid = (range_high + range_low) * 0.5
    range_width_pct = float(range_regime_meta.get("range_width_pct", 0.0) or 0.0)
    false_breakout_ratio = float(range_regime_meta.get("false_breakout_ratio", 0.0) or 0.0)
    wickiness = float(range_regime_meta.get("wickiness", 0.0) or 0.0)
    dist_to_mid_atr = abs(close - range_mid) / max(atr_ltf, 1e-9)
    dist_to_ema20_atr = abs(close - ema20) / max(atr_ltf, 1e-9)
    candle_range = max(high - low, 1e-9)
    close_pos = (close - low) / candle_range
    body_atr = abs(close - open_) / max(atr_ltf, 1e-9)

    min_width_pct = float(getattr(cfg, "BTC_RANGE_ENGINE_V1_MIN_RANGE_WIDTH_PCT", 0.012))
    max_width_pct = float(getattr(cfg, "BTC_RANGE_ENGINE_V1_MAX_RANGE_WIDTH_PCT", 0.055))
    min_dist_mid_atr = float(getattr(cfg, "BTC_RANGE_ENGINE_V1_MIN_DISTANCE_TO_RANGE_MID_ATR", 0.55))
    min_dist_ema20_atr = float(getattr(cfg, "BTC_RANGE_ENGINE_V1_MIN_DISTANCE_TO_EMA20_ATR", 0.20))
    max_dist_ema20_atr = float(getattr(cfg, "BTC_RANGE_ENGINE_V1_MAX_DISTANCE_TO_EMA20_ATR", 1.10))

    if range_width_pct < min_width_pct or range_width_pct > max_width_pct:
        return False, {"reason": "range_width_invalid", "range_width_pct": range_width_pct}
    if dist_to_mid_atr < min_dist_mid_atr:
        return False, {"reason": "too_close_to_mid", "dist_to_mid_atr": dist_to_mid_atr}
    if trade_type != "liquidity_reversal" and (dist_to_ema20_atr < min_dist_ema20_atr or dist_to_ema20_atr > max_dist_ema20_atr):
        return False, {"reason": "ema20_distance_invalid", "dist_to_ema20_atr": dist_to_ema20_atr}

    require_side_away = bool(getattr(cfg, "BTC_RANGE_ENGINE_V1_REQUIRE_SIDE_AWAY_FROM_EMA20", True))
    if signal == "buy":
        if require_side_away and trade_type != "liquidity_reversal" and close > ema20:
            return False, {"reason": "long_not_below_ema20", "ema20": ema20}
        if trade_type != "liquidity_reversal" and close_pos < 0.52:
            return False, {"reason": "long_close_pos_too_low", "close_pos": close_pos}
        if trade_type == "range" and rsi > float(getattr(cfg, "RANGE_RSI_LONG_MAX", 40.0)):
            return False, {"reason": "long_rsi_not_low_enough", "rsi": rsi}
    else:
        if require_side_away and trade_type != "liquidity_reversal" and close < ema20:
            return False, {"reason": "short_not_above_ema20", "ema20": ema20}
        if trade_type != "liquidity_reversal" and (1.0 - close_pos) < 0.52:
            return False, {"reason": "short_close_pos_too_low", "close_pos": 1.0-close_pos}
        if trade_type == "range" and rsi < float(getattr(cfg, "RANGE_RSI_SHORT_MIN", 72.0)):
            return False, {"reason": "short_rsi_not_high_enough", "rsi": rsi}

    if trade_type == "range":
        max_false_breakout = float(getattr(cfg, "BTC_RANGE_ENGINE_V1_MAX_FALSE_BREAKOUT_RATIO_FOR_BOUNCE", 0.24))
        if false_breakout_ratio > max_false_breakout:
            return False, {"reason": "bounce_false_breakout_too_high", "false_breakout_ratio": false_breakout_ratio}
    if trade_type == "liquidity_reversal":
        min_inside_atr = float(getattr(cfg, "BTC_RANGE_ENGINE_V1_LIQUIDITY_MIN_INSIDE_RANGE_ATR", 0.10))
        max_drift = float(getattr(cfg, "BTC_RANGE_ENGINE_V1_LIQUIDITY_MAX_DRIFT_PCT", 0.0085))
        long_close_pos_min = float(getattr(cfg, "BTC_RANGE_ENGINE_V1_LIQUIDITY_LONG_CLOSE_POS_MIN", 0.58))
        short_close_pos_min = float(getattr(cfg, "BTC_RANGE_ENGINE_V1_LIQUIDITY_SHORT_CLOSE_POS_MIN", 0.58))
        if abs(drift) > max_drift and range_regime in {"transition_range", "volatile_range"}:
            return False, {"reason": "drift_too_high_for_liquidity_reversal", "drift": drift}
        if signal == "buy":
            inside_range_atr = (close - range_low) / max(atr_ltf, 1e-9)
            if inside_range_atr < min_inside_atr:
                return False, {"reason": "long_not_far_enough_back_inside_range", "inside_range_atr": inside_range_atr}
            if close_pos < long_close_pos_min:
                return False, {"reason": "liquidity_long_close_pos_too_low", "close_pos": close_pos}
        else:
            inside_range_atr = (range_high - close) / max(atr_ltf, 1e-9)
            if inside_range_atr < min_inside_atr:
                return False, {"reason": "short_not_far_enough_back_inside_range", "inside_range_atr": inside_range_atr}
            if (1.0 - close_pos) < short_close_pos_min:
                return False, {"reason": "liquidity_short_close_pos_too_low", "close_pos": 1.0 - close_pos}
        if body_atr < float(getattr(cfg, "BTC_RANGE_ENGINE_V1_SIMPLE_SWEEP_MIN_BODY_ATR", 0.10)):
            return False, {"reason": "liquidity_body_too_small", "body_atr": body_atr}
    if range_regime == "quiet_range" and wickiness > float(getattr(cfg, "BTC_RANGE_ENGINE_V1_QUIET_WICKINESS_MAX", 0.54)):
        return False, {"reason": "quiet_range_too_wicky", "wickiness": wickiness}

    return True, {
        "range_mid": range_mid,
        "dist_to_mid_atr": dist_to_mid_atr,
        "dist_to_ema20_atr": dist_to_ema20_atr,
        "range_width_pct": range_width_pct,
        "false_breakout_ratio": false_breakout_ratio,
        "wickiness": wickiness,
    }


def _simple_sweep_reclaim_candidate(*, cfg, side: str, recent: pd.DataFrame, last: pd.Series, close: float, atr_ltf: float, range_high: float, range_low: float) -> tuple[bool, dict]:
    if len(recent) < 3 or atr_ltf <= 0:
        return False, {"reason": "simple_sweep_not_enough_history"}
    try:
        prev = recent.iloc[-1]
        open_ = float(last.get("open", close))
        high = float(last.get("high", close))
        low = float(last.get("low", close))
        prev_open = float(prev.get("open", prev.get("close", close)))
        prev_high = float(prev.get("high", high))
        prev_low = float(prev.get("low", low))
        prev_close = float(prev.get("close", close))
        rsi = float(last.get("RSI", 50.0))
    except Exception:
        return False, {"reason": "simple_sweep_parse_error"}

    pierce_atr = float(getattr(cfg, "BTC_RANGE_ENGINE_V1_SIMPLE_SWEEP_PIERCE_ATR", 0.06))
    reclaim_atr = float(getattr(cfg, "BTC_RANGE_ENGINE_V1_SIMPLE_SWEEP_RECLAIM_ATR", 0.03))
    min_body_atr = float(getattr(cfg, "BTC_RANGE_ENGINE_V1_SIMPLE_SWEEP_MIN_BODY_ATR", 0.05))
    long_rsi_max = float(getattr(cfg, "BTC_RANGE_ENGINE_V1_SIMPLE_SWEEP_LONG_RSI_MAX", 62.0))
    short_rsi_min = float(getattr(cfg, "BTC_RANGE_ENGINE_V1_SIMPLE_SWEEP_SHORT_RSI_MIN", 38.0))
    require_prev_close_outside = bool(getattr(cfg, "BTC_RANGE_ENGINE_V1_SIMPLE_SWEEP_REQUIRE_PREV_CLOSE_OUTSIDE", True))
    min_prev_close_outside_atr = float(getattr(cfg, "BTC_RANGE_ENGINE_V1_SIMPLE_SWEEP_MIN_PREV_CLOSE_OUTSIDE_ATR", 0.04))
    require_prev_direction = bool(getattr(cfg, "BTC_RANGE_ENGINE_V1_SIMPLE_SWEEP_REQUIRE_PREV_DIRECTION", True))
    body_atr = abs(close - open_) / max(atr_ltf, 1e-9)

    if side == "long":
        pierced = min(low, prev_low) <= (range_low - pierce_atr * atr_ltf)
        reclaimed = close >= (range_low + reclaim_atr * atr_ltf)
        prev_close_outside = prev_close <= (range_low - min_prev_close_outside_atr * atr_ltf)
        prev_direction_ok = prev_close <= prev_open if require_prev_direction else True
        directional = close >= open_ and close >= prev_close
        close_pos = (close - low) / max(high - low, 1e-9)
        rsi_ok = rsi <= long_rsi_max
        ok = pierced and reclaimed and directional and rsi_ok and body_atr >= min_body_atr and close_pos >= 0.58 and (prev_close_outside if require_prev_close_outside else True) and prev_direction_ok
        return ok, {
            "reason": "simple_sweep_long" if ok else "candidate_false",
            "pierced": pierced,
            "reclaimed": reclaimed,
            "prev_close_outside": prev_close_outside,
            "prev_direction_ok": prev_direction_ok,
            "directional": directional,
            "rsi_ok": rsi_ok,
            "close_pos": close_pos,
            "body_atr": body_atr,
            "rsi": rsi,
            "side": side,
        }

    pierced = max(high, prev_high) >= (range_high + pierce_atr * atr_ltf)
    reclaimed = close <= (range_high - reclaim_atr * atr_ltf)
    prev_close_outside = prev_close >= (range_high + min_prev_close_outside_atr * atr_ltf)
    prev_direction_ok = prev_close >= prev_open if require_prev_direction else True
    directional = close <= open_ and close <= prev_close
    close_pos_short = 1.0 - ((close - low) / max(high - low, 1e-9))
    rsi_ok = rsi >= short_rsi_min
    ok = pierced and reclaimed and directional and rsi_ok and body_atr >= min_body_atr and close_pos_short >= 0.58 and (prev_close_outside if require_prev_close_outside else True) and prev_direction_ok
    return ok, {
        "reason": "simple_sweep_short" if ok else "candidate_false",
        "pierced": pierced,
        "reclaimed": reclaimed,
        "prev_close_outside": prev_close_outside,
        "prev_direction_ok": prev_direction_ok,
        "directional": directional,
        "rsi_ok": rsi_ok,
        "close_pos_short": close_pos_short,
        "body_atr": body_atr,
        "rsi": rsi,
        "side": side,
    }


def _reaction_edge_candidate(*, cfg, side: str, recent: pd.DataFrame, last: pd.Series, close: float, atr_ltf: float, range_high: float, range_low: float, drift: float) -> tuple[bool, dict]:
    if len(recent) < 2 or atr_ltf <= 0 or range_high <= range_low:
        return False, {"reason": "reaction_not_enough_context"}
    try:
        open_ = float(last.get("open", close))
        high = float(last.get("high", close))
        low = float(last.get("low", close))
        rsi = float(last.get("RSI", 50.0))
        prev = recent.iloc[-1]
        prev_open = float(prev.get("open", prev.get("close", close)))
        prev_close = float(prev.get("close", close))
        prev_high = float(prev.get("high", high))
        prev_low = float(prev.get("low", low))
    except Exception:
        return False, {"reason": "reaction_parse_error"}

    width = max(range_high - range_low, 1e-9)
    zone_pct = float(getattr(cfg, "BTC_RANGE_ENGINE_V1_REACTION_EDGE_ZONE_PCT", 0.18))
    min_body_atr = float(getattr(cfg, "BTC_RANGE_ENGINE_V1_REACTION_MIN_BODY_ATR", 0.08))
    reclaim_atr = float(getattr(cfg, "BTC_RANGE_ENGINE_V1_REACTION_RECLAIM_ATR", 0.05))
    max_drift = float(getattr(cfg, "BTC_RANGE_ENGINE_V1_REACTION_MAX_DRIFT_PCT", 0.0160))
    require_prev_opposite = bool(getattr(cfg, "BTC_RANGE_ENGINE_V1_REACTION_REQUIRE_PREV_OPPOSITE", True))
    long_rsi_max = float(getattr(cfg, "BTC_RANGE_ENGINE_V1_SCALP_LONG_RSI_MAX", 58.0))
    short_rsi_min = float(getattr(cfg, "BTC_RANGE_ENGINE_V1_SCALP_SHORT_RSI_MIN", 42.0))
    long_close_pos_min = float(getattr(cfg, "BTC_RANGE_ENGINE_V1_REACTION_LONG_CLOSE_POS_MIN", 0.58))
    short_close_pos_min = float(getattr(cfg, "BTC_RANGE_ENGINE_V1_REACTION_SHORT_CLOSE_POS_MIN", 0.58))

    if abs(drift) > max_drift:
        return False, {"reason": "reaction_drift_too_high", "drift": drift, "side": side}

    close_pos_range = (close - range_low) / width
    candle_range = max(high - low, 1e-9)
    close_pos_candle = (close - low) / candle_range
    body_atr = abs(close - open_) / max(atr_ltf, 1e-9)
    bullish = close > open_
    bearish = close < open_

    if side == "long":
        near_lower = min(low, prev_low) <= (range_low + zone_pct * width)
        reclaim = close >= (range_low + reclaim_atr * atr_ltf)
        reaction = bullish and close > prev_close
        prev_opposite = prev_close <= prev_open if require_prev_opposite else True
        ok = near_lower and reclaim and reaction and prev_opposite and body_atr >= min_body_atr and close_pos_candle >= long_close_pos_min and rsi <= long_rsi_max
        return ok, {
            "reason": "reaction_range_long" if ok else "candidate_false",
            "near_lower": near_lower, "reclaim": reclaim, "reaction": reaction, "prev_opposite": prev_opposite,
            "body_atr": body_atr, "close_pos_candle": close_pos_candle, "close_pos_range": close_pos_range, "rsi": rsi, "side": side,
        }

    near_upper = max(high, prev_high) >= (range_high - zone_pct * width)
    reclaim = close <= (range_high - reclaim_atr * atr_ltf)
    reaction = bearish and close < prev_close
    prev_opposite = prev_close >= prev_open if require_prev_opposite else True
    close_pos_candle_short = 1.0 - close_pos_candle
    ok = near_upper and reclaim and reaction and prev_opposite and body_atr >= min_body_atr and close_pos_candle_short >= short_close_pos_min and rsi >= short_rsi_min
    return ok, {
        "reason": "reaction_range_short" if ok else "candidate_false",
        "near_upper": near_upper, "reclaim": reclaim, "reaction": reaction, "prev_opposite": prev_opposite,
        "body_atr": body_atr, "close_pos_candle_short": close_pos_candle_short, "close_pos_range": close_pos_range, "rsi": rsi, "side": side,
    }


def run_btc_range_engine_v1(*, cfg, symbol: str, market_state: str, regime: str, df: pd.DataFrame, recent: pd.DataFrame, last: pd.Series,
                            close: float, atr_ltf: float, adx_h: float, drift: float, range_high: float, range_low: float,
                            market_meta: dict | None = None) -> tuple[Optional[str], Optional[str], float, dict]:
    if not bool(getattr(cfg, "BTC_RANGE_ENGINE_V1_ENABLED", True)):
        return None, None, 1.0, {"reason": "range_engine_v1_disabled"}
    btc_symbol = str(getattr(cfg, "BTC_REGIME_FILTER_SYMBOL", "BTCUSDT"))
    if symbol != btc_symbol:
        return None, None, 1.0, {"reason": "not_btc_symbol"}

    allowed_states = {str(x).lower() for x in (getattr(cfg, "BTC_RANGE_ENGINE_V1_ALLOWED_MARKET_STATES", ["range", "transition", "flat", "chop"]) or [])}
    if str(market_state or "").lower() not in allowed_states:
        return None, None, 1.0, {"reason": "market_state_not_allowed", "market_state": market_state}

    max_market_state_drift = float(getattr(cfg, "BTC_RANGE_ENGINE_V1_MAX_MARKET_STATE_DRIFT_PCT", 0.0095))
    max_market_state_adx = float(getattr(cfg, "BTC_RANGE_ENGINE_V1_MAX_MARKET_STATE_ADX", 26.0))
    if abs(drift) > max_market_state_drift or adx_h > max_market_state_adx:
        return None, None, 1.0, {"reason": "market_state_filter_too_directional", "market_state": market_state, "adx_h": adx_h, "drift": drift}

    if bool(getattr(cfg, "BTC_RANGE_ENGINE_V1_BLOCK_IN_STRONG_TREND", True)):
        strong_adx_min = float(getattr(cfg, "BTC_RANGE_ENGINE_V1_STRONG_TREND_ADX_MIN", 21.0))
        strong_drift_min = float(getattr(cfg, "BTC_RANGE_ENGINE_V1_STRONG_TREND_DRIFT_MIN", 0.0045))
        if adx_h >= strong_adx_min and abs(drift) >= strong_drift_min:
            return None, None, 1.0, {"reason": "blocked_by_strong_trend", "adx_h": adx_h, "drift": drift}

    range_regime, range_regime_meta = detect_btc_range_regime_v1(cfg=cfg, recent=recent, close=close, atr_ltf=atr_ltf, adx_h=adx_h, drift=drift)
    regime_allow = {str(x).lower() for x in (getattr(cfg, "BTC_RANGE_ENGINE_V1_ALLOWED_RANGE_REGIMES", ["quiet_range", "volatile_range", "liquidity_sweep_range", "transition_range"]) or [])}
    if range_regime not in regime_allow:
        return None, None, 1.0, {"reason": "range_regime_not_allowed", "range_regime": range_regime, **range_regime_meta}

    allowed_setups = {str(x).lower() for x in (getattr(cfg, "BTC_RANGE_ENGINE_V1_ALLOWED_SETUPS", ["range_bounce", "liquidity_sweep_reversal", "reclaim_after_flush"]) or [])}
    allow_shorts = bool(getattr(cfg, "BTC_RANGE_ENGINE_V1_ALLOW_SHORTS", True))
    short_filter_adx_max = float(getattr(cfg, "BTC_RANGE_ENGINE_V1_SHORT_FILTER_ADX_MAX", 18.0))
    short_filter_drift_max = float(getattr(cfg, "BTC_RANGE_ENGINE_V1_SHORT_FILTER_DRIFT_MAX", 0.0045))
    allow_shorts = bool(allow_shorts and range_regime in {"quiet_range", "liquidity_sweep_range", "transition_range"} and adx_h <= short_filter_adx_max and abs(drift) <= short_filter_drift_max)
    debug = {
        "engine": "btc_range_engine_v1",
        "market_state": market_state,
        "regime": regime,
        "range_regime": range_regime,
        "range_regime_meta": range_regime_meta,
        "allow_shorts": allow_shorts,
    }

    scalp_regimes = {str(x).lower() for x in (getattr(cfg, "BTC_RANGE_ENGINE_V1_SCALP_ALLOWED_REGIMES", ["quiet_range", "volatile_range", "transition_range", "liquidity_sweep_range"]) or [])}
    if "reaction_range" in allowed_setups and range_regime in scalp_regimes:
        long_ok, long_meta = _reaction_edge_candidate(cfg=cfg, side="long", recent=recent, last=last, close=close, atr_ltf=atr_ltf, range_high=range_high, range_low=range_low, drift=drift)
        debug["long_candidate_reason"] = long_meta.get("reason", "candidate_true" if long_ok else "candidate_false")
        debug["long_candidate_meta"] = long_meta
        if long_ok:
            valid_long, valid_long_meta = _validate_range_signal_v2(cfg=cfg, signal="buy", trade_type="reaction_range", last=last, close=close, atr_ltf=atr_ltf, range_high=range_high, range_low=range_low, range_regime=range_regime, range_regime_meta=range_regime_meta, drift=drift)
            debug["long_validation_reason"] = valid_long_meta.get("reason", "validated" if valid_long else "validation_failed")
            if valid_long:
                return "buy", "reaction_range", float(getattr(cfg, "BTC_RANGE_ENGINE_V1_SOFT_RANGE_RISK_MULT", 0.035)), {
                    **long_meta,
                    **valid_long_meta,
                    **debug,
                    "range_setup": "reaction_range",
                    "reason": "reaction_range_long",
                    "allow_btc_range_short_bypass": bool(getattr(cfg, "BTC_RANGE_ENGINE_V1_BYPASS_BTC_SHORT_BLOCK", True)),
                }

        short_ok, short_meta = _reaction_edge_candidate(cfg=cfg, side="short", recent=recent, last=last, close=close, atr_ltf=atr_ltf, range_high=range_high, range_low=range_low, drift=drift)
        debug["short_candidate_reason"] = short_meta.get("reason", "candidate_true" if short_ok else "candidate_false")
        debug["short_candidate_meta"] = short_meta
        if allow_shorts and short_ok:
            valid_short, valid_short_meta = _validate_range_signal_v2(cfg=cfg, signal="sell", trade_type="reaction_range", last=last, close=close, atr_ltf=atr_ltf, range_high=range_high, range_low=range_low, range_regime=range_regime, range_regime_meta=range_regime_meta, drift=drift)
            debug["short_validation_reason"] = valid_short_meta.get("reason", "validated" if valid_short else "validation_failed")
            if valid_short:
                return "sell", "reaction_range", float(getattr(cfg, "BTC_RANGE_ENGINE_V1_SOFT_RANGE_RISK_MULT", 0.035)), {
                    **short_meta,
                    **valid_short_meta,
                    **debug,
                    "range_setup": "reaction_range",
                    "reason": "reaction_range_short",
                    "allow_btc_range_short_bypass": bool(getattr(cfg, "BTC_RANGE_ENGINE_V1_BYPASS_BTC_SHORT_BLOCK", True)),
                }

    if False and "liquidity_sweep_reversal" in allowed_setups and range_regime in {"liquidity_sweep_range", "quiet_range", "transition_range"}:
        long_ok, long_meta = check_fakeout_reversal_entry(symbol=symbol, df=df, recent=recent, side="long", range_high=range_high, range_low=range_low, atr_ltf=atr_ltf, adx_h=adx_h)
        if not long_ok:
            long_ok, long_meta = _simple_sweep_reclaim_candidate(cfg=cfg, side="long", recent=recent, last=last, close=close, atr_ltf=atr_ltf, range_high=range_high, range_low=range_low)
            long_meta = {**long_meta, "candidate_source": "simple_sweep"}
        else:
            long_meta = {**long_meta, "candidate_source": "fakeout_reversal"}
        debug["long_candidate_reason"] = long_meta.get("reason", "candidate_true" if long_ok else "candidate_false")
        debug["long_candidate_meta"] = long_meta
        if long_ok:
            valid_long, valid_long_meta = _validate_range_signal_v2(cfg=cfg, signal="buy", trade_type="liquidity_reversal", last=last, close=close, atr_ltf=atr_ltf, range_high=range_high, range_low=range_low, range_regime=range_regime, range_regime_meta=range_regime_meta, drift=drift)
            debug["long_validation_reason"] = valid_long_meta.get("reason", "validated" if valid_long else "validation_failed")
            if valid_long:
                return "buy", "liquidity_reversal", float(getattr(cfg, "BTC_RANGE_ENGINE_V1_LIQUIDITY_REVERSAL_RISK_MULT", 0.40)), {
                    **long_meta,
                    **valid_long_meta,
                    **debug,
                    "range_setup": "liquidity_sweep_reversal",
                    "reason": "liquidity_sweep_reversal_long",
                    "allow_btc_range_short_bypass": bool(getattr(cfg, "BTC_RANGE_ENGINE_V1_BYPASS_BTC_SHORT_BLOCK", True)),
                }

        short_ok, short_meta = check_fakeout_reversal_entry(symbol=symbol, df=df, recent=recent, side="short", range_high=range_high, range_low=range_low, atr_ltf=atr_ltf, adx_h=adx_h)
        if not short_ok:
            short_ok, short_meta = _simple_sweep_reclaim_candidate(cfg=cfg, side="short", recent=recent, last=last, close=close, atr_ltf=atr_ltf, range_high=range_high, range_low=range_low)
            short_meta = {**short_meta, "candidate_source": "simple_sweep"}
        else:
            short_meta = {**short_meta, "candidate_source": "fakeout_reversal"}
        debug["short_candidate_reason"] = short_meta.get("reason", "candidate_true" if short_ok else "candidate_false")
        debug["short_candidate_meta"] = short_meta
        if allow_shorts and short_ok:
            valid_short, valid_short_meta = _validate_range_signal_v2(cfg=cfg, signal="sell", trade_type="liquidity_reversal", last=last, close=close, atr_ltf=atr_ltf, range_high=range_high, range_low=range_low, range_regime=range_regime, range_regime_meta=range_regime_meta, drift=drift)
            debug["short_validation_reason"] = valid_short_meta.get("reason", "validated" if valid_short else "validation_failed")
            if valid_short:
                return "sell", "liquidity_reversal", float(getattr(cfg, "BTC_RANGE_ENGINE_V1_LIQUIDITY_REVERSAL_RISK_MULT", 0.40)), {
                    **short_meta,
                    **valid_short_meta,
                    **debug,
                    "range_setup": "liquidity_sweep_reversal",
                    "reason": "liquidity_sweep_reversal_short",
                    "allow_btc_range_short_bypass": bool(getattr(cfg, "BTC_RANGE_ENGINE_V1_BYPASS_BTC_SHORT_BLOCK", True)),
                }

    if "reclaim_after_flush" in allowed_setups and range_regime in {"liquidity_sweep_range"}:
        reclaim_signal, reclaim_meta = check_reclaim_after_flush_entry(cfg=cfg, symbol=symbol, recent=recent, candle=last, atr_ltf=atr_ltf, range_high=range_high, range_low=range_low)
        debug["reclaim_reason"] = reclaim_meta.get("reason", "reclaim_none")
        if reclaim_signal is not None and (reclaim_signal != "sell" or allow_shorts):
            valid_reclaim, valid_reclaim_meta = _validate_range_signal_v2(cfg=cfg, signal=reclaim_signal, trade_type="reclaim_range", last=last, close=close, atr_ltf=atr_ltf, range_high=range_high, range_low=range_low, range_regime=range_regime, range_regime_meta=range_regime_meta, drift=drift)
            debug[f"{'long' if reclaim_signal=='buy' else 'short'}_validation_reason"] = valid_reclaim_meta.get("reason", "validated" if valid_reclaim else "validation_failed")
            if valid_reclaim:
                return reclaim_signal, "reclaim_range", float(getattr(cfg, "BTC_RANGE_ENGINE_V1_RECLAIM_RISK_MULT", 0.38)), {
                    **reclaim_meta,
                    **valid_reclaim_meta,
                    **debug,
                    "range_setup": "reclaim_after_flush",
                    "reason": str(reclaim_meta.get("reason", "reclaim_after_flush")),
                    "allow_btc_range_short_bypass": bool(getattr(cfg, "BTC_RANGE_ENGINE_V1_BYPASS_BTC_SHORT_BLOCK", True)),
                }

    return None, None, 1.0, {
        **debug,
        "reason": "no_range_engine_v1_setup",
    }
