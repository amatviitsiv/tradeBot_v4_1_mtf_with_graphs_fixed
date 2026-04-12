import config as cfg


def _is_alt_symbol(self, symbol: str) -> bool:
    btc_symbol = str(getattr(cfg, "BTC_REGIME_FILTER_SYMBOL", "BTCUSDT"))
    alt_symbols = set(getattr(cfg, "BTC_REGIME_ALT_SYMBOLS", ["ETHUSDT", "SOLUSDT", "BNBUSDT", "AVAXUSDT"]) or [])
    return bool(symbol and symbol != btc_symbol and symbol in alt_symbols)


def _alt_strong_setup(self, symbol: str, adx_h: float, drift: float, volume_meta: dict | None = None, rs_meta: dict | None = None, side: str = "long") -> bool:
    if not self._is_alt_symbol(symbol):
        return False
    volume_meta = volume_meta or {}
    rs_meta = rs_meta or {}
    min_adx = float(cfg.get_symbol_param_float(symbol, "ALT_STRONG_SETUP_ADX", float(getattr(cfg, "ALT_STRONG_SETUP_ADX", 28.0))))
    min_drift = float(cfg.get_symbol_param_float(symbol, "ALT_STRONG_SETUP_DRIFT_PCT", float(getattr(cfg, "ALT_STRONG_SETUP_DRIFT_PCT", 0.0085))))
    min_impulse = float(cfg.get_symbol_param_float(symbol, "ALT_STRONG_SETUP_VOLUME_IMPULSE", float(getattr(cfg, "ALT_STRONG_SETUP_VOLUME_IMPULSE", 0.95))))
    ratio = float(rs_meta.get("ratio", 1.0) or 1.0)
    ratio_req = float(cfg.get_symbol_param_float(symbol, "ALT_STRONG_SETUP_RS_RATIO_LONG", float(getattr(cfg, "ALT_STRONG_SETUP_RS_RATIO_LONG", 1.0)))) if side == "long" else float(cfg.get_symbol_param_float(symbol, "ALT_STRONG_SETUP_RS_RATIO_SHORT", float(getattr(cfg, "ALT_STRONG_SETUP_RS_RATIO_SHORT", 1.0))))
    return float(adx_h) >= min_adx and float(drift) >= min_drift and float(volume_meta.get("impulse_score", 0.0) or 0.0) >= min_impulse and ((ratio >= ratio_req) if side == "long" else (ratio <= ratio_req))


def _alt_setup_tier(self, symbol: str, side: str, trade_type: str, adx_h: float, drift: float, volume_meta: dict | None = None, rs_meta: dict | None = None, alt_meta: dict | None = None) -> str:
    if not self._is_alt_symbol(symbol):
        return "not_alt"
    side = str(side or "").lower()
    trade_type = str(trade_type or "").lower()
    volume_meta = volume_meta or {}
    rs_meta = rs_meta or {}
    alt_meta = alt_meta or {}
    if self._alt_strong_setup(symbol, adx_h, drift, volume_meta, rs_meta, side=side):
        return "strong"
    impulse_score = float(volume_meta.get("impulse_score", 0.0) or 0.0)
    ratio = float(rs_meta.get("ratio", 1.0) or 1.0)
    alt_score = float(alt_meta.get("score", 0.0) or 0.0)
    if trade_type == "cont_compression":
        min_adx = float(cfg.get_symbol_param_float(symbol, "ALT_MEDIUM_CONT_COMP_ADX", 18.0))
        min_drift = float(cfg.get_symbol_param_float(symbol, "ALT_MEDIUM_CONT_COMP_DRIFT_PCT", 0.0042))
        min_impulse = float(cfg.get_symbol_param_float(symbol, "ALT_MEDIUM_CONT_COMP_VOLUME_IMPULSE", 0.46))
    else:
        min_adx = float(cfg.get_symbol_param_float(symbol, "ALT_MEDIUM_SETUP_ADX", 19.0))
        min_drift = float(cfg.get_symbol_param_float(symbol, "ALT_MEDIUM_SETUP_DRIFT_PCT", 0.0045))
        min_impulse = float(cfg.get_symbol_param_float(symbol, "ALT_MEDIUM_SETUP_VOLUME_IMPULSE", 0.50))
    if side == "long":
        min_ratio = float(cfg.get_symbol_param_float(symbol, "ALT_MEDIUM_SETUP_RS_RATIO_LONG", 0.9995))
        min_alt = float(cfg.get_symbol_param_float(symbol, "ALT_MEDIUM_SETUP_MIN_ALT_SCORE_LONG", 0.42))
        ok_ratio = ratio >= min_ratio
    else:
        max_ratio = float(cfg.get_symbol_param_float(symbol, "ALT_MEDIUM_SETUP_RS_RATIO_SHORT", 1.0005))
        min_alt = float(cfg.get_symbol_param_float(symbol, "ALT_MEDIUM_SETUP_MIN_ALT_SCORE_SHORT", 0.46))
        ok_ratio = ratio <= max_ratio
    if float(adx_h) >= min_adx and float(drift) >= min_drift and impulse_score >= min_impulse and alt_score >= min_alt and ok_ratio:
        return "medium"
    return "weak"


