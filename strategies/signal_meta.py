"""Typed helpers for strategy signal metadata.

This module is intentionally small and dependency-light.  It centralizes the
shape of `last_signal_meta` so the strategy does not rebuild slightly different
metadata dictionaries in multiple branches.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass(slots=True)
class SignalMeta:
    signal: Optional[str] = None
    trade_type: Optional[str] = None
    risk_multiplier: float = 1.0
    execution_risk_multiplier: float = 1.0
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = {
            "signal": self.signal,
            "trade_type": self.trade_type,
            "risk_multiplier": float(self.risk_multiplier),
            "execution_risk_multiplier": float(self.execution_risk_multiplier),
        }
        data.update(self.extra)
        return data


def empty_signal_meta() -> dict[str, Any]:
    """Return the canonical empty signal metadata dictionary."""
    return SignalMeta().to_dict()


def build_signal_meta(
    *,
    signal: Optional[str],
    trade_type: Optional[str],
    risk_multiplier: float = 1.0,
    execution_risk_multiplier: Optional[float] = None,
    **extra: Any,
) -> dict[str, Any]:
    """Build normalized signal metadata without changing strategy behavior."""
    exec_risk = float(risk_multiplier if execution_risk_multiplier is None else execution_risk_multiplier)
    return SignalMeta(
        signal=signal,
        trade_type=trade_type,
        risk_multiplier=float(risk_multiplier),
        execution_risk_multiplier=exec_risk,
        extra=dict(extra),
    ).to_dict()
