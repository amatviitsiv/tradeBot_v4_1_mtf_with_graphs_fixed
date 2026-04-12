from __future__ import annotations

from typing import Any


def apply_standard_long_risk_stack(
    strategy: Any,
    *,
    symbol: str,
    trade_type: str,
    risk_multiplier: float,
    market_state: str,
    regime: str,
    btc_meta: dict | None = None,
    alt_meta: dict | None = None,
    rs_meta: dict | None = None,
    volume_meta: dict | None = None,
    trend_quality_meta: dict | None = None,
    regime_gate_meta: dict | None = None,
    adx_h: float = 0.0,
    drift: float = 0.0,
    strong_setup: bool = False,
) -> tuple[float, dict]:
    risk_mult = float(risk_multiplier)
    risk_mult, setup_flags = strategy._apply_directional_setup_scaling(
        symbol=symbol,
        base_risk_multiplier=risk_mult,
        adx_h=adx_h,
        drift=drift,
        volume_meta=volume_meta,
        trade_type=trade_type,
        side="long",
        market_state=market_state,
        trend_quality_meta=trend_quality_meta,
    )
    risk_mult, alt_risk_flags = strategy._apply_alt_risk_adjustment(
        symbol=symbol,
        side="long",
        trade_type=trade_type,
        risk_multiplier=risk_mult,
        strong_setup=strong_setup,
        regime_gate_meta=regime_gate_meta,
        alt_meta=alt_meta,
        rs_meta=rs_meta,
        volume_meta=volume_meta,
        adx_h=adx_h,
        drift=drift,
    )
    risk_mult, v7_flags = strategy._apply_v7_direct_boost(
        symbol=symbol,
        side="long",
        trade_type=trade_type,
        base_risk_multiplier=risk_mult,
        adx_h=adx_h,
        drift=drift,
        volume_meta=volume_meta,
        strong_setup=strong_setup,
        regime_gate_meta=regime_gate_meta,
    )
    risk_mult, v78_flags = strategy._apply_v78_selective_risk_reduction(
        symbol=symbol,
        side="long",
        trade_type=trade_type,
        base_risk_multiplier=risk_mult,
        market_state=market_state,
        regime=regime,
        regime_gate_meta=regime_gate_meta,
        trend_quality_meta=trend_quality_meta,
        volume_meta=volume_meta,
        strong_setup=strong_setup,
        v7_flags=v7_flags,
    )
    risk_mult, v80_alt_flags = strategy._apply_v80_alt_engine_upgrade(
        symbol=symbol,
        side="long",
        trade_type=trade_type,
        risk_multiplier=risk_mult,
        alt_meta=alt_meta,
        btc_meta=btc_meta,
        rs_meta=rs_meta,
        adx_h=adx_h,
        drift=drift,
        volume_meta=volume_meta,
        strong_setup=strong_setup,
        regime_gate_meta=regime_gate_meta,
    )
    return risk_mult, {
        **(setup_flags or {}),
        **(alt_risk_flags or {}),
        **(v7_flags or {}),
        **(v78_flags or {}),
        **(v80_alt_flags or {}),
    }


def apply_standard_short_risk_stack(
    strategy: Any,
    *,
    symbol: str,
    trade_type: str,
    risk_multiplier: float,
    market_state: str,
    regime: str,
    btc_meta: dict | None = None,
    alt_meta: dict | None = None,
    rs_meta: dict | None = None,
    volume_meta: dict | None = None,
    trend_quality_meta: dict | None = None,
    regime_gate_meta: dict | None = None,
    adx_h: float = 0.0,
    drift: float = 0.0,
    strong_setup: bool = False,
) -> tuple[float, bool, dict]:
    risk_mult = float(risk_multiplier)
    risk_mult, setup_flags = strategy._apply_directional_setup_scaling(
        symbol=symbol,
        base_risk_multiplier=risk_mult,
        adx_h=adx_h,
        drift=drift,
        volume_meta=volume_meta,
        trade_type=trade_type,
        side="short",
        market_state=market_state,
        trend_quality_meta=trend_quality_meta,
    )
    risk_mult, alt_risk_flags = strategy._apply_alt_risk_adjustment(
        symbol=symbol,
        side="short",
        trade_type=trade_type,
        risk_multiplier=risk_mult,
        strong_setup=strong_setup,
        alt_meta=alt_meta,
        rs_meta=rs_meta,
        volume_meta=volume_meta,
        adx_h=adx_h,
        drift=drift,
    )
    v83_short_ok, v83_short_flags = strategy._apply_v83_short_suppression(
        symbol=symbol,
        side="short",
        trade_type=trade_type,
        market_state=market_state,
        regime=regime,
        btc_meta=btc_meta,
        rs_meta=rs_meta,
        trend_quality_meta=trend_quality_meta,
        strong_setup=strong_setup,
        regime_gate_meta=regime_gate_meta,
    )
    if not v83_short_ok:
        return risk_mult, False, {**(setup_flags or {}), **(alt_risk_flags or {}), **(v83_short_flags or {})}
    risk_mult, v80_short_flags = strategy._apply_v80_short_control(
        symbol=symbol,
        side="short",
        trade_type=trade_type,
        risk_multiplier=risk_mult,
        market_state=market_state,
        regime=regime,
        btc_meta=btc_meta,
        rs_meta=rs_meta,
        trend_quality_meta=trend_quality_meta,
        strong_setup=strong_setup,
        regime_gate_meta=regime_gate_meta,
    )
    risk_mult, v81_short_flags = strategy._apply_v81_aggressive_short_risk(
        symbol=symbol,
        side="short",
        trade_type=trade_type,
        risk_multiplier=risk_mult,
        market_state=market_state,
        regime=regime,
        volume_meta=volume_meta,
        strong_setup=strong_setup,
    )
    risk_mult, v80_alt_flags = strategy._apply_v80_alt_engine_upgrade(
        symbol=symbol,
        side="short",
        trade_type=trade_type,
        risk_multiplier=risk_mult,
        alt_meta=alt_meta,
        btc_meta=btc_meta,
        rs_meta=rs_meta,
        adx_h=adx_h,
        drift=drift,
        volume_meta=volume_meta,
        strong_setup=strong_setup,
    )
    v85_short_ok, v85_short_flags = strategy._apply_v85_inline_short_suppression(
        symbol=symbol,
        trade_type=trade_type,
        market_state=market_state,
        regime=regime,
        btc_meta=btc_meta,
        rs_meta=rs_meta,
        trend_quality_meta=trend_quality_meta,
        regime_gate_meta=regime_gate_meta,
        strong_setup=strong_setup,
    )
    flags = {
        **(setup_flags or {}),
        **(alt_risk_flags or {}),
        **(v83_short_flags or {}),
        **(v80_short_flags or {}),
        **(v81_short_flags or {}),
        **(v80_alt_flags or {}),
        **(v85_short_flags or {}),
    }
    return risk_mult, bool(v85_short_ok), flags