def _relax_alt_filters(self, symbol: str, side: str, alt_ok: bool, alt_meta: dict, rs_ok: bool, rs_meta: dict) -> tuple[bool, bool, dict, dict]:
    if not self._is_alt_symbol(symbol):
        return alt_ok, rs_ok, alt_meta, rs_meta
    if not alt_ok:
        score = float(alt_meta.get("score", 0.0) or 0.0)
        threshold = float(alt_meta.get("threshold", cfg.get_symbol_param_float(symbol, "ALT_QUALITY_MIN_SCORE", float(getattr(cfg, "ALT_QUALITY_MIN_SCORE", 0.48)))) or 0.0)
        relax = float(cfg.get_symbol_param_float(symbol, "ALT_QUALITY_THRESHOLD_RELAX", float(getattr(cfg, "ALT_QUALITY_THRESHOLD_RELAX", 0.05))))
        if score >= max(0.0, threshold - relax):
            alt_ok = True
            alt_meta = {**alt_meta, "soft_pass": True, "soft_margin": relax}
    if not rs_ok:
        ratio = float(rs_meta.get("ratio", 1.0) or 1.0)
        slope = float(rs_meta.get("slope", 0.0) or 0.0)
        if side == "long":
            relax_ratio = float(cfg.get_symbol_param_float(symbol, "ALT_REL_STRENGTH_LONG_RATIO_RELAX", float(getattr(cfg, "ALT_REL_STRENGTH_LONG_RATIO_RELAX", 0.0020))))
            relax_slope = float(cfg.get_symbol_param_float(symbol, "ALT_REL_STRENGTH_LONG_MIN_SLOPE_RELAX", float(getattr(cfg, "ALT_REL_STRENGTH_LONG_MIN_SLOPE_RELAX", 0.0030))))
            min_ratio = float(cfg.get_symbol_param_float(symbol, "REL_STRENGTH_MIN_RATIO", float(getattr(cfg, "REL_STRENGTH_MIN_RATIO", 1.002))))
            min_slope = float(cfg.get_symbol_param_float(symbol, "REL_STRENGTH_MIN_SLOPE", float(getattr(cfg, "REL_STRENGTH_MIN_SLOPE", 0.0))))
            if ratio >= (min_ratio - relax_ratio) and slope >= (min_slope - relax_slope):
                rs_ok = True
                rs_meta = {**rs_meta, "soft_pass": True, "ratio_relax": relax_ratio, "slope_relax": relax_slope}
        else:
            relax_ratio = float(cfg.get_symbol_param_float(symbol, "ALT_REL_STRENGTH_SHORT_RATIO_RELAX", float(getattr(cfg, "ALT_REL_STRENGTH_SHORT_RATIO_RELAX", 0.0020))))
            relax_slope = float(cfg.get_symbol_param_float(symbol, "ALT_REL_STRENGTH_SHORT_MIN_SLOPE_RELAX", float(getattr(cfg, "ALT_REL_STRENGTH_SHORT_MIN_SLOPE_RELAX", 0.0030))))
            max_ratio = float(cfg.get_symbol_param_float(symbol, "REL_STRENGTH_SHORT_MAX_RATIO", float(getattr(cfg, "REL_STRENGTH_SHORT_MAX_RATIO", 0.998))))
            min_slope = float(cfg.get_symbol_param_float(symbol, "REL_STRENGTH_SHORT_MIN_SLOPE", float(getattr(cfg, "REL_STRENGTH_SHORT_MIN_SLOPE", 0.0))))
            if ratio <= (max_ratio + relax_ratio) and slope <= (min_slope + relax_slope):
                rs_ok = True
                rs_meta = {**rs_meta, "soft_pass": True, "ratio_relax": relax_ratio, "slope_relax": relax_slope}
    return alt_ok, rs_ok, alt_meta, rs_meta


