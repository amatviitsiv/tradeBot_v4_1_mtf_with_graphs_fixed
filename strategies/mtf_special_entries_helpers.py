from typing import Optional

import numpy as np
import pandas as pd

import config as cfg


def check_fakeout_reversal_entry(symbol: str, df: pd.DataFrame, recent: pd.DataFrame, side: str, range_high: float, range_low: float, atr_ltf: float, adx_h: float) -> tuple[bool, dict]:
    if len(df) < 60 or len(recent) < 20 or atr_ltf <= 0:
        return False, {"reason": "not_enough_fakeout_history"}
    try:
        last = df.iloc[-1]
        prev = df.iloc[-2]
        open_ = float(last.get("open", np.nan))
        high = float(last.get("high", np.nan))
        low = float(last.get("low", np.nan))
        close = float(last.get("close", np.nan))
        prev_open = float(prev.get("open", np.nan))
        prev_high = float(prev.get("high", np.nan))
        prev_low = float(prev.get("low", np.nan))
        prev_close = float(prev.get("close", np.nan))
        rsi = float(last.get("RSI", np.nan))
        volume = float(last.get("volume", 0.0))
        vol_ema = float(df["volume"].astype(float).ewm(span=12, adjust=False).mean().iloc[-1])
    except Exception:
        return False, {"reason": "bad_fakeout_values"}
    vals = [open_, high, low, close, prev_open, prev_high, prev_low, prev_close, rsi, volume, vol_ema, adx_h]
    if any(np.isnan(x) for x in vals):
        return False, {"reason": "nan_fakeout_values"}

    rng = max(high - low, 1e-9)
    body = abs(close - open_)
    close_pos = (close - low) / rng
    wick_break = 0.0
    pierced = False
    reclaimed = False
    rejection_ok = False
    rsi_ok = False
    fakeout_buf = cfg.get_symbol_param_float(symbol, "FAKEOUT_PIERCE_ATR", float(getattr(cfg, "FAKEOUT_PIERCE_ATR", 0.16)))
    min_body_atr = cfg.get_symbol_param_float(symbol, "FAKEOUT_MIN_BODY_ATR", float(getattr(cfg, "FAKEOUT_MIN_BODY_ATR", 0.28)))
    min_vol_ratio = cfg.get_symbol_param_float(symbol, "FAKEOUT_MIN_VOL_RATIO", float(getattr(cfg, "FAKEOUT_MIN_VOL_RATIO", 0.90)))
    max_adx = cfg.get_symbol_param_float(symbol, "FAKEOUT_MAX_ADX", float(getattr(cfg, "FAKEOUT_MAX_ADX", 24.0)))
    rsi_long_max = cfg.get_symbol_param_float(symbol, "FAKEOUT_RSI_LONG_MAX", float(getattr(cfg, "FAKEOUT_RSI_LONG_MAX", 32.0)))
    rsi_short_min = cfg.get_symbol_param_float(symbol, "FAKEOUT_RSI_SHORT_MIN", float(getattr(cfg, "FAKEOUT_RSI_SHORT_MIN", 68.0)))

    if side == "long":
        pierced = min(low, prev_low) <= range_low - atr_ltf * fakeout_buf
        reclaimed = close >= range_low and prev_close <= range_low + atr_ltf * 0.10
        rejection_ok = close > open_ and close_pos >= 0.62 and (range_low - low) >= body * 0.8
        rsi_ok = rsi <= rsi_long_max
        wick_break = max(0.0, range_low - low)
    else:
        close_pos = 1.0 - close_pos
        pierced = max(high, prev_high) >= range_high + atr_ltf * fakeout_buf
        reclaimed = close <= range_high and prev_close >= range_high - atr_ltf * 0.10
        rejection_ok = close < open_ and close_pos >= 0.62 and (high - range_high) >= body * 0.8
        rsi_ok = rsi >= rsi_short_min
        wick_break = max(0.0, high - range_high)

    vol_ratio = volume / max(vol_ema, 1e-9)
    ok = bool(
        pierced and reclaimed and rejection_ok and rsi_ok
        and body >= atr_ltf * min_body_atr
        and vol_ratio >= min_vol_ratio
        and adx_h <= max_adx
    )
    return ok, {
        "pierced": pierced,
        "reclaimed": reclaimed,
        "rejection_ok": rejection_ok,
        "rsi_ok": rsi_ok,
        "vol_ratio": vol_ratio,
        "adx_h": adx_h,
        "body": body,
        "wick_break": wick_break,
        "side": side,
    }


