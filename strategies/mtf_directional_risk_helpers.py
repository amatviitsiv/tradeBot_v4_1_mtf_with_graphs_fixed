import config as cfg


def _apply_v7_direct_boost(self, symbol: str, side: str, trade_type: str, base_risk_multiplier: float, adx_h: float, drift: float, volume_meta: dict | None = None, strong_setup: bool = False, regime_gate_meta: dict | None = None) -> tuple[float, dict]:
    flags = {"v7_direct_boost_applied": False}
    risk_mult = float(base_risk_multiplier)
    if not bool(getattr(cfg, "V7_DIRECT_BOOST_ENABLED", True)):
        return risk_mult, flags
    allowed_symbols = set(getattr(cfg, "V7_DIRECT_BOOST_SYMBOLS", ["BTCUSDT"]) or ["BTCUSDT"])
    if symbol not in allowed_symbols:
        return risk_mult, flags
    allowed_types = {str(v).lower() for v in (getattr(cfg, "V7_DIRECT_BOOST_ALLOWED_TYPES", ["impulse", "continuation"]) or ["impulse", "continuation"])}
    if str(trade_type or "").lower() not in allowed_types:
        return risk_mult, flags
    required_side = str(getattr(cfg, "V7_DIRECT_BOOST_SIDE", "long") or "long").lower()
    if str(side or "").lower() != required_side:
        return risk_mult, flags
    min_adx = float(cfg.get_symbol_param_float(symbol, "V7_DIRECT_BOOST_MIN_ADX", float(getattr(cfg, "V7_DIRECT_BOOST_MIN_ADX", 24.0))))
    min_drift = float(cfg.get_symbol_param_float(symbol, "V7_DIRECT_BOOST_MIN_DRIFT_PCT", float(getattr(cfg, "V7_DIRECT_BOOST_MIN_DRIFT_PCT", 0.0060))))
    min_impulse = float(cfg.get_symbol_param_float(symbol, "V7_DIRECT_BOOST_MIN_IMPULSE", float(getattr(cfg, "V7_DIRECT_BOOST_MIN_IMPULSE", 0.75))))
    impulse_score = float((volume_meta or {}).get("impulse_score", 0.0) or 0.0)
    if float(adx_h) < min_adx or float(drift) < min_drift or impulse_score < min_impulse:
        flags.update({
            "v7_direct_boost_reason": "threshold_not_met",
            "v7_direct_boost_min_adx": min_adx,
            "v7_direct_boost_min_drift_pct": min_drift,
            "v7_direct_boost_min_impulse": min_impulse,
        })
        return risk_mult, flags
    require_strong_setup = bool(getattr(cfg, "V7_DIRECT_BOOST_REQUIRES_STRONG_SETUP", True))
    if require_strong_setup and not bool(strong_setup):
        flags["v7_direct_boost_reason"] = "strong_setup_required"
        return risk_mult, flags
    boost = float(cfg.get_symbol_param_float(symbol, "V7_DIRECT_BOOST_MULT", float(getattr(cfg, "V7_DIRECT_BOOST_MULT", 1.45))))
    risk_mult *= boost
    flags.update({
        "v7_direct_boost_applied": True,
        "v7_direct_boost_mult": boost,
        "v7_direct_boost_adx_h": float(adx_h),
        "v7_direct_boost_drift": float(drift),
        "v7_direct_boost_impulse_score": impulse_score,
        "v7_direct_boost_strong_setup": bool(strong_setup),
    })
    return risk_mult, flags