def _alt_upgrade_gate(self, symbol: str, side: str, trade_type: str, alt_meta: dict | None = None, rs_meta: dict | None = None, btc_meta: dict | None = None, adx_h: float = 0.0, drift: float = 0.0, volume_meta: dict | None = None) -> tuple[bool, dict]:
    if not self._is_alt_symbol(symbol):
        return True, {"skipped": True, "reason": "not_alt_symbol"}
    if not bool(getattr(cfg, "ALT_V1_UPGRADE_ENABLED", True)):
        return True, {"disabled": True}

    alt_meta = alt_meta or {}
    rs_meta = rs_meta or {}
    btc_meta = btc_meta or {}
    volume_meta = volume_meta or {}
    trade_type = str(trade_type or "").lower()
    side = str(side or "").lower()

    strong_setup = self._alt_strong_setup(symbol, adx_h, drift, volume_meta, rs_meta, side=side)
    setup_tier = self._alt_setup_tier(symbol=symbol, side=side, trade_type=trade_type, adx_h=adx_h, drift=drift, volume_meta=volume_meta, rs_meta=rs_meta, alt_meta=alt_meta)
    alt_score = float(alt_meta.get("score", 0.0) or 0.0)
    rs_ratio = float(rs_meta.get("ratio", 1.0) or 1.0)
    btc_score = float(btc_meta.get("score", 0.0) or 0.0)
    soft_alt = bool(alt_meta.get("soft_pass", False))
    soft_rs = bool(rs_meta.get("soft_pass", False))

    if trade_type in {"continuation", "cont_compression"}:
        if side == "long":
            min_alt = float(cfg.get_symbol_param_float(symbol, "ALT_V1_CONT_LONG_MIN_SCORE", float(getattr(cfg, "ALT_V1_CONT_LONG_MIN_SCORE", 0.50))))
            min_btc = float(cfg.get_symbol_param_float(symbol, "ALT_V1_CONT_LONG_MIN_BTC_SCORE", float(getattr(cfg, "ALT_V1_CONT_LONG_MIN_BTC_SCORE", 1.00))))
            min_ratio = float(cfg.get_symbol_param_float(symbol, "ALT_V1_CONT_LONG_MIN_RS_RATIO", float(getattr(cfg, "ALT_V1_CONT_LONG_MIN_RS_RATIO", 1.0035))))
            if soft_alt and not strong_setup and not (trade_type == "cont_compression" and setup_tier == "medium"):
                return False, {"reason": "alt_soft_pass_blocked", "trade_type": trade_type, "strong_setup": strong_setup, "alt_score": alt_score, "setup_tier": setup_tier}
            if soft_rs and not strong_setup and not (trade_type == "cont_compression" and setup_tier == "medium"):
                return False, {"reason": "rs_soft_pass_blocked", "trade_type": trade_type, "strong_setup": strong_setup, "rs_ratio": rs_ratio, "setup_tier": setup_tier}
            if alt_score < min_alt and not strong_setup:
                return False, {"reason": "alt_score_too_low", "trade_type": trade_type, "alt_score": alt_score, "min_alt_score": min_alt}
            if rs_ratio < min_ratio and not strong_setup:
                return False, {"reason": "rs_ratio_too_low", "trade_type": trade_type, "rs_ratio": rs_ratio, "min_rs_ratio": min_ratio}
            if btc_score < min_btc:
                return False, {"reason": "btc_context_too_weak", "trade_type": trade_type, "btc_score": btc_score, "min_btc_score": min_btc}
        else:
            min_alt = float(cfg.get_symbol_param_float(symbol, "ALT_V1_CONT_SHORT_MIN_SCORE", float(getattr(cfg, "ALT_V1_CONT_SHORT_MIN_SCORE", 0.54))))
            min_btc = float(cfg.get_symbol_param_float(symbol, "ALT_V1_CONT_SHORT_MIN_BTC_SCORE", float(getattr(cfg, "ALT_V1_CONT_SHORT_MIN_BTC_SCORE", 1.12))))
            max_ratio = float(cfg.get_symbol_param_float(symbol, "ALT_V1_CONT_SHORT_MAX_RS_RATIO", float(getattr(cfg, "ALT_V1_CONT_SHORT_MAX_RS_RATIO", 0.9965))))
            require_strong = bool(getattr(cfg, "ALT_V1_CONT_SHORT_REQUIRE_STRONG_SETUP", True))
            if soft_alt and setup_tier == "weak":
                return False, {"reason": "alt_soft_pass_blocked", "trade_type": trade_type, "side": side, "alt_score": alt_score, "setup_tier": setup_tier}
            if soft_rs and setup_tier == "weak":
                return False, {"reason": "rs_soft_pass_blocked", "trade_type": trade_type, "side": side, "rs_ratio": rs_ratio, "setup_tier": setup_tier}
            if alt_score < min_alt:
                return False, {"reason": "alt_score_too_low", "trade_type": trade_type, "side": side, "alt_score": alt_score, "min_alt_score": min_alt}
            if rs_ratio > max_ratio:
                return False, {"reason": "rs_ratio_not_weak_enough", "trade_type": trade_type, "side": side, "rs_ratio": rs_ratio, "max_rs_ratio": max_ratio}
            if btc_score < min_btc:
                return False, {"reason": "btc_context_too_weak", "trade_type": trade_type, "side": side, "btc_score": btc_score, "min_btc_score": min_btc}
            if require_strong and not strong_setup and setup_tier != "medium":
                return False, {"reason": "strong_setup_required", "trade_type": trade_type, "side": side, "strong_setup": strong_setup, "setup_tier": setup_tier}

    return True, {"passed": True, "trade_type": trade_type, "side": side, "strong_setup": strong_setup, "setup_tier": setup_tier, "alt_score": alt_score, "rs_ratio": rs_ratio, "btc_score": btc_score}