def check_btc_exhaustion_short(symbol: str, df: pd.DataFrame, recent: pd.DataFrame, atr_ltf: float, adx_h: float, rsi_h: float, ema20_h: float, ema50_h: float, regime: str) -> tuple[bool, dict]:
    btc_symbol = str(getattr(cfg, "BTC_REGIME_FILTER_SYMBOL", "BTCUSDT"))
    if symbol != btc_symbol:
        return False, {"reason": "not_btc"}
    if not bool(cfg.get_symbol_param(symbol, "ENABLE_BTC_EXHAUSTION_SHORT", getattr(cfg, "ENABLE_BTC_EXHAUSTION_SHORT", True))):
        return False, {"reason": "btc_exhaustion_disabled"}
    if atr_ltf <= 0 or len(df) < 3 or len(recent) < 10:
        return False, {"reason": "btc_exhaustion_history"}
    try:
        last = df.iloc[-1]
        prev = df.iloc[-2]
        open_ = float(last.get("open", np.nan))
        high = float(last.get("high", np.nan))
        low = float(last.get("low", np.nan))
        close = float(last.get("close", np.nan))
        prev_close = float(prev.get("close", np.nan))
        rsi_ltf = float(last.get("RSI", np.nan))
    except Exception:
        return False, {"reason": "btc_exhaustion_parse"}
    vals = [open_, high, low, close, prev_close, rsi_ltf, ema20_h, ema50_h, adx_h, rsi_h]
    if any(np.isnan(v) for v in vals):
        return False, {"reason": "btc_exhaustion_nan"}

    min_stretch_atr = cfg.get_symbol_param_float(symbol, "BTC_EXHAUSTION_MIN_STRETCH_ATR", float(getattr(cfg, "BTC_EXHAUSTION_MIN_STRETCH_ATR", 1.20)))
    min_rsi = cfg.get_symbol_param_float(symbol, "BTC_EXHAUSTION_MIN_RSI", float(getattr(cfg, "BTC_EXHAUSTION_MIN_RSI", 64.0)))
    min_htf_adx = cfg.get_symbol_param_float(symbol, "BTC_EXHAUSTION_MIN_HTF_ADX", float(getattr(cfg, "BTC_EXHAUSTION_MIN_HTF_ADX", 14.0)))
    max_htf_rsi = cfg.get_symbol_param_float(symbol, "BTC_EXHAUSTION_MAX_HTF_RSI", float(getattr(cfg, "BTC_EXHAUSTION_MAX_HTF_RSI", 60.0)))
    min_upper_wick_body = cfg.get_symbol_param_float(symbol, "BTC_EXHAUSTION_MIN_UPPER_WICK_BODY", float(getattr(cfg, "BTC_EXHAUSTION_MIN_UPPER_WICK_BODY", 0.70)))
    min_close_from_high = cfg.get_symbol_param_float(symbol, "BTC_EXHAUSTION_MIN_CLOSE_POS_FROM_HIGH", float(getattr(cfg, "BTC_EXHAUSTION_MIN_CLOSE_POS_FROM_HIGH", 0.55)))

    recent_close = recent["close"].astype(float)
    mean_price = float(recent_close.ewm(span=20, adjust=False).mean().iloc[-1])
    stretch_atr = (close - mean_price) / atr_ltf
    htf_bias_ok = bool(close >= ema20_h or close >= ema50_h)
    body = abs(close - open_)
    upper_wick = max(high - max(open_, close), 0.0)
    candle_range = max(high - low, 1e-9)
    close_from_high = (high - close) / candle_range
    bearish_rejection = bool(close < open_ and close < prev_close)
    wick_ok = upper_wick >= max(min_upper_wick_body * max(body, 1e-9), 0.18 * atr_ltf)
    context_ok = bool(regime in {"bear", "none"} and adx_h >= min_htf_adx and rsi_h <= max_htf_rsi)
    overextended = bool(stretch_atr >= min_stretch_atr and rsi_ltf >= min_rsi and htf_bias_ok)
    ok = bool(context_ok and overextended and bearish_rejection and wick_ok and close_from_high >= min_close_from_high)
    return ok, {
        "reason": "btc_exhaustion_short",
        "stretch_atr": stretch_atr,
        "rsi_ltf": rsi_ltf,
        "adx_h": adx_h,
        "rsi_h": rsi_h,
        "close_from_high": close_from_high,
        "upper_wick": upper_wick,
        "body": body,
        "mean_price": mean_price,
        "context_ok": context_ok,
        "overextended": overextended,
    }


def range_signal(symbol: str, df: pd.DataFrame, recent: pd.DataFrame, close: float, atr_ltf: float, adx_h: float, market_meta: dict) -> tuple[Optional[str], dict]:
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
        "stretch_atr": stretch_atr,
        "state": market_meta,
        "state_ok": state_ok,
    }