def _apply_v78_selective_risk_reduction(self, symbol: str, side: str, trade_type: str, base_risk_multiplier: float, market_state: str = "", regime: str = "", regime_gate_meta: dict | None = None, trend_quality_meta: dict | None = None, volume_meta: dict | None = None, strong_setup: bool = False, v7_flags: dict | None = None) -> tuple[float, dict]:
    flags = {"v78_risk_reduction_applied": False}
    risk_mult = float(base_risk_multiplier)
    if not bool(getattr(cfg, "V78_SELECTIVE_RISK_ENABLED", True)):
        return risk_mult, flags
    allowed_symbols = set(getattr(cfg, "V78_SELECTIVE_RISK_SYMBOLS", ["BTCUSDT"]) or ["BTCUSDT"])
    if symbol not in allowed_symbols:
        return risk_mult, flags
    allowed_types = {str(v).lower() for v in (getattr(cfg, "V78_SELECTIVE_RISK_ALLOWED_TYPES", ["impulse", "continuation", "cont_compression"]) or ["impulse", "continuation", "cont_compression"])}
    trade_type = str(trade_type or "").lower()
    if trade_type not in allowed_types:
        return risk_mult, flags
    required_side = str(getattr(cfg, "V78_SELECTIVE_RISK_SIDE", "long") or "long").lower()
    if str(side or "").lower() != required_side:
        return risk_mult, flags

    regime_gate_meta = regime_gate_meta or {}
    trend_quality_meta = trend_quality_meta or {}
    volume_meta = volume_meta or {}
    v7_flags = v7_flags or {}

    impulse_score = float(volume_meta.get("impulse_score", 0.0) or 0.0)
    gate_reason = str(regime_gate_meta.get("reason", "") or "").lower()
    ema20_crosses = int(trend_quality_meta.get("ema20_crosses", 0) or 0)
    mean_wickiness = float(trend_quality_meta.get("mean_wickiness", 0.0) or 0.0)
    mean_body_ratio = float(trend_quality_meta.get("mean_body_ratio", 1.0) or 1.0)
    ema20_slope_pct = float(trend_quality_meta.get("ema20_slope_pct", 0.0) or 0.0)
    ema50_slope_pct = float(trend_quality_meta.get("ema50_slope_pct", 0.0) or 0.0)
    v7_applied = bool((v7_flags or {}).get("v7_direct_boost_applied", False))

    mild_hits: list[str] = []
    severe_hits: list[str] = []

    if str(market_state or "") in set(getattr(cfg, "V78_SEVERE_MARKET_STATES", ["chop", "range", "flat"]) or ["chop", "range", "flat"]):
        severe_hits.append(f"market_state:{market_state}")
    elif str(market_state or "") in set(getattr(cfg, "V78_MILD_MARKET_STATES", ["transition"]) or ["transition"]):
        mild_hits.append(f"market_state:{market_state}")

    if str(regime or "") in set(getattr(cfg, "V78_SEVERE_REGIMES", ["bear"]) or ["bear"]):
        severe_hits.append(f"regime:{regime}")
    elif str(regime or "") in set(getattr(cfg, "V78_MILD_REGIMES", []) or []):
        mild_hits.append(f"regime:{regime}")

    severe_gate_parts = [str(v).lower() for v in (getattr(cfg, "V78_SEVERE_GATE_FRAGMENTS", ["transition_guard_failed", "transition_rsi_guard_failed", "non_directional_market_state", "regime_mismatch"]) or [])]
    mild_gate_parts = [str(v).lower() for v in (getattr(cfg, "V78_MILD_GATE_FRAGMENTS", ["trend_not_clean", "trend_quality", "chop"]) or [])]
    if gate_reason:
        if any(part and part in gate_reason for part in severe_gate_parts):
            severe_hits.append(f"gate:{gate_reason}")
        elif any(part and part in gate_reason for part in mild_gate_parts):
            mild_hits.append(f"gate:{gate_reason}")

    if ema20_crosses >= int(getattr(cfg, "V78_SEVERE_MIN_EMA20_CROSSES", 3)):
        severe_hits.append(f"ema20_crosses:{ema20_crosses}")
    elif ema20_crosses >= int(getattr(cfg, "V78_MILD_MIN_EMA20_CROSSES", 2)):
        mild_hits.append(f"ema20_crosses:{ema20_crosses}")

    if mean_wickiness >= float(getattr(cfg, "V78_SEVERE_MIN_WICKINESS", 0.58)):
        severe_hits.append(f"wickiness:{mean_wickiness:.3f}")
    elif mean_wickiness >= float(getattr(cfg, "V78_MILD_MIN_WICKINESS", 0.50)):
        mild_hits.append(f"wickiness:{mean_wickiness:.3f}")

    if mean_body_ratio <= float(getattr(cfg, "V78_SEVERE_MAX_BODY_RATIO", 0.30)):
        severe_hits.append(f"body_ratio:{mean_body_ratio:.3f}")
    elif mean_body_ratio <= float(getattr(cfg, "V78_MILD_MAX_BODY_RATIO", 0.38)):
        mild_hits.append(f"body_ratio:{mean_body_ratio:.3f}")

    if ema20_slope_pct <= float(getattr(cfg, "V78_SEVERE_MAX_EMA20_SLOPE_PCT", 0.0025)) or ema50_slope_pct <= float(getattr(cfg, "V78_SEVERE_MAX_EMA50_SLOPE_PCT", 0.0012)):
        severe_hits.append(f"slopes:{ema20_slope_pct:.4f}/{ema50_slope_pct:.4f}")
    elif ema20_slope_pct <= float(getattr(cfg, "V78_MILD_MAX_EMA20_SLOPE_PCT", 0.0036)) or ema50_slope_pct <= float(getattr(cfg, "V78_MILD_MAX_EMA50_SLOPE_PCT", 0.0018)):
        mild_hits.append(f"slopes:{ema20_slope_pct:.4f}/{ema50_slope_pct:.4f}")

    if trade_type == "impulse" and impulse_score <= float(getattr(cfg, "V78_MILD_MAX_IMPULSE_SCORE", 0.95)):
        mild_hits.append(f"impulse_score:{impulse_score:.3f}")

    if v7_applied and not bool(strong_setup) and bool(getattr(cfg, "V78_EXTRA_HAIRCUT_IF_BOOST_WITHOUT_STRONG_SETUP", True)):
        severe_hits.append("boost_without_strong_setup")

    mild_mult = float(cfg.get_symbol_param_float(symbol, "V78_RISK_MILD_MULT", float(getattr(cfg, "V78_RISK_MILD_MULT", 0.90))))
    severe_mult = float(cfg.get_symbol_param_float(symbol, "V78_RISK_SEVERE_MULT", float(getattr(cfg, "V78_RISK_SEVERE_MULT", 0.78))))
    strong_setup_mild_mult = float(cfg.get_symbol_param_float(symbol, "V78_STRONG_SETUP_MILD_MULT", float(getattr(cfg, "V78_STRONG_SETUP_MILD_MULT", 0.96))))
    strong_setup_severe_mult = float(cfg.get_symbol_param_float(symbol, "V78_STRONG_SETUP_SEVERE_MULT", float(getattr(cfg, "V78_STRONG_SETUP_SEVERE_MULT", 0.88))))

    if severe_hits:
        mult = strong_setup_severe_mult if bool(strong_setup) else severe_mult
        risk_mult *= mult
        flags.update({
            "v78_risk_reduction_applied": True,
            "v78_risk_reduction_level": "severe_strong_setup" if bool(strong_setup) else "severe",
            "v78_risk_reduction_mult": mult,
            "v78_risk_reduction_reason": severe_hits,
        })
    elif mild_hits:
        mult = strong_setup_mild_mult if bool(strong_setup) else mild_mult
        risk_mult *= mult
        flags.update({
            "v78_risk_reduction_applied": True,
            "v78_risk_reduction_level": "mild_strong_setup" if bool(strong_setup) else "mild",
            "v78_risk_reduction_mult": mult,
            "v78_risk_reduction_reason": mild_hits,
        })
    return risk_mult, flags


