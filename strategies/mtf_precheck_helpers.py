import logging

import config as cfg
from .mtf_regime_helpers import check_htf_overextension, check_htf_trend_vitality

logger = logging.getLogger(__name__)


def run_market_regime_precheck(strategy, df, *, symbol: str, is_alt: bool, regime: str, close: float, atr_ltf: float, atr_h: float, adx_h: float, ema20_h: float, ema50_h: float):
    """Run the market/regime precheck block used at the top of signal().

    Returns a dict with either:
      - {"should_return": True, "result": None}
      - {"should_return": False, ...context values...}
    """
    if close <= 0 or atr_h <= 0:
        strategy._alt_trace("early_return", symbol=symbol, stage="htf_inputs", reason="non_positive_close_or_atr")
        return {"should_return": True, "result": None}

    atr_pct_h = atr_h / close
    strategy._last_atr_pct_h = atr_pct_h
    min_atr_pct = float(getattr(cfg, "ANTI_CHOP_MIN_ATR_PCT", 0.0005))
    if atr_pct_h < min_atr_pct:
        strategy._alt_trace("early_return", symbol=symbol, stage="htf_atr", reason="atr_below_min", atr_pct_h=round(atr_pct_h, 6), min_atr_pct=round(min_atr_pct, 6))
        return {"should_return": True, "result": None}

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
        if is_alt and bool(getattr(cfg, "ALT_DISABLE_HTF_VOLATILE_DRIFTLESS_FILTER", True)):
            strategy._alt_trace("soft_pass", symbol=symbol, stage="htf_noise", reason="alt_disable_volatile_driftless_htf", atr_pct_h=round(atr_pct_h, 6), drift_h=round(drift_h, 6), adx_h=round(adx_h, 6))
        else:
            logger.debug("[MTF] skip volatile driftless HTF regime")
            strategy._alt_trace("early_return", symbol=symbol, stage="htf_noise", reason="volatile_driftless_htf", atr_pct_h=round(atr_pct_h, 6), drift_h=round(drift_h, 6), adx_h=round(adx_h, 6))
            return {"should_return": True, "result": None}

    super_high_atr_pct = float(getattr(cfg, "MTF_ATR_SUPER_HIGH_PCT", 0.02))

    htf_vitality_enabled = bool(getattr(cfg, "HTF_TREND_VITALITY_ENABLED", True))
    if htf_vitality_enabled and regime != "none":
        vitality_ok, vitality_meta = check_htf_trend_vitality(cfg=cfg, df=df, regime=regime, close=close)
    else:
        vitality_ok, vitality_meta = True, {}

    htf_overextension_enabled = bool(getattr(cfg, "HTF_OVEREXTENSION_FILTER_ENABLED", True))
    if htf_overextension_enabled and regime != "none":
        overext_ok, overext_meta = check_htf_overextension(cfg=cfg, close=close, ema20_h=ema20_h, ema50_h=ema50_h, atr_h=atr_h, regime=regime)
    else:
        overext_ok, overext_meta = True, {}

    base_recent = df.iloc[-min(max(24, int(getattr(cfg, "RANGE_LOOKBACK", 48))), len(df)):]
    market_state, market_meta = strategy._classify_market_state(
        symbol=symbol,
        recent=base_recent,
        close=close,
        atr_ltf=atr_ltf,
        atr_h=atr_h,
        adx_h=adx_h,
        drift=drift,
        regime=regime,
    )
    strategy._alt_trace("setup_context", symbol=symbol, market_state=market_state, regime=regime, drift=round(drift, 6), atr_pct_h=round(atr_pct_h, 6), atr_ltf=round(atr_ltf, 6))

    if getattr(cfg, "MTF_DISABLE_VOLATILE_FLAT", True) and atr_pct_h > super_high_atr_pct and market_state != "range":
        logger.debug(
            "[MTF] skip super-high ATR non-range state: atr_pct_h=%.5f > super_high_atr_pct=%.5f",
            atr_pct_h,
            super_high_atr_pct,
        )
        return {"should_return": True, "result": None}

    transition_state = False
    if market_state == "panic":
        logger.debug("[MTF] skip panic market state: %s", market_meta)
        strategy._alt_trace("early_return", symbol=symbol, stage="market_state", reason="panic", market_state=market_state)
        return {"should_return": True, "result": None}
    if market_state == "transition":
        transition_state = True
        logger.debug("[MTF] transition market state: %s", market_meta)

    if market_state == "trend":
        if regime == "none":
            strategy._alt_trace("early_return", symbol=symbol, stage="trend_regime", reason="regime_none")
            return {"should_return": True, "result": None}
        if not vitality_ok:
            logger.debug("[MTF] skip flat HTF trend: %s", vitality_meta)
            return {"should_return": True, "result": None}
        if not overext_ok:
            logger.debug("[MTF] skip overheated HTF move: %s", overext_meta)
            return {"should_return": True, "result": None}

        if bool(cfg.get_symbol_param(symbol, "MARKET_REGIME_FILTER_ENABLED", getattr(cfg, "MARKET_REGIME_FILTER_ENABLED", True))):
            require_trend_state = bool(cfg.get_symbol_param(symbol, "MARKET_REGIME_REQUIRE_TREND_STATE", getattr(cfg, "MARKET_REGIME_REQUIRE_TREND_STATE", True)))
            min_regime_adx = float(cfg.get_symbol_param_float(symbol, "MARKET_REGIME_MIN_HTF_ADX", float(getattr(cfg, "MARKET_REGIME_MIN_HTF_ADX", 18.0))))
            min_regime_atr_pct = float(cfg.get_symbol_param_float(symbol, "MARKET_REGIME_MIN_HTF_ATR_PCT", float(getattr(cfg, "MARKET_REGIME_MIN_HTF_ATR_PCT", 0.0012))))
            min_regime_drift = float(cfg.get_symbol_param_float(symbol, "MARKET_REGIME_MIN_DRIFT_PCT", float(getattr(cfg, "MARKET_REGIME_MIN_DRIFT_PCT", drift_min_pct))))
            if require_trend_state and market_state != "trend":
                logger.debug("[MTF] skip non-trend market_state by regime filter: %s", market_state)
                strategy._alt_trace("early_return", symbol=symbol, stage="regime_strength", reason="weak_regime", adx_h=round(adx_h, 6), atr_pct_h=round(atr_pct_h, 6), drift=round(drift, 6))
                return {"should_return": True, "result": None}
            if adx_h < min_regime_adx or atr_pct_h < min_regime_atr_pct or drift < min_regime_drift:
                logger.debug(
                    "[MTF] skip weak regime: adx_h=%.2f atr_pct_h=%.5f drift=%.5f thresholds=(%.2f, %.5f, %.5f)",
                    adx_h, atr_pct_h, drift, min_regime_adx, min_regime_atr_pct, min_regime_drift
                )
                return {"should_return": True, "result": None}

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
            return {"should_return": True, "result": None}

    return {
        "should_return": False,
        "atr_pct_h": atr_pct_h,
        "min_atr_pct": min_atr_pct,
        "drift": drift,
        "drift_h": drift_h,
        "drift_min_pct": drift_min_pct,
        "drift_strong_pct": drift_strong_pct,
        "market_state": market_state,
        "market_meta": market_meta,
        "transition_state": transition_state,
        "vitality_ok": vitality_ok,
        "vitality_meta": vitality_meta,
        "overext_ok": overext_ok,
        "overext_meta": overext_meta,
        "super_high_atr_pct": super_high_atr_pct,
        "htf_volatile_atr": htf_volatile_atr,
    }
