"""Entry-pattern helpers extracted from mtf_breakout.py without logic changes."""
from __future__ import annotations

import numpy as np
import pandas as pd
import config as cfg

def check_impulse_breakout(symbol: str, recent: pd.DataFrame, candle: pd.Series, side: str, trigger: float, atr_ltf: float) -> tuple[bool, dict]:
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

def check_breakout_confirmation(symbol: str, df: pd.DataFrame, side: str, trigger: float, range_high: float, range_low: float, atr_ltf: float) -> tuple[bool, dict]:
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

def check_pullback_trend_entry(symbol: str, df: pd.DataFrame, side: str, atr_ltf: float) -> tuple[bool, dict]:
    if len(df) < 120 or atr_ltf <= 0:
        return False, {"reason": "not_enough_pullback_history"}
    need_cols = {"EMA20", "EMA50", "EMA200", "open", "high", "low", "close", "volume", "RSI", "HTF_ADX", "HTF_EMA20"}
    if not need_cols.issubset(df.columns):
        return False, {"reason": "missing_pullback_cols"}
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
        prev_high = float(prev.get("high", np.nan))
        prev_low = float(prev.get("low", np.nan))
        prev_ema20 = float(prev.get("EMA20", np.nan))
        prev_ema50 = float(prev.get("EMA50", np.nan))
        rsi = float(last.get("RSI", np.nan))
        htf_adx = float(last.get("HTF_ADX", np.nan))
        htf_ema20 = float(last.get("HTF_EMA20", np.nan))
    except Exception:
        return False, {"reason": "bad_pullback_values"}

    vals = [ema20, ema50, ema200, close, open_, high, low, prev_close, prev_open, prev_high, prev_low, prev_ema20, prev_ema50, rsi, htf_adx, htf_ema20]
    if any(np.isnan(x) for x in vals):
        return False, {"reason": "nan_pullback_values"}

    trend_ok = (ema20 > ema50 > ema200) if side == "long" else (ema20 < ema50 < ema200)
    if not trend_ok:
        return False, {"reason": "ltf_alignment_fail"}

    touch_atr = cfg.get_symbol_param_float(symbol, "PULLBACK_TOUCH_ATR", float(getattr(cfg, "PULLBACK_TOUCH_ATR", 0.55)))
    deep_touch_atr = cfg.get_symbol_param_float(symbol, "PULLBACK_MAX_DEEP_TOUCH_ATR", float(getattr(cfg, "PULLBACK_MAX_DEEP_TOUCH_ATR", 1.10)))
    min_body_atr = cfg.get_symbol_param_float(symbol, "PULLBACK_MIN_BODY_ATR", float(getattr(cfg, "PULLBACK_MIN_BODY_ATR", 0.30)))
    min_close_pos = cfg.get_symbol_param_float(symbol, "PULLBACK_MIN_CLOSE_POS", float(getattr(cfg, "PULLBACK_MIN_CLOSE_POS", 0.55)))
    min_vol_ratio = cfg.get_symbol_param_float(symbol, "PULLBACK_MIN_VOL_RATIO", float(getattr(cfg, "PULLBACK_MIN_VOL_RATIO", 0.90)))
    min_htf_adx = cfg.get_symbol_param_float(symbol, "PULLBACK_MIN_HTF_ADX", float(getattr(cfg, "PULLBACK_MIN_HTF_ADX", 20.0)))
    require_prev_counter = bool(getattr(cfg, "PULLBACK_REQUIRE_PREV_COUNTER_CANDLE", True))
    prev_close_pos_max = cfg.get_symbol_param_float(symbol, "PULLBACK_PREV_CLOSE_POS_MAX", float(getattr(cfg, "PULLBACK_PREV_CLOSE_POS_MAX", 0.62)))
    reclaim_ema20 = bool(getattr(cfg, "PULLBACK_RECLAIM_EMA20_REQUIRED", True))
    min_rsi_long = cfg.get_symbol_param_float(symbol, "PULLBACK_RSI_LONG_MIN", float(getattr(cfg, "PULLBACK_RSI_LONG_MIN", 46.0)))
    max_rsi_long = cfg.get_symbol_param_float(symbol, "PULLBACK_RSI_LONG_MAX", float(getattr(cfg, "PULLBACK_RSI_LONG_MAX", 63.0)))
    min_rsi_short = cfg.get_symbol_param_float(symbol, "PULLBACK_RSI_SHORT_MIN", float(getattr(cfg, "PULLBACK_RSI_SHORT_MIN", 37.0)))
    max_rsi_short = cfg.get_symbol_param_float(symbol, "PULLBACK_RSI_SHORT_MAX", float(getattr(cfg, "PULLBACK_RSI_SHORT_MAX", 54.0)))
    pre_impulse_bars = int(getattr(cfg, "PULLBACK_PRE_IMPULSE_BARS", 8))
    pre_impulse_min_atr = cfg.get_symbol_param_float(symbol, "PULLBACK_PRE_IMPULSE_MIN_ATR", float(getattr(cfg, "PULLBACK_PRE_IMPULSE_MIN_ATR", 1.45)))
    pre_impulse_min_atr_short = cfg.get_symbol_param_float(symbol, "PULLBACK_PRE_IMPULSE_MIN_ATR_SHORT", float(getattr(cfg, "PULLBACK_PRE_IMPULSE_MIN_ATR_SHORT", 1.75)))
    max_ema20_crosses = int(getattr(cfg, "PULLBACK_MAX_EMA20_CROSSES", 2))
    max_avg_wick_ratio = cfg.get_symbol_param_float(symbol, "PULLBACK_MAX_AVG_WICK_RATIO", float(getattr(cfg, "PULLBACK_MAX_AVG_WICK_RATIO", 0.46)))
    min_ema20_slope_pct = cfg.get_symbol_param_float(symbol, "PULLBACK_MIN_EMA20_SLOPE_PCT", float(getattr(cfg, "PULLBACK_MIN_EMA20_SLOPE_PCT", 0.00055)))
    min_ema50_slope_pct = cfg.get_symbol_param_float(symbol, "PULLBACK_MIN_EMA50_SLOPE_PCT", float(getattr(cfg, "PULLBACK_MIN_EMA50_SLOPE_PCT", 0.00035)))
    min_ema20_slope_pct_short = cfg.get_symbol_param_float(symbol, "PULLBACK_MIN_EMA20_SLOPE_PCT_SHORT", float(getattr(cfg, "PULLBACK_MIN_EMA20_SLOPE_PCT_SHORT", 0.00075)))
    min_ema50_slope_pct_short = cfg.get_symbol_param_float(symbol, "PULLBACK_MIN_EMA50_SLOPE_PCT_SHORT", float(getattr(cfg, "PULLBACK_MIN_EMA50_SLOPE_PCT_SHORT", 0.00045)))
    max_price_to_htf_ema20_pct = cfg.get_symbol_param_float(symbol, "PULLBACK_MAX_PRICE_TO_HTF_EMA20_PCT", float(getattr(cfg, "PULLBACK_MAX_PRICE_TO_HTF_EMA20_PCT", 0.030)))
    max_price_to_htf_ema20_pct_short = cfg.get_symbol_param_float(symbol, "PULLBACK_MAX_PRICE_TO_HTF_EMA20_PCT_SHORT", float(getattr(cfg, "PULLBACK_MAX_PRICE_TO_HTF_EMA20_PCT_SHORT", 0.025)))
    max_same_dir_bars = int(getattr(cfg, "PULLBACK_MAX_PRE_IMPULSE_SAME_DIR_BARS", 5))
    max_same_dir_bars_short = int(getattr(cfg, "PULLBACK_MAX_PRE_IMPULSE_SAME_DIR_BARS_SHORT", 4))
    decay_lookback = int(getattr(cfg, "PULLBACK_DECAY_LOOKBACK", 4))
    min_decay_ratio = cfg.get_symbol_param_float(symbol, "PULLBACK_MIN_MOMENTUM_DECAY_RATIO", float(getattr(cfg, "PULLBACK_MIN_MOMENTUM_DECAY_RATIO", 0.52)))
    min_decay_ratio_short = cfg.get_symbol_param_float(symbol, "PULLBACK_MIN_MOMENTUM_DECAY_RATIO_SHORT", float(getattr(cfg, "PULLBACK_MIN_MOMENTUM_DECAY_RATIO_SHORT", 0.62)))
    recent_body_atr_min = cfg.get_symbol_param_float(symbol, "PULLBACK_RECENT_BODY_ATR_MIN", float(getattr(cfg, "PULLBACK_RECENT_BODY_ATR_MIN", 0.22)))
    recent_body_atr_min_short = cfg.get_symbol_param_float(symbol, "PULLBACK_RECENT_BODY_ATR_MIN_SHORT", float(getattr(cfg, "PULLBACK_RECENT_BODY_ATR_MIN_SHORT", 0.26)))

    body = abs(close - open_)
    rng = max(high - low, 0.0)
    prev_rng = max(prev_high - prev_low, 1e-9)
    if rng <= 0:
        return False, {"reason": "zero_range"}
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

    pull_recent = df.tail(min(len(df), max(12, pre_impulse_bars + 4))).copy()
    close_s = pull_recent["close"].astype(float)
    ema20_s = pull_recent["EMA20"].astype(float)
    ema50_s = pull_recent["EMA50"].astype(float)
    high_s = pull_recent["high"].astype(float)
    low_s = pull_recent["low"].astype(float)
    open_s = pull_recent["open"].astype(float)
    bar_range = (high_s - low_s).clip(lower=1e-9)
    wick_ratio_s = (((high_s - close_s.combine(open_s, max)) + (close_s.combine(open_s, min) - low_s)).clip(lower=0.0) / bar_range)
    avg_wick_ratio = float(wick_ratio_s.tail(min(5, len(wick_ratio_s))).mean()) if len(wick_ratio_s) else 1.0
    closes_rel = close_s.tail(min(8, len(close_s)))
    ema20_rel = ema20_s.tail(len(closes_rel))
    ema20_crosses = int((((closes_rel > ema20_rel).astype(int)).diff().abs() == 1).sum()) if len(closes_rel) > 1 else 0
    slope_lookback = min(6, len(ema20_s) - 1)
    ema20_slope_pct = abs(float(ema20_s.iloc[-1] - ema20_s.iloc[-1 - slope_lookback])) / max(abs(float(ema20_s.iloc[-1 - slope_lookback])), 1e-9) if slope_lookback >= 1 else 0.0
    ema50_slope_pct = abs(float(ema50_s.iloc[-1] - ema50_s.iloc[-1 - slope_lookback])) / max(abs(float(ema50_s.iloc[-1 - slope_lookback])), 1e-9) if slope_lookback >= 1 else 0.0
    leg_window = df.iloc[max(0, len(df) - (pre_impulse_bars + 3)):-1].copy()
    if len(leg_window) >= 3:
        leg_high = float(leg_window["high"].astype(float).max())
        leg_low = float(leg_window["low"].astype(float).min())
        pre_impulse_atr = (leg_high - leg_low) / max(atr_ltf, 1e-9)
    else:
        pre_impulse_atr = 0.0

    body_s = (close_s - open_s).abs()
    same_dir_series = close_s.diff().dropna()
    recent_impulse = leg_window.tail(min(len(leg_window), max(decay_lookback, 3))).copy() if len(leg_window) else leg_window.copy()
    if len(recent_impulse) >= max(decay_lookback, 3):
        recent_bodies = (recent_impulse["close"].astype(float) - recent_impulse["open"].astype(float)).abs() / max(atr_ltf, 1e-9)
        split = max(2, len(recent_bodies) // 2)
        older_mean = float(recent_bodies.iloc[:split].mean()) if split > 0 else 0.0
        newer_mean = float(recent_bodies.iloc[-split:].mean()) if split > 0 else 0.0
        momentum_decay_ratio = newer_mean / max(older_mean, 1e-9)
        recent_body_atr = newer_mean
    else:
        momentum_decay_ratio = 1.0
        recent_body_atr = 0.0

    if side == "long":
        touch20 = low <= ema20 + atr_ltf * touch_atr
        touch50 = low <= ema50 + atr_ltf * touch_atr
        touch_ok = touch20 or touch50
        not_too_deep = low >= ema50 - atr_ltf * deep_touch_atr
        reclaim_ok = close >= ema20 if reclaim_ema20 else close >= open_
        bullish_ok = close > open_ and close > prev_close and close_pos >= min_close_pos
        prev_counter_ok = (prev_close < prev_open and prev_close_pos <= prev_close_pos_max) if require_prev_counter else True
        rsi_ok = min_rsi_long <= rsi <= max_rsi_long
        slope_ok = ema20_slope_pct >= min_ema20_slope_pct and ema50_slope_pct >= min_ema50_slope_pct
        pre_impulse_ok = pre_impulse_atr >= pre_impulse_min_atr
        price_to_htf_ema20_pct = abs(close - htf_ema20) / max(abs(htf_ema20), 1e-9)
        trend_not_exhausted = price_to_htf_ema20_pct <= max_price_to_htf_ema20_pct
        same_dir_bars = int((same_dir_series > 0).sum()) if len(same_dir_series) else 0
        exhaustion_ok = same_dir_bars <= max_same_dir_bars
        decay_ok = momentum_decay_ratio >= min_decay_ratio and recent_body_atr >= recent_body_atr_min
    else:
        touch20 = high >= ema20 - atr_ltf * touch_atr
        touch50 = high >= ema50 - atr_ltf * touch_atr
        touch_ok = touch20 or touch50
        not_too_deep = high <= ema50 + atr_ltf * deep_touch_atr
        reclaim_ok = close <= ema20 if reclaim_ema20 else close <= open_
        bullish_ok = close < open_ and close < prev_close and close_pos >= min_close_pos
        prev_counter_ok = (prev_close > prev_open and prev_close_pos <= prev_close_pos_max) if require_prev_counter else True
        rsi_ok = min_rsi_short <= rsi <= max_rsi_short
        slope_ok = ema20_slope_pct >= min_ema20_slope_pct_short and ema50_slope_pct >= min_ema50_slope_pct_short
        pre_impulse_ok = pre_impulse_atr >= pre_impulse_min_atr_short
        price_to_htf_ema20_pct = abs(close - htf_ema20) / max(abs(htf_ema20), 1e-9)
        trend_not_exhausted = price_to_htf_ema20_pct <= max_price_to_htf_ema20_pct_short
        same_dir_bars = int((same_dir_series < 0).sum()) if len(same_dir_series) else 0
        exhaustion_ok = same_dir_bars <= max_same_dir_bars_short
        decay_ok = momentum_decay_ratio >= min_decay_ratio_short and recent_body_atr >= recent_body_atr_min_short

    clean_trend_ok = ema20_crosses <= max_ema20_crosses and avg_wick_ratio <= max_avg_wick_ratio
    continuation_ok = trend_not_exhausted and exhaustion_ok and decay_ok
    ok = bool(touch_ok and not_too_deep and reclaim_ok and bullish_ok and prev_counter_ok and body >= atr_ltf * min_body_atr and vol_ratio >= min_vol_ratio and htf_adx >= min_htf_adx and rsi_ok and slope_ok and pre_impulse_ok and clean_trend_ok and continuation_ok)
    return ok, {
        "touch20": touch20,
        "touch50": touch50,
        "touch_ok": touch_ok,
        "not_too_deep": not_too_deep,
        "reclaim_ok": reclaim_ok,
        "trigger_ok": bullish_ok,
        "prev_counter_ok": prev_counter_ok,
        "body": body,
        "atr": atr_ltf,
        "close_pos": close_pos,
        "prev_close_pos": prev_close_pos,
        "vol_ratio": vol_ratio,
        "rsi": rsi,
        "htf_adx": htf_adx,
        "ema20_crosses": ema20_crosses,
        "avg_wick_ratio": avg_wick_ratio,
        "ema20_slope_pct": ema20_slope_pct,
        "ema50_slope_pct": ema50_slope_pct,
        "pre_impulse_atr": pre_impulse_atr,
        "slope_ok": slope_ok,
        "pre_impulse_ok": pre_impulse_ok,
        "clean_trend_ok": clean_trend_ok,
        "side": side,
    }

def check_continuation_entry(symbol: str, df: pd.DataFrame, side: str, atr_ltf: float) -> tuple[bool, dict]:
    if len(df) < 120 or atr_ltf <= 0:
        return False, {"reason": "not_enough_continuation_history"}
    need_cols = {"EMA20", "EMA50", "EMA200", "open", "high", "low", "close", "volume", "RSI", "HTF_ADX", "HTF_EMA20"}
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
    soft_rejection = cfg.get_symbol_param_float(symbol, "CONTINUATION_SOFT_REJECTION", 0.0) > 0.5
    max_rsi_long = cfg.get_symbol_param_float(symbol, "CONTINUATION_RSI_LONG_MAX", float(getattr(cfg, "CONTINUATION_RSI_LONG_MAX", 63.0)))
    min_rsi_long = cfg.get_symbol_param_float(symbol, "CONTINUATION_RSI_LONG_MIN", float(getattr(cfg, "CONTINUATION_RSI_LONG_MIN", 48.0)))
    min_rsi_short = cfg.get_symbol_param_float(symbol, "CONTINUATION_RSI_SHORT_MIN", float(getattr(cfg, "CONTINUATION_RSI_SHORT_MIN", 37.0)))
    max_rsi_short = cfg.get_symbol_param_float(symbol, "CONTINUATION_RSI_SHORT_MAX", float(getattr(cfg, "CONTINUATION_RSI_SHORT_MAX", 52.0)))
    pullback_depth_atr = cfg.get_symbol_param_float(symbol, "CONTINUATION_PULLBACK_DEPTH_ATR", float(getattr(cfg, "CONTINUATION_PULLBACK_DEPTH_ATR", 0.9)))
    pre_impulse_bars = int(getattr(cfg, "PULLBACK_PRE_IMPULSE_BARS", 8))

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

    pull_recent = df.tail(min(len(df), max(12, pre_impulse_bars + 4))).copy()
    close_s = pull_recent["close"].astype(float)
    ema20_s = pull_recent["EMA20"].astype(float)
    ema50_s = pull_recent["EMA50"].astype(float)
    high_s = pull_recent["high"].astype(float)
    low_s = pull_recent["low"].astype(float)
    open_s = pull_recent["open"].astype(float)
    bar_range = (high_s - low_s).clip(lower=1e-9)
    wick_ratio_s = (((high_s - close_s.combine(open_s, max)) + (close_s.combine(open_s, min) - low_s)).clip(lower=0.0) / bar_range)
    avg_wick_ratio = float(wick_ratio_s.tail(min(5, len(wick_ratio_s))).mean()) if len(wick_ratio_s) else 1.0
    closes_rel = close_s.tail(min(8, len(close_s)))
    ema20_rel = ema20_s.tail(len(closes_rel))
    ema20_crosses = int((((closes_rel > ema20_rel).astype(int)).diff().abs() == 1).sum()) if len(closes_rel) > 1 else 0
    slope_lookback = min(6, len(ema20_s) - 1)
    ema20_slope_pct = abs(float(ema20_s.iloc[-1] - ema20_s.iloc[-1 - slope_lookback])) / max(abs(float(ema20_s.iloc[-1 - slope_lookback])), 1e-9) if slope_lookback >= 1 else 0.0
    ema50_slope_pct = abs(float(ema50_s.iloc[-1] - ema50_s.iloc[-1 - slope_lookback])) / max(abs(float(ema50_s.iloc[-1 - slope_lookback])), 1e-9) if slope_lookback >= 1 else 0.0
    leg_window = df.iloc[max(0, len(df) - (pre_impulse_bars + 3)):-1].copy()
    if len(leg_window) >= 3:
        leg_high = float(leg_window["high"].astype(float).max())
        leg_low = float(leg_window["low"].astype(float).min())
        pre_impulse_atr = (leg_high - leg_low) / max(atr_ltf, 1e-9)
    else:
        pre_impulse_atr = 0.0

    if side == "long":
        touch_ok = low <= ema20 + atr_ltf * touch_atr
        reclaim_ok = close >= ema20 and close > open_ and close > prev_close and close_pos >= close_pos_min
        prev_pullback_ok = (prev_low <= prev_ema20 + atr_ltf * touch_atr) or (prev_close <= prev_ema20 + atr_ltf * touch_atr)
        pullback_depth_ok = abs(min(prev_low, low) - ema20) <= atr_ltf * pullback_depth_atr
        rsi_ok = min_rsi_long <= rsi <= max_rsi_long
        if soft_rejection:
            rejection_ok = close > open_ and close > prev_close and close_pos >= max(0.50, close_pos_min - 0.06) and prev_close_pos <= 0.72
        else:
            rejection_ok = prev_close < prev_open and close > open_ and close > prev_open and close > prev_close and prev_close_pos <= 0.55
    else:
        touch_ok = high >= ema20 - atr_ltf * touch_atr
        reclaim_ok = close <= ema20 and close < open_ and close < prev_close and close_pos >= close_pos_min
        prev_pullback_ok = (prev_high >= prev_ema20 - atr_ltf * touch_atr) or (prev_close >= prev_ema20 - atr_ltf * touch_atr)
        pullback_depth_ok = abs(max(prev_high, high) - ema20) <= atr_ltf * pullback_depth_atr
        rsi_ok = min_rsi_short <= rsi <= max_rsi_short
        if soft_rejection:
            rejection_ok = close < open_ and close < prev_close and close_pos >= max(0.50, close_pos_min - 0.06) and prev_close_pos <= 0.72
        else:
            rejection_ok = prev_close > prev_open and close < open_ and close < prev_open and close < prev_close and prev_close_pos <= 0.55

    ok = (
        touch_ok
        and reclaim_ok
        and prev_pullback_ok if require_prev_pullback else touch_ok and reclaim_ok
    )
    prev_body_factor = 0.70 if soft_rejection else 0.85
    ok = bool(ok and pullback_depth_ok and rejection_ok and body >= atr_ltf * body_atr and rsi_ok and vol_ratio >= min_vol_ratio and htf_adx >= min_htf_adx and body >= prev_body * prev_body_factor)

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

def check_continuation_compression_entry(symbol: str, df: pd.DataFrame, side: str, atr_ltf: float) -> tuple[bool, dict]:
    if len(df) < 140 or atr_ltf <= 0:
        return False, {"reason": "not_enough_cont_comp_history"}
    need_cols = {"EMA20", "EMA50", "EMA200", "open", "high", "low", "close", "volume", "RSI", "ATR", "HTF_ADX"}
    if not need_cols.issubset(df.columns):
        return False, {"reason": "missing_cont_comp_cols"}
    try:
        last = df.iloc[-1]
        prev = df.iloc[-2]
        recent6 = df.iloc[-7:-1].copy()
        prev12 = df.iloc[-19:-7].copy()
        ema20 = float(last.get("EMA20", np.nan))
        ema50 = float(last.get("EMA50", np.nan))
        ema200 = float(last.get("EMA200", np.nan))
        close = float(last.get("close", np.nan))
        open_ = float(last.get("open", np.nan))
        high = float(last.get("high", np.nan))
        low = float(last.get("low", np.nan))
        prev_close = float(prev.get("close", np.nan))
        prev_open = float(prev.get("open", np.nan))
        prev_high = float(prev.get("high", np.nan))
        prev_low = float(prev.get("low", np.nan))
        rsi = float(last.get("RSI", np.nan))
        htf_adx = float(last.get("HTF_ADX", np.nan))
    except Exception:
        return False, {"reason": "bad_cont_comp_values"}
    vals = [ema20, ema50, ema200, close, open_, high, low, prev_close, prev_open, prev_high, prev_low, rsi, htf_adx]
    if any(np.isnan(x) for x in vals):
        return False, {"reason": "nan_cont_comp_values"}

    trend_ok = (ema20 > ema50 > ema200) if side == "long" else (ema20 < ema50 < ema200)
    if not trend_ok:
        return False, {"reason": "ltf_alignment_fail"}

    body = abs(close - open_)
    rng = max(high - low, 0.0)
    prev_rng = max(prev_high - prev_low, 1e-9)
    if rng <= 0:
        return False, {"reason": "zero_range"}

    try:
        comp_rng = float((recent6["high"].astype(float) - recent6["low"].astype(float)).mean())
        base_rng = float((prev12["high"].astype(float) - prev12["low"].astype(float)).mean())
        comp_atr = float(recent6["ATR"].astype(float).mean())
        base_atr = float(prev12["ATR"].astype(float).mean())
        vol_ema = float(df["volume"].astype(float).ewm(span=12, adjust=False).mean().iloc[-1])
        vol_ratio = float(last.get("volume", 0.0)) / max(vol_ema, 1e-9)
    except Exception:
        return False, {"reason": "cont_comp_calc_exception"}

    compression_ratio = comp_rng / max(base_rng, 1e-9)
    atr_compression_ratio = comp_atr / max(base_atr, 1e-9)
    max_compression_ratio = cfg.get_symbol_param_float(symbol, "CONT_COMP_MAX_COMPRESSION_RATIO", float(getattr(cfg, "CONT_COMP_MAX_COMPRESSION_RATIO", 0.82)))
    max_atr_comp_ratio = cfg.get_symbol_param_float(symbol, "CONT_COMP_MAX_ATR_RATIO", float(getattr(cfg, "CONT_COMP_MAX_ATR_RATIO", 0.90)))
    min_body_atr = cfg.get_symbol_param_float(symbol, "CONT_COMP_MIN_BODY_ATR", float(getattr(cfg, "CONT_COMP_MIN_BODY_ATR", 0.42)))
    min_range_atr = cfg.get_symbol_param_float(symbol, "CONT_COMP_MIN_RANGE_ATR", float(getattr(cfg, "CONT_COMP_MIN_RANGE_ATR", 0.80)))
    min_vol_ratio = cfg.get_symbol_param_float(symbol, "CONT_COMP_MIN_VOL_RATIO", float(getattr(cfg, "CONT_COMP_MIN_VOL_RATIO", 1.02)))
    min_htf_adx = cfg.get_symbol_param_float(symbol, "CONT_COMP_MIN_HTF_ADX", float(getattr(cfg, "CONT_COMP_MIN_HTF_ADX", 18.0)))
    pullback_touch_atr = cfg.get_symbol_param_float(symbol, "CONT_COMP_TOUCH_ATR", float(getattr(cfg, "CONT_COMP_TOUCH_ATR", 0.45)))
    break_prev_factor = cfg.get_symbol_param_float(symbol, "CONT_COMP_BREAK_PREV_FACTOR", float(getattr(cfg, "CONT_COMP_BREAK_PREV_FACTOR", 0.15)))
    close_pos = (close - low) / rng
    if side == "short":
        close_pos = 1.0 - close_pos

    if side == "long":
        touch_ok = min(low, prev_low) <= ema20 + atr_ltf * pullback_touch_atr
        expansion_ok = close > open_ and close > prev_high + atr_ltf * break_prev_factor and close_pos >= 0.60
        rsi_ok = 47.0 <= rsi <= cfg.get_symbol_param_float(symbol, "CONTINUATION_RSI_LONG_MAX", float(getattr(cfg, "CONTINUATION_RSI_LONG_MAX", 63.0))) + 4.0
    else:
        touch_ok = max(high, prev_high) >= ema20 - atr_ltf * pullback_touch_atr
        expansion_ok = close < open_ and close < prev_low - atr_ltf * break_prev_factor and close_pos >= 0.60
        rsi_ok = cfg.get_symbol_param_float(symbol, "CONTINUATION_RSI_SHORT_MIN", float(getattr(cfg, "CONTINUATION_RSI_SHORT_MIN", 37.0))) - 4.0 <= rsi <= 53.0

    ok = bool(
        compression_ratio <= max_compression_ratio
        and atr_compression_ratio <= max_atr_comp_ratio
        and touch_ok
        and expansion_ok
        and body >= atr_ltf * min_body_atr
        and rng >= atr_ltf * min_range_atr
        and vol_ratio >= min_vol_ratio
        and htf_adx >= min_htf_adx
        and rsi_ok
    )
    return ok, {
        "compression_ratio": compression_ratio,
        "atr_compression_ratio": atr_compression_ratio,
        "touch_ok": touch_ok,
        "expansion_ok": expansion_ok,
        "vol_ratio": vol_ratio,
        "htf_adx": htf_adx,
        "rsi": rsi,
        "body": body,
        "range": rng,
        "side": side,
    }

ACTIVE_TRADE_TYPE_PATHS = {
    "mean_reversion": "_check_v52_mean_reversion_entry",
    "fakeout": "_check_fakeout_reversal_entry",
    "range": "_range_signal",
    "btc_exhaustion": "_check_btc_exhaustion_short",
    "impulse": "_check_impulse_breakout",
    "continuation": "_check_continuation_entry",
    "cont_compression": "_check_continuation_compression_entry",
    "pullback": "_check_pullback_trend_entry",
}
