"""Shared execution-layer policy helpers.

These helpers are intentionally strategy-agnostic and are used by both
live trading and backtesting to keep risk application aligned.
"""

from __future__ import annotations

from typing import Any, Mapping


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _safe_bool(value: Any, default: bool = False) -> bool:
    try:
        return bool(value)
    except Exception:
        return bool(default)


def compute_trade_risk_multiplier(
    sig_meta: Mapping[str, Any] | None,
    side: str | None,
    cfg: Any,
    market_state_fallback: str = "",
    enable_legacy_v812: bool = False,
) -> float:
    """Compute execution-time risk multiplier for a signal.

    The strategy may set a base execution_risk_multiplier, but some execution-
    layer adjustments are intentionally applied here so live trading and
    backtests use the same path.
    """
    meta = sig_meta or {}
    trade_risk_mult = _safe_float(meta.get("execution_risk_multiplier", meta.get("risk_multiplier", 1.0)), 1.0)

    if str(side or "") != "short":
        return trade_risk_mult

    if _safe_bool(meta.get("v80_short_control_applied", False)):
        trade_risk_mult *= _safe_float(meta.get("v80_short_control_mult", 1.0), 1.0)

    if _safe_bool(meta.get("v81_short_adjustment_applied", False)):
        trade_risk_mult *= _safe_float(meta.get("v81_short_adjustment_mult", 1.0), 1.0)

    if _safe_bool(getattr(cfg, "V813_GLOBAL_SHORT_RISK_ENABLED", True), True):
        trade_risk_mult *= _safe_float(getattr(cfg, "V813_GLOBAL_SHORT_BASE_MULT", 1.0), 1.0)
        bad_states = set(getattr(cfg, "V813_GLOBAL_SHORT_BAD_MARKET_STATES", ["chop", "flat", "range"]) or ["chop", "flat", "range"])
        signal_market_state = str(meta.get("market_state", market_state_fallback) or market_state_fallback or "")
        signal_regime = str(meta.get("regime", "") or "")
        bad_context = signal_market_state in bad_states
        if (not bad_context) and _safe_bool(getattr(cfg, "V813_GLOBAL_SHORT_REQUIRE_BEAR_REGIME", True), True) and signal_regime != "bear":
            bad_context = True
        if bad_context:
            trade_risk_mult *= _safe_float(getattr(cfg, "V813_GLOBAL_SHORT_BAD_MARKET_MULT", 0.72), 0.72)
            if not _safe_bool(meta.get("strong_setup", False), False):
                trade_risk_mult *= _safe_float(getattr(cfg, "V813_GLOBAL_SHORT_WEAK_SETUP_MULT", 0.90), 0.90)

    if enable_legacy_v812 and _safe_bool(getattr(cfg, "V812_GLOBAL_SHORT_RISK_ENABLED", False), False):
        trade_risk_mult *= _safe_float(getattr(cfg, "V812_GLOBAL_SHORT_BASE_MULT", 1.0), 1.0)
        bad_states = set(getattr(cfg, "V812_GLOBAL_SHORT_BAD_MARKET_STATES", ["chop", "flat", "range"]) or ["chop", "flat", "range"])
        signal_market_state = str(meta.get("market_state", market_state_fallback) or market_state_fallback or "")
        if signal_market_state in bad_states:
            trade_risk_mult *= _safe_float(getattr(cfg, "V812_GLOBAL_SHORT_BAD_MARKET_MULT", 0.82), 0.82)
        elif _safe_bool(getattr(cfg, "V812_GLOBAL_SHORT_REQUIRE_BEAR_REGIME", True), True) and str(meta.get("regime", "") or "") != "bear":
            trade_risk_mult *= _safe_float(getattr(cfg, "V812_GLOBAL_SHORT_BAD_MARKET_MULT", 0.82), 0.82)
        if not _safe_bool(meta.get("strong_setup", False), False):
            trade_risk_mult *= _safe_float(getattr(cfg, "V812_GLOBAL_SHORT_WEAK_SETUP_MULT", 0.90), 0.90)

    return trade_risk_mult