def apply_pullback_long_risk_stack(
    strategy: Any,
    *,
    symbol: str,
    risk_multiplier: float,
    market_state: str,
    regime: str,
    btc_meta: dict | None = None,
    volume_meta: dict | None = None,
    trend_quality_meta: dict | None = None,
    regime_gate_meta: dict | None = None,
    adx_h: float = 0.0,
    drift: float = 0.0,
) -> tuple[float, bool, dict]:
    risk_mult = float(risk_multiplier)
    risk_mult, setup_flags = strategy._apply_directional_setup_scaling(
        symbol=symbol,
        base_risk_multiplier=risk_mult,
        adx_h=adx_h,
        drift=drift,
        volume_meta=volume_meta,
        trade_type="continuation",
        side="long",
        market_state=market_state,
        trend_quality_meta=trend_quality_meta,
    )
    v86_long_ok, v86_long_flags = strategy._apply_v86_inline_long_suppression(
        symbol=symbol,
        trade_type="pullback",
        market_state=market_state,
        regime=regime,
        btc_meta=btc_meta,
        rs_meta={},
        trend_quality_meta=trend_quality_meta,
        regime_gate_meta=regime_gate_meta,
        volume_meta=volume_meta,
        adx_h=adx_h,
        drift=drift,
        strong_setup=False,
    )
    return risk_mult, bool(v86_long_ok), {**(setup_flags or {}), **(v86_long_flags or {})}


def apply_impulse_short_risk_stack(
    strategy: Any,
    *,
    symbol: str,
    risk_multiplier: float,
    market_state: str,
    regime: str,
    btc_meta: dict | None = None,
    alt_meta: dict | None = None,
    rs_meta: dict | None = None,
    volume_meta: dict | None = None,
    trend_quality_meta: dict | None = None,
    regime_gate_meta: dict | None = None,
    adx_h: float = 0.0,
    drift: float = 0.0,
    strong_setup: bool = False,
    allow_late_entry_bypass: bool = False,
) -> tuple[float, bool, dict]:
    risk_mult, short_ok, flags = apply_standard_short_risk_stack(
        strategy,
        symbol=symbol,
        trade_type="impulse",
        risk_multiplier=risk_multiplier,
        market_state=market_state,
        regime=regime,
        btc_meta=btc_meta,
        alt_meta=alt_meta,
        rs_meta=rs_meta,
        volume_meta=volume_meta,
        trend_quality_meta=trend_quality_meta,
        regime_gate_meta=regime_gate_meta,
        adx_h=adx_h,
        drift=drift,
        strong_setup=strong_setup,
    )
    if short_ok or not allow_late_entry_bypass:
        return risk_mult, bool(short_ok), flags
    bypassed = dict(flags or {})
    if bypassed.get("v83_short_suppressed"):
        bypassed["soft_pass"] = True
        bypassed["late_entry"] = True
        bypassed["v83_short_suppressed"] = False
        return risk_mult, True, bypassed
    if bypassed.get("v85_short_suppressed"):
        bypassed["soft_pass"] = True
        bypassed["late_entry"] = True
        bypassed["v85_short_suppressed"] = False
        return risk_mult, True, bypassed
    return risk_mult, False, bypassed