def _apply_alt_risk_adjustment(self, symbol: str, side: str, trade_type: str, risk_multiplier: float, strong_setup: bool = False, regime_gate_meta: dict | None = None, alt_meta: dict | None = None, rs_meta: dict | None = None, volume_meta: dict | None = None, adx_h: float = 0.0, drift: float = 0.0) -> tuple[float, dict]:
    flags = {"alt_risk_adjustment_applied": False}
    if not self._is_alt_symbol(symbol):
        return float(risk_multiplier), flags
    if not bool(getattr(cfg, "ALT_V1_UPGRADE_ENABLED", True)):
        return float(risk_multiplier), flags
    trade_type = str(trade_type or "").lower()
    side = str(side or "").lower()
    risk_mult = float(risk_multiplier)
    tier = self._alt_setup_tier(symbol=symbol, side=side, trade_type=trade_type, adx_h=adx_h, drift=drift, volume_meta=volume_meta, rs_meta=rs_meta, alt_meta=alt_meta)
    if trade_type in {"continuation", "cont_compression"}:
        if tier == "strong" or strong_setup:
            if side == "short":
                mult = float(cfg.get_symbol_param_float(symbol, "ALT_V1_CONT_SHORT_STRONG_RISK_MULT", float(getattr(cfg, "ALT_V1_CONT_SHORT_STRONG_RISK_MULT", 0.85))))
                risk_mult *= mult
                flags = {"alt_risk_adjustment_applied": True, "alt_risk_adjustment_type": "cont_short_strong", "alt_risk_adjustment_mult": mult, "alt_setup_tier": "strong"}
            else:
                flags = {"alt_risk_adjustment_applied": True, "alt_risk_adjustment_type": "cont_long_strong", "alt_risk_adjustment_mult": 1.0, "alt_setup_tier": "strong"}
        elif tier == "medium":
            if trade_type == "cont_compression":
                default = 0.78 if side == "long" else 0.70
                mult_name = "ALT_MEDIUM_RISK_MULT_CONT_COMP"
            else:
                default = 0.60 if side == "long" else 0.62
                mult_name = "ALT_MEDIUM_RISK_MULT_CONT"
            mult = float(cfg.get_symbol_param_float(symbol, mult_name, float(getattr(cfg, mult_name, default))))
            risk_mult *= mult
            flags = {"alt_risk_adjustment_applied": True, "alt_risk_adjustment_type": f"{trade_type}_{side}_medium", "alt_risk_adjustment_mult": mult, "alt_setup_tier": "medium"}
        else:
            if side == "long":
                mult = float(cfg.get_symbol_param_float(symbol, "ALT_V1_CONT_LONG_WEAK_RISK_MULT", float(getattr(cfg, "ALT_V1_CONT_LONG_WEAK_RISK_MULT", 0.90))))
                risk_mult *= mult
                flags = {"alt_risk_adjustment_applied": True, "alt_risk_adjustment_type": "cont_long_weak", "alt_risk_adjustment_mult": mult, "alt_setup_tier": "weak"}
            else:
                mult = float(cfg.get_symbol_param_float(symbol, "ALT_V1_CONT_SHORT_RISK_MULT", float(getattr(cfg, "ALT_V1_CONT_SHORT_RISK_MULT", 0.72))))
                risk_mult *= mult
                flags = {"alt_risk_adjustment_applied": True, "alt_risk_adjustment_type": "cont_short_weak", "alt_risk_adjustment_mult": mult, "alt_setup_tier": "weak"}
    return risk_mult, flags


