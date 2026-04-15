from __future__ import annotations

from typing import Callable


def build_short_suppression_reason(cfg, symbol: str, trade_type: str | None, regime: str, meta: dict) -> str:
    market_state = str(meta.get("market_state") or "")
    btc_meta = meta.get("btc_meta") or {}
    rs_meta = meta.get("rs_meta") or {}
    trend_quality_meta = meta.get("trend_quality_meta") or {}
    regime_gate_meta = meta.get("regime_gate_meta") or {}
    strong_setup = bool(meta.get("strong_setup", False))
    reasons = []
    bad_states = set(getattr(cfg, "V83_SHORT_BAD_MARKET_STATES", ["chop", "flat", "range", "transition"]) or [])
    if market_state in bad_states:
        reasons.append(f"market_state={market_state}")
    if bool(getattr(cfg, "V83_SHORT_REQUIRE_BEAR_REGIME", True)) and regime != "bear":
        reasons.append(f"regime={regime or 'none'}")
    min_btc = float(getattr(cfg, "V83_SHORT_MIN_BTC_SCORE", 1.12))
    btc_score = float((btc_meta.get("score", 0.0) or 0.0))
    if btc_score < min_btc:
        reasons.append(f"btc_score={btc_score:.3f}")
    max_rs = float(getattr(cfg, "V83_SHORT_MAX_RS_RATIO", 0.975))
    rs_ratio = float((rs_meta.get("ratio", 1.0) or 1.0))
    if rs_ratio > max_rs:
        reasons.append(f"rs_ratio={rs_ratio:.3f}")
    max_crosses = int(getattr(cfg, "V83_SHORT_MAX_EMA20_CROSSES", 2))
    max_wick = float(getattr(cfg, "V83_SHORT_MAX_WICKINESS", 0.52))
    min_body = float(getattr(cfg, "V83_SHORT_MIN_BODY_RATIO", 0.34))
    ema20_crosses = int(trend_quality_meta.get("ema20_crosses", 0) or 0)
    wick = float(trend_quality_meta.get("mean_wickiness", 0.0) or 0.0)
    body = float(trend_quality_meta.get("mean_body_ratio", 1.0) or 1.0)
    if ema20_crosses > max_crosses:
        reasons.append(f"ema20_crosses={ema20_crosses}")
    if wick > max_wick:
        reasons.append(f"wickiness={wick:.3f}")
    if body < min_body:
        reasons.append(f"body_ratio={body:.3f}")
    gate_reason = str(regime_gate_meta.get("reason") or "")
    bad_gate_parts = [str(x).lower() for x in (getattr(cfg, "V831_SHORT_BAD_GATE_FRAGMENTS", ["transition", "regime_mismatch", "non_directional"]) or [])]
    if gate_reason and any(part in gate_reason.lower() for part in bad_gate_parts):
        reasons.append(f"gate={gate_reason}")
    req_strong = bool(getattr(cfg, "V83_SHORT_REQUIRE_STRONG_SETUP", True))
    req_types = {str(x).lower() for x in (getattr(cfg, "V83_SHORT_REQUIRE_STRONG_SETUP_TYPES", ["impulse", "continuation", "cont_compression", "pullback"]) or [])}
    if req_strong and str(trade_type or "").lower() in req_types and not strong_setup:
        reasons.append("no_strong_setup")
    return ", ".join(reasons) or "suppressed"


def should_suppress_short_signal(cfg, symbol: str, trade_type: str | None, regime: str, meta: dict, reason_builder: Callable[[str, str | None, str, dict], str]) -> bool:
    if not bool(getattr(cfg, "V83_SHORT_SUPPRESSION_ENABLED", True)):
        return False
    allowed_symbols = set(getattr(cfg, "V83_SHORT_SUPPRESSION_SYMBOLS", ["BTCUSDT", "ETHUSDT"]) or [])
    if symbol and allowed_symbols and symbol not in allowed_symbols:
        return False
    allowed_types = {str(x).lower() for x in (getattr(cfg, "V83_SHORT_SUPPRESSION_ALLOWED_TYPES", ["impulse", "continuation", "cont_compression", "pullback"]) or [])}
    if trade_type is not None and str(trade_type).lower() not in allowed_types:
        return False
    reason = reason_builder(symbol=symbol, trade_type=trade_type, regime=regime, meta=meta)
    min_reasons = int(getattr(cfg, "V831_SHORT_MIN_REASON_COUNT", 1))
    return len([r for r in reason.split(", ") if r]) >= min_reasons
