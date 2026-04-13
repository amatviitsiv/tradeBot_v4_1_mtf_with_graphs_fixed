import pandas as pd


def is_mean_reversion_symbol(*, cfg, symbol: str) -> bool:
    symbols = set(getattr(cfg, "V52_MR_SYMBOLS", ["BTCUSDT", "ETHUSDT"]) or [])
    return bool(symbol and symbol in symbols)


def mr_risk_multiplier(*, cfg, symbol: str) -> float:
    if symbol == "ETHUSDT":
        return float(getattr(cfg, "V54_ETH_MR_RISK_MULTIPLIER", 0.15))
    core = set(getattr(cfg, "V52_MR_CORE_SYMBOLS", ["BTCUSDT", "ETHUSDT"]) or [])
    if symbol in core:
        return float(getattr(cfg, "V54_MR_RISK_MULTIPLIER_CORE", 0.45))
    return float(getattr(cfg, "V54_MR_RISK_MULTIPLIER_ALT", 0.35))


def check_v52_mean_reversion_entry(*, cfg, symbol: str, market_state: str, recent: pd.DataFrame, candle: pd.Series, atr_ltf: float) -> tuple[str | None, dict]:
    if not bool(getattr(cfg, "V52_MEAN_REVERSION_ENABLED", True)):
        return None, {"reason": "disabled"}
    if not is_mean_reversion_symbol(cfg=cfg, symbol=symbol):
        return None, {"reason": "symbol_not_enabled"}

    core = set(getattr(cfg, "V52_MR_CORE_SYMBOLS", ["BTCUSDT", "ETHUSDT"]) or [])
    is_core = symbol in core
    if is_core:
        allow_states = set(getattr(cfg, "V52_MR_ALLOWED_STATES", ["range", "transition"]) or ["range"])
    else:
        allow_states = set(getattr(cfg, "V52_MR_ALLOWED_STATES", ["range", "transition"]) or ["range", "transition"])
    if market_state not in allow_states:
        return None, {"reason": "market_state_not_allowed", "market_state": market_state}
    if atr_ltf <= 0 or recent is None or len(recent) < 20:
        return None, {"reason": "not_enough_data"}

    def _f(name: str, default: float = 0.0) -> float:
        try:
            return float(candle.get(name, default))
        except Exception:
            return float(default)

    open_ = _f("open", float("nan"))
    high = _f("high", float("nan"))
    low = _f("low", float("nan"))
    close = _f("close", float("nan"))
    ema20 = _f("EMA20", float("nan"))
    rsi = _f("RSI", float("nan"))
    volume = _f("volume", float("nan"))
    adx_ltf = _f("ADX", float("nan"))
    adx_htf = _f("HTF_ADX", float("nan"))
    htf_ema20 = _f("HTF_EMA20", float("nan"))
    htf_ema50 = _f("HTF_EMA50", float("nan"))
    htf_rsi = _f("HTF_RSI", float("nan"))
    vals = [open_, high, low, close, ema20, rsi, volume, adx_ltf, adx_htf, htf_ema20, htf_ema50, htf_rsi]
    if any(pd.isna(v) for v in vals) or close <= 0:
        return None, {"reason": "nan_values"}

    z_window = int(getattr(cfg, "V52_MR_Z_WINDOW", 20))
    bb_mult = float(getattr(cfg, "V52_MR_BB_STD", 2.0))
    closes = recent["close"].astype(float).tail(max(z_window, 20))
    vols = recent["volume"].astype(float).tail(12) if "volume" in recent.columns else pd.Series(dtype=float)
    ma = float(closes.mean()) if len(closes) else close
    std = float(closes.std(ddof=0)) if len(closes) else 0.0
    if std <= 1e-9:
        return None, {"reason": "std_too_low"}
    zscore = (close - ma) / std
    bb_lower = ma - bb_mult * std
    bb_upper = ma + bb_mult * std
    dev_atr = (close - ema20) / atr_ltf
    candle_range = max(high - low, 1e-9)
    close_pos = (close - low) / candle_range
    upper_wick_ratio = max(0.0, high - max(open_, close)) / candle_range
    lower_wick_ratio = max(0.0, min(open_, close) - low) / candle_range
    vol_ma = float(vols.mean()) if len(vols) else volume
    vol_ratio = (volume / vol_ma) if vol_ma > 0 else 1.0
    htf_spread_pct = abs(htf_ema20 - htf_ema50) / close

    max_htf_adx = float(getattr(cfg, "V52_MR_MAX_HTF_ADX", 20.0 if is_core else 22.0))
    max_ltf_adx = float(getattr(cfg, "V52_MR_MAX_LTF_ADX", 24.0 if is_core else 26.0))
    max_htf_spread = float(getattr(cfg, "V52_MR_MAX_HTF_EMA_SPREAD_PCT", 0.008 if is_core else 0.012))
    htf_rsi_min = float(getattr(cfg, "V52_MR_HTF_RSI_MIN", 42.0))
    htf_rsi_max = float(getattr(cfg, "V52_MR_HTF_RSI_MAX", 58.0))
    if adx_htf > max_htf_adx or adx_ltf > max_ltf_adx:
        return None, {"reason": "adx_too_high", "adx_htf": adx_htf, "adx_ltf": adx_ltf}
    if htf_spread_pct > max_htf_spread:
        return None, {"reason": "htf_spread_too_wide", "htf_spread_pct": htf_spread_pct}
    if not (htf_rsi_min <= htf_rsi <= htf_rsi_max):
        return None, {"reason": "htf_rsi_not_neutral", "htf_rsi": htf_rsi}

    long_rsi_max = float(getattr(cfg, "V52_MR_RSI_LONG_MAX", 34.0 if is_core else 36.0))
    short_rsi_min = float(getattr(cfg, "V52_MR_RSI_SHORT_MIN", 66.0 if is_core else 64.0))
    z_thresh = float(getattr(cfg, "V52_MR_Z_THRESHOLD", 1.8 if is_core else 1.6))
    dev_thresh = float(getattr(cfg, "V52_MR_DEV_ATR_THRESHOLD", 1.4 if is_core else 1.2))
    min_vol_ratio = float(getattr(cfg, "V52_MR_MIN_VOL_RATIO", 0.85))
    min_close_pos_long = float(getattr(cfg, "V52_MR_MIN_CLOSE_POS_LONG", 0.50))
    max_close_pos_short = float(getattr(cfg, "V52_MR_MAX_CLOSE_POS_SHORT", 0.50))
    min_reject_wick = float(getattr(cfg, "V52_MR_MIN_REJECTION_WICK", 0.10))
    allow_short_core = bool(getattr(cfg, "V52_MR_ALLOW_SHORT_CORE", False))
    allow_short_alt = bool(getattr(cfg, "V52_MR_ALLOW_SHORT_ALT", False))
    allow_short = allow_short_core if is_core else allow_short_alt

    long_extreme = (zscore <= -z_thresh and (close <= bb_lower or dev_atr <= -dev_thresh))
    short_extreme = (zscore >= z_thresh and (close >= bb_upper or dev_atr >= dev_thresh))
    long_reversal = close_pos >= min_close_pos_long or lower_wick_ratio >= min_reject_wick
    short_reversal = close_pos <= max_close_pos_short or upper_wick_ratio >= min_reject_wick
    long_ok = long_extreme and rsi <= long_rsi_max and vol_ratio >= min_vol_ratio and long_reversal
    short_ok = allow_short and short_extreme and rsi >= short_rsi_min and vol_ratio >= min_vol_ratio and short_reversal

    meta = {
        "market_state": market_state,
        "zscore": zscore,
        "bb_lower": bb_lower,
        "bb_upper": bb_upper,
        "dev_atr": dev_atr,
        "rsi": rsi,
        "vol_ratio": vol_ratio,
        "adx_ltf": adx_ltf,
        "adx_htf": adx_htf,
        "htf_rsi": htf_rsi,
        "htf_spread_pct": htf_spread_pct,
        "is_core": is_core,
    }
    if long_ok:
        return "buy", {**meta, "reason": "controlled_mean_reversion_long"}
    if short_ok:
        return "sell", {**meta, "reason": "controlled_mean_reversion_short"}
    return None, {**meta, "reason": "no_controlled_mr_setup"}