def _apply_v80_alt_engine_upgrade(self, symbol: str, side: str, trade_type: str, risk_multiplier: float, alt_meta: dict | None = None, btc_meta: dict | None = None, rs_meta: dict | None = None, adx_h: float = 0.0, drift: float = 0.0, volume_meta: dict | None = None, strong_setup: bool = False, regime_gate_meta: dict | None = None) -> tuple[float, dict]:
    flags = {"v80_alt_engine_applied": False}
    risk_mult = float(risk_multiplier)
    if not bool(getattr(cfg, "V80_ALT_ENGINE_ENABLED", True)):
        return risk_mult, flags
    if not self._is_alt_symbol(symbol):
        return risk_mult, flags
    allowed_types = {str(v).lower() for v in (getattr(cfg, "V80_ALT_ENGINE_ALLOWED_TYPES", ["impulse", "continuation", "cont_compression"]) or ["impulse", "continuation", "cont_compression"])}
    trade_type = str(trade_type or "").lower()
    if trade_type not in allowed_types:
        return risk_mult, flags
    alt_meta = alt_meta or {}
    btc_meta = btc_meta or {}
    rs_meta = rs_meta or {}
    volume_meta = volume_meta or {}
    alt_score = float(alt_meta.get("score", 0.0) or 0.0)
    btc_score = float(btc_meta.get("score", 0.0) or 0.0)
    rs_ratio = float(rs_meta.get("ratio", 1.0) or 1.0)
    impulse_score = float(volume_meta.get("impulse_score", 0.0) or 0.0)

    long_side = str(side or "").lower() == "long"
    weak_hits = []
    if btc_score < float(getattr(cfg, "V80_ALT_MIN_BTC_SCORE", 0.98)):
        weak_hits.append(f"btc_score:{btc_score:.3f}")
    if alt_score < float(getattr(cfg, "V80_ALT_MIN_ALT_SCORE", 0.98)):
        weak_hits.append(f"alt_score:{alt_score:.3f}")
    if long_side:
        if rs_ratio < float(getattr(cfg, "V80_ALT_LONG_MIN_RS_RATIO", 1.00)):
            weak_hits.append(f"rs_ratio:{rs_ratio:.3f}")
    else:
        if rs_ratio > float(getattr(cfg, "V80_ALT_SHORT_MAX_RS_RATIO", 1.00)):
            weak_hits.append(f"rs_ratio:{rs_ratio:.3f}")
    if float(adx_h) < float(getattr(cfg, "V80_ALT_MIN_ADX", 18.0)):
        weak_hits.append(f"adx_h:{float(adx_h):.2f}")
    if float(drift) < float(getattr(cfg, "V80_ALT_MIN_DRIFT_PCT", 0.0035)):
        weak_hits.append(f"drift:{float(drift):.4f}")
    if impulse_score < float(getattr(cfg, "V80_ALT_MIN_IMPULSE_SCORE", 0.62)):
        weak_hits.append(f"impulse_score:{impulse_score:.3f}")

    strong_ok = bool(strong_setup) and btc_score >= float(getattr(cfg, "V80_ALT_STRONG_MIN_BTC_SCORE", 1.08)) and alt_score >= float(getattr(cfg, "V80_ALT_STRONG_MIN_ALT_SCORE", 1.08)) and impulse_score >= float(getattr(cfg, "V80_ALT_STRONG_MIN_IMPULSE_SCORE", 0.90)) and float(adx_h) >= float(getattr(cfg, "V80_ALT_STRONG_MIN_ADX", 24.0))
    if long_side and rs_ratio < float(getattr(cfg, "V80_ALT_STRONG_LONG_MIN_RS_RATIO", 1.03)):
        strong_ok = False
    if (not long_side) and rs_ratio > float(getattr(cfg, "V80_ALT_STRONG_SHORT_MAX_RS_RATIO", 0.97)):
        strong_ok = False

    if strong_ok:
        mult = float(cfg.get_symbol_param_float(symbol, "V80_ALT_STRONG_RISK_MULT", float(getattr(cfg, "V80_ALT_STRONG_RISK_MULT", 1.04))))
        risk_mult *= mult
        flags.update({"v80_alt_engine_applied": True, "v80_alt_engine_tier": "strong", "v80_alt_engine_mult": mult, "v80_alt_engine_reason": ["strong_setup"]})
    elif weak_hits:
        mult = float(cfg.get_symbol_param_float(symbol, "V80_ALT_WEAK_RISK_MULT", float(getattr(cfg, "V80_ALT_WEAK_RISK_MULT", 0.86))))
        risk_mult *= mult
        flags.update({"v80_alt_engine_applied": True, "v80_alt_engine_tier": "weak", "v80_alt_engine_mult": mult, "v80_alt_engine_reason": weak_hits})
    else:
        mult = float(cfg.get_symbol_param_float(symbol, "V80_ALT_NORMAL_RISK_MULT", float(getattr(cfg, "V80_ALT_NORMAL_RISK_MULT", 0.95))))
        risk_mult *= mult
        flags.update({"v80_alt_engine_applied": True, "v80_alt_engine_tier": "normal", "v80_alt_engine_mult": mult, "v80_alt_engine_reason": ["default"]})
    return risk_mult, flags


