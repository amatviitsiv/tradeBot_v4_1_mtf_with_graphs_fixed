"""Production state-machine safety helpers.

These helpers are intentionally conservative: they validate and normalize
persisted/live PositionState objects without changing trading alpha logic.
The goal is to prevent bad state after restart/reconnect from corrupting
BE/trailing/partial-close management.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Iterable

logger = logging.getLogger(__name__)


@dataclass
class StateValidationResult:
    ok: bool = True
    repaired: bool = False
    issues: list[str] = field(default_factory=list)

    def add(self, issue: str, repaired: bool = False) -> None:
        self.issues.append(issue)
        if repaired:
            self.repaired = True
        else:
            self.ok = False

    def summary(self) -> str:
        if not self.issues:
            return "ok"
        prefix = "repaired" if self.repaired and self.ok else "issues"
        return f"{prefix}: " + "; ".join(self.issues)


def _safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _is_positive(value: Any) -> bool:
    v = _safe_float(value)
    return v is not None and v > 0.0


def validate_position_state(pos: Any, *, repair: bool = True) -> StateValidationResult:
    """Validate a PositionState-like object and optionally repair safe fields.

    Repairs are limited to deterministic state-machine invariants:
    - side/mode normalization;
    - missing notional/peak values;
    - impossible BE/trailing/TP flags;
    - stop/trailing on the wrong side of entry.

    The function deliberately does not modify entry, qty or side when they are
    invalid; such states are marked not ok so live code can drop/disable them.
    """

    result = StateValidationResult()

    symbol = str(getattr(pos, "symbol", "") or "").upper()
    if not symbol:
        result.add("missing_symbol")

    side = str(getattr(pos, "side", "") or "").lower()
    if side not in {"long", "short"}:
        result.add(f"invalid_side={side!r}")

    mode = str(getattr(pos, "mode", "") or "futures").lower()
    if mode != "futures" and repair:
        setattr(pos, "mode", "futures")
        result.add(f"mode_normalized={mode!r}", repaired=True)

    entry = _safe_float(getattr(pos, "entry_price", None))
    qty = _safe_float(getattr(pos, "qty", None))
    if entry is None or entry <= 0.0:
        result.add("invalid_entry_price")
    if qty is None or qty <= 0.0:
        result.add("invalid_qty")

    notional = _safe_float(getattr(pos, "notional", None))
    if entry and qty and (notional is None or notional <= 0.0) and repair:
        setattr(pos, "notional", float(entry) * float(qty))
        result.add("notional_rebuilt", repaired=True)

    peak = _safe_float(getattr(pos, "peak_price", None))
    if entry and (peak is None or peak <= 0.0) and repair:
        setattr(pos, "peak_price", float(entry))
        result.add("peak_initialized", repaired=True)

    # Stop-loss must be on the invalidation side of entry. If not, clear it
    # rather than moving it silently; caller/exchange sync can rebuild/disable.
    stop = _safe_float(getattr(pos, "stop_loss", None))
    if entry and stop is not None:
        bad_stop = (side == "long" and stop >= entry) or (side == "short" and stop <= entry)
        if bad_stop:
            if repair:
                setattr(pos, "stop_loss", None)
                result.add("invalid_stop_loss_cleared", repaired=True)
            else:
                result.add("invalid_stop_loss")

    trailing = _safe_float(getattr(pos, "trailing_stop", None))
    if entry and trailing is not None:
        bad_trailing = (side == "long" and trailing <= 0.0) or (side == "short" and trailing <= 0.0)
        if bad_trailing and repair:
            setattr(pos, "trailing_stop", None)
            setattr(pos, "trail_active", False)
            result.add("invalid_trailing_cleared", repaired=True)

    tp1 = _safe_float(getattr(pos, "tp1", None))
    tp1_hit = bool(getattr(pos, "tp1_hit", False))
    if tp1_hit and (tp1 is None or tp1 <= 0.0) and repair:
        setattr(pos, "tp1_hit", False)
        result.add("tp1_hit_reset_without_tp1", repaired=True)

    trail_active = bool(getattr(pos, "trail_active", False))
    trailing_stop = _safe_float(getattr(pos, "trailing_stop", None))
    if trail_active and (trailing_stop is None or trailing_stop <= 0.0) and repair:
        setattr(pos, "trail_active", False)
        result.add("trail_active_reset_without_stop", repaired=True)

    # Normalize optional numeric metadata that can survive restarts.
    for attr in (
        "last_atr",
        "v52_score",
        "v60_short_score",
        "v62_rank_score",
        "v62_short_rank_score",
        "v84_quality_score",
        "entry_adx_h",
        "entry_drift",
    ):
        if hasattr(pos, attr):
            value = getattr(pos, attr)
            if value is not None:
                f = _safe_float(value)
                if f is None and repair:
                    setattr(pos, attr, None)
                    result.add(f"{attr}_cleared", repaired=True)

    try:
        level = int(getattr(pos, "pyramid_level", 0) or 0)
        if level < 0 and repair:
            setattr(pos, "pyramid_level", 0)
            result.add("negative_pyramid_level_reset", repaired=True)
    except Exception:
        if repair:
            setattr(pos, "pyramid_level", 0)
            result.add("invalid_pyramid_level_reset", repaired=True)

    return result


def validate_position_map(positions: dict[str, Any], *, repair: bool = True, drop_invalid: bool = True) -> dict[str, Any]:
    """Validate a symbol->position map and optionally drop unrecoverable states."""

    clean: dict[str, Any] = {}
    for symbol, pos in list((positions or {}).items()):
        result = validate_position_state(pos, repair=repair)
        if result.ok:
            clean[symbol] = pos
            if result.repaired:
                logger.warning("[STATE] repaired position %s: %s", symbol, result.summary())
        else:
            logger.error("[STATE] invalid position %s: %s", symbol, result.summary())
            if not drop_invalid:
                clean[symbol] = pos
    return clean