def _apply_directional_setup_scaling(self, symbol: str, base_risk_multiplier: float, adx_h: float, drift: float, volume_meta: dict | None = None, trade_type: str = "", side: str = "", market_state: str = "", trend_quality_meta: dict | None = None) -> tuple[float, dict]:
    flags = {"core_strong_setup": False, "core_very_strong_setup": False, "directional_setup_strength": "normal", "smart_scaling_pass": False, "v6_boost_applied": False}
    if not bool(getattr(cfg, "ENABLE_DIRECTIONAL_RISK_SCALING", True)):
        return float(base_risk_multiplier), flags
    if bool(getattr(cfg, "V6_BOOST_LONG_ONLY", True)) and side == "short":
        return float(base_risk_multiplier), flags
    scaling_symbols = set(getattr(cfg, "DIRECTIONAL_SCALING_SYMBOLS", ["BTCUSDT", "ETHUSDT"]) or [])
    if symbol not in scaling_symbols:
        return float(base_risk_multiplier), flags

    if bool(getattr(cfg, "SMART_SCALING_ONLY_IN_TREND", True)) and market_state != "trend":
        flags["smart_scaling_reason"] = "non_trend_market_state"
        return float(base_risk_multiplier), flags

    if trade_type == "impulse" and not bool(getattr(cfg, "SMART_SCALING_ALLOW_FOR_IMPULSE", True)):
        flags["smart_scaling_reason"] = "impulse_disabled"
        return float(base_risk_multiplier), flags
    if trade_type == "continuation" and not bool(getattr(cfg, "SMART_SCALING_ALLOW_FOR_CONTINUATION", True)):
        flags["smart_scaling_reason"] = "continuation_disabled"
        return float(base_risk_multiplier), flags
    if trade_type == "cont_compression" and not bool(getattr(cfg, "SMART_SCALING_ALLOW_FOR_CONT_COMPRESSION", True)):
        flags["smart_scaling_reason"] = "cont_compression_disabled"
        return float(base_risk_multiplier), flags

    trend_quality_meta = trend_quality_meta or {}
    volume_meta = volume_meta or {}
    impulse_score = float(volume_meta.get("impulse_score", 0.0) or 0.0)
    ema20_crosses = int(trend_quality_meta.get("ema20_crosses", 99) or 99)
    mean_wickiness = float(trend_quality_meta.get("mean_wickiness", 1.0) or 1.0)
    mean_body_ratio = float(trend_quality_meta.get("mean_body_ratio", 0.0) or 0.0)
    ema20_slope_pct = float(trend_quality_meta.get("ema20_slope_pct", 0.0) or 0.0)
    ema50_slope_pct = float(trend_quality_meta.get("ema50_slope_pct", 0.0) or 0.0)

    if bool(getattr(cfg, "ENABLE_SMART_DIRECTIONAL_SCALING", True)):
        max_crosses = int(getattr(cfg, "SMART_SCALING_MAX_EMA20_CROSSES", 1))
        max_wickiness = float(getattr(cfg, "SMART_SCALING_MAX_WICKINESS", 0.52))
        min_body_ratio = float(getattr(cfg, "SMART_SCALING_MIN_BODY_RATIO", 0.40))
        min_ema20_slope = float(getattr(cfg, "SMART_SCALING_MIN_EMA20_SLOPE_PCT", 0.0038))
        min_ema50_slope = float(getattr(cfg, "SMART_SCALING_MIN_EMA50_SLOPE_PCT", 0.0020))
        min_atr_pct = float(getattr(cfg, "SMART_SCALING_MIN_ATR_PCT", 0.0016))
        clean_trend = ema20_crosses <= max_crosses and mean_wickiness <= max_wickiness and mean_body_ratio >= min_body_ratio
        slope_trend = ema20_slope_pct >= min_ema20_slope and ema50_slope_pct >= min_ema50_slope
        if not (clean_trend and slope_trend and float(getattr(self, "_last_atr_pct_h", 0.0) or 0.0) >= min_atr_pct):
            flags["smart_scaling_reason"] = "trend_quality_not_clean_enough"
            return float(base_risk_multiplier), flags
        flags["smart_scaling_pass"] = True

    strong_adx = float(getattr(cfg, "STRONG_SETUP_MIN_ADX", 26.0))
    very_strong_adx = float(getattr(cfg, "VERY_STRONG_SETUP_MIN_ADX", 32.0))
    strong_drift = float(getattr(cfg, "STRONG_SETUP_MIN_DRIFT_PCT", 0.0075))
    very_strong_drift = float(getattr(cfg, "VERY_STRONG_SETUP_MIN_DRIFT_PCT", 0.0110))
    strong_impulse = float(getattr(cfg, "STRONG_SETUP_MIN_VOLUME_IMPULSE", 0.85))
    very_strong_impulse = float(getattr(cfg, "VERY_STRONG_SETUP_MIN_VOLUME_IMPULSE", 0.98))

    if side == "short":
        strong_adx += float(getattr(cfg, "SMART_SCALING_SHORT_EXTRA_MIN_ADX", 2.0))
        very_strong_adx += float(getattr(cfg, "SMART_SCALING_SHORT_EXTRA_MIN_ADX", 2.0))
        strong_drift += float(getattr(cfg, "SMART_SCALING_SHORT_EXTRA_MIN_DRIFT_PCT", 0.0015))
        very_strong_drift += float(getattr(cfg, "SMART_SCALING_SHORT_EXTRA_MIN_DRIFT_PCT", 0.0015))
        strong_impulse += float(getattr(cfg, "SMART_SCALING_SHORT_EXTRA_MIN_IMPULSE", 0.05))
        very_strong_impulse += float(getattr(cfg, "SMART_SCALING_SHORT_EXTRA_MIN_IMPULSE", 0.05))

    risk_mult = float(base_risk_multiplier)
    if float(adx_h) >= very_strong_adx and float(drift) >= very_strong_drift and impulse_score >= very_strong_impulse:
        risk_mult *= float(getattr(cfg, "VERY_STRONG_SETUP_RISK_MULT", 2.20))
        flags.update({"core_strong_setup": True, "core_very_strong_setup": True, "directional_setup_strength": "very_strong"})
    elif float(adx_h) >= strong_adx and float(drift) >= strong_drift and impulse_score >= strong_impulse:
        risk_mult *= float(getattr(cfg, "STRONG_SETUP_RISK_MULT", 1.60))
        flags.update({"core_strong_setup": True, "core_very_strong_setup": False, "directional_setup_strength": "strong"})
    else:
        flags["smart_scaling_reason"] = "base_thresholds_not_met"

    if (
        bool(getattr(cfg, "V6_ENABLE_BTC_BOOST", True))
        and symbol in set(getattr(cfg, "V6_BOOST_SYMBOLS", ["BTCUSDT"]) or [])
        and trade_type in set(getattr(cfg, "V6_BOOST_TRADE_TYPES", ["impulse", "continuation", "cont_compression"]) or [])
        and market_state == "trend"
        and side == "long"
    ):
        min_adx = float(getattr(cfg, "V6_BOOST_MIN_HTF_ADX", 27.0))
        min_drift = float(getattr(cfg, "V6_BOOST_MIN_DRIFT_PCT", 0.0080))
        min_impulse = float(getattr(cfg, "V6_BOOST_MIN_IMPULSE_SCORE", 0.95))
        if float(adx_h) >= min_adx and float(drift) >= min_drift and impulse_score >= min_impulse:
            boost = float(getattr(cfg, "V6_BOOST_MULT_VERY_STRONG", 1.20)) if flags.get("core_very_strong_setup") else float(getattr(cfg, "V6_BOOST_MULT_STRONG", 1.12))
            risk_mult *= boost
            flags["v6_boost_applied"] = True
            flags["v6_boost_mult"] = boost

    return risk_mult, flags