def _alt_regime_filter(self, symbol: str, side: str, trade_type: str, market_state: str, alt_meta: dict | None = None, rs_meta: dict | None = None, btc_meta: dict | None = None, adx_h: float = 0.0, drift: float = 0.0, volume_meta: dict | None = None, strong_setup: bool = False) -> tuple[bool, dict]:
    if not self._is_alt_symbol(symbol):
        return True, {"skipped": True, "reason": "not_alt_symbol"}
    if not bool(getattr(cfg, "ALT_V2_REGIME_FILTER_ENABLED", True)):
        return True, {"disabled": True}

    alt_meta = alt_meta or {}
    rs_meta = rs_meta or {}
    btc_meta = btc_meta or {}
    volume_meta = volume_meta or {}
    side = str(side or "").lower()
    trade_type = str(trade_type or "").lower()
    market_state = str(market_state or "")

    alt_score = float(alt_meta.get("score", 0.0) or 0.0)
    rs_ratio = float(rs_meta.get("ratio", 1.0) or 1.0)
    btc_score = float(btc_meta.get("score", 0.0) or 0.0)
    impulse_score = float(volume_meta.get("impulse_score", 0.0) or 0.0)
    setup_tier = self._alt_setup_tier(symbol=symbol, side=side, trade_type=trade_type, adx_h=adx_h, drift=drift, volume_meta=volume_meta, rs_meta=rs_meta, alt_meta=alt_meta)
    soft_alt = bool(alt_meta.get("soft_pass", False))
    soft_rs = bool(rs_meta.get("soft_pass", False))

    if side == "long":
        allowed_states = {"trend"}
        if bool(getattr(cfg, "ALT_V2_LONG_ALLOW_TRANSITION_STRONG_SETUP", False)) and strong_setup:
            allowed_states.add("transition")
        if market_state not in allowed_states:
            return False, {"reason": "market_state_blocked", "side": side, "trade_type": trade_type, "market_state": market_state, "allowed_states": sorted(allowed_states)}
        if bool(getattr(cfg, "ALT_V2_LONG_BLOCK_SOFT_PASSES", True)) and (soft_alt or soft_rs) and not strong_setup and setup_tier == "weak":
            return False, {"reason": "soft_pass_blocked", "side": side, "trade_type": trade_type, "soft_alt": soft_alt, "soft_rs": soft_rs, "strong_setup": strong_setup, "setup_tier": setup_tier}

        min_btc = float(cfg.get_symbol_param_float(symbol, "ALT_V2_LONG_MIN_BTC_SCORE", float(getattr(cfg, "ALT_V2_LONG_MIN_BTC_SCORE", 1.00))))
        min_alt = float(cfg.get_symbol_param_float(symbol, "ALT_V2_LONG_MIN_ALT_SCORE", float(getattr(cfg, "ALT_V2_LONG_MIN_ALT_SCORE", 0.50))))
        min_rs = float(cfg.get_symbol_param_float(symbol, "ALT_V2_LONG_MIN_RS_RATIO", float(getattr(cfg, "ALT_V2_LONG_MIN_RS_RATIO", 1.0025))))
        min_adx = float(cfg.get_symbol_param_float(symbol, "ALT_V2_LONG_MIN_ADX", float(getattr(cfg, "ALT_V2_LONG_MIN_ADX", 20.0))))
        min_drift = float(cfg.get_symbol_param_float(symbol, "ALT_V2_LONG_MIN_DRIFT_PCT", float(getattr(cfg, "ALT_V2_LONG_MIN_DRIFT_PCT", 0.0050))))
        min_impulse = float(cfg.get_symbol_param_float(symbol, "ALT_V2_LONG_MIN_VOLUME_IMPULSE", float(getattr(cfg, "ALT_V2_LONG_MIN_VOLUME_IMPULSE", 0.55))))

        if btc_score < min_btc:
            return False, {"reason": "btc_context_too_weak", "side": side, "trade_type": trade_type, "btc_score": btc_score, "min_btc_score": min_btc}
        if float(adx_h) < min_adx or float(drift) < min_drift:
            return False, {"reason": "trend_strength_too_low", "side": side, "trade_type": trade_type, "adx_h": float(adx_h), "drift": float(drift), "min_adx": min_adx, "min_drift": min_drift}
        if impulse_score < min_impulse and not strong_setup:
            return False, {"reason": "volume_impulse_too_low", "side": side, "trade_type": trade_type, "impulse_score": impulse_score, "min_impulse_score": min_impulse, "strong_setup": strong_setup}
        if alt_score < min_alt and not strong_setup:
            return False, {"reason": "alt_score_too_low", "side": side, "trade_type": trade_type, "alt_score": alt_score, "min_alt_score": min_alt, "strong_setup": strong_setup}
        if rs_ratio < min_rs and not strong_setup:
            return False, {"reason": "rs_ratio_too_low", "side": side, "trade_type": trade_type, "rs_ratio": rs_ratio, "min_rs_ratio": min_rs, "strong_setup": strong_setup}
    else:
        allowed_states = {"trend"}
        if bool(getattr(cfg, "ALT_V2_SHORT_ALLOW_TRANSITION", False)):
            allowed_states.add("transition")
        if market_state not in allowed_states:
            return False, {"reason": "market_state_blocked", "side": side, "trade_type": trade_type, "market_state": market_state, "allowed_states": sorted(allowed_states)}
        if bool(getattr(cfg, "ALT_V2_SHORT_BLOCK_SOFT_PASSES", True)) and (soft_alt or soft_rs) and setup_tier == "weak":
            return False, {"reason": "soft_pass_blocked", "side": side, "trade_type": trade_type, "soft_alt": soft_alt, "soft_rs": soft_rs, "setup_tier": setup_tier}

        min_btc = float(cfg.get_symbol_param_float(symbol, "ALT_V2_SHORT_MIN_BTC_SCORE", float(getattr(cfg, "ALT_V2_SHORT_MIN_BTC_SCORE", 1.10))))
        min_alt = float(cfg.get_symbol_param_float(symbol, "ALT_V2_SHORT_MIN_ALT_SCORE", float(getattr(cfg, "ALT_V2_SHORT_MIN_ALT_SCORE", 0.56))))
        max_rs = float(cfg.get_symbol_param_float(symbol, "ALT_V2_SHORT_MAX_RS_RATIO", float(getattr(cfg, "ALT_V2_SHORT_MAX_RS_RATIO", 0.9970))))
        min_adx = float(cfg.get_symbol_param_float(symbol, "ALT_V2_SHORT_MIN_ADX", float(getattr(cfg, "ALT_V2_SHORT_MIN_ADX", 24.0))))
        min_drift = float(cfg.get_symbol_param_float(symbol, "ALT_V2_SHORT_MIN_DRIFT_PCT", float(getattr(cfg, "ALT_V2_SHORT_MIN_DRIFT_PCT", 0.0065))))
        min_impulse = float(cfg.get_symbol_param_float(symbol, "ALT_V2_SHORT_MIN_VOLUME_IMPULSE", float(getattr(cfg, "ALT_V2_SHORT_MIN_VOLUME_IMPULSE", 0.60))))
        require_strong = bool(getattr(cfg, "ALT_V2_SHORT_REQUIRE_STRONG_SETUP", True))

        if btc_score < min_btc:
            return False, {"reason": "btc_context_too_weak", "side": side, "trade_type": trade_type, "btc_score": btc_score, "min_btc_score": min_btc}
        if float(adx_h) < min_adx or float(drift) < min_drift:
            return False, {"reason": "trend_strength_too_low", "side": side, "trade_type": trade_type, "adx_h": float(adx_h), "drift": float(drift), "min_adx": min_adx, "min_drift": min_drift}
        if impulse_score < min_impulse:
            return False, {"reason": "volume_impulse_too_low", "side": side, "trade_type": trade_type, "impulse_score": impulse_score, "min_impulse_score": min_impulse}
        if alt_score < min_alt:
            return False, {"reason": "alt_score_too_low", "side": side, "trade_type": trade_type, "alt_score": alt_score, "min_alt_score": min_alt}
        if rs_ratio > max_rs:
            return False, {"reason": "rs_ratio_not_weak_enough", "side": side, "trade_type": trade_type, "rs_ratio": rs_ratio, "max_rs_ratio": max_rs}
        if require_strong and not strong_setup and setup_tier != "medium":
            return False, {"reason": "strong_setup_required", "side": side, "trade_type": trade_type, "strong_setup": strong_setup, "setup_tier": setup_tier}

    return True, {
        "passed": True,
        "side": side,
        "trade_type": trade_type,
        "market_state": market_state,
        "btc_score": btc_score,
        "alt_score": alt_score,
        "rs_ratio": rs_ratio,
        "adx_h": float(adx_h),
        "drift": float(drift),
        "impulse_score": impulse_score,
        "strong_setup": bool(strong_setup),
        "setup_tier": setup_tier,
    }
