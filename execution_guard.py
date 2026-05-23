"""Execution protection helpers for live trading.

The guard is deliberately conservative and non-alpha: it prevents duplicate,
stale, or desynchronised order attempts before they hit the exchange.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Optional
import time


@dataclass(frozen=True)
class GuardResult:
    ok: bool
    reason: str = "ok"


class ExecutionGuard:
    def __init__(self, *, min_order_interval_sec: float = 30.0, max_signal_age_sec: float = 1200.0) -> None:
        self.min_order_interval_sec = float(min_order_interval_sec)
        self.max_signal_age_sec = float(max_signal_age_sec)
        self._last_order_ts: dict[tuple[str, str, bool], float] = {}
        self._last_signal_bar: dict[tuple[str, str], object] = {}

    def validate_signal_freshness(self, *, symbol: str, signal: str, bar_open_time: object, now_ts: Optional[float] = None) -> GuardResult:
        if signal not in {"buy", "sell"}:
            return GuardResult(False, "no_trade_signal")
        if bar_open_time is None or bar_open_time == 0:
            return GuardResult(False, "missing_signal_bar_time")
        # Live open_time is usually milliseconds. Datetime is used in backtest and not checked by live guard.
        try:
            bar_float = float(bar_open_time)
            if bar_float > 10_000_000_000:  # ms timestamp
                age = (float(now_ts or time.time()) * 1000.0 - bar_float) / 1000.0
                if age > self.max_signal_age_sec:
                    return GuardResult(False, f"stale_signal_age={age:.1f}s")
        except Exception:
            pass
        return GuardResult(True)

    def prevent_duplicate_signal_bar(self, *, symbol: str, signal: str, bar_open_time: object) -> GuardResult:
        key = (str(symbol), str(signal))
        if self._last_signal_bar.get(key) == bar_open_time:
            return GuardResult(False, "duplicate_signal_same_bar")
        self._last_signal_bar[key] = bar_open_time
        return GuardResult(True)

    def prevent_order_burst(self, *, symbol: str, side: str, reduce_only: bool = False, now_ts: Optional[float] = None) -> GuardResult:
        now = float(now_ts or time.time())
        key = (str(symbol), str(side), bool(reduce_only))
        last = self._last_order_ts.get(key)
        if last is not None and now - last < self.min_order_interval_sec:
            return GuardResult(False, f"duplicate_order_interval={now - last:.1f}s")
        self._last_order_ts[key] = now
        return GuardResult(True)

    def validate_local_exchange_position_sync(self, *, symbol: str, local_position_exists: bool, exchange_positions: Optional[Mapping[str, float]]) -> GuardResult:
        if exchange_positions is None:
            return GuardResult(True, "exchange_sync_unavailable")
        exch_qty = float(exchange_positions.get(symbol, 0.0) or 0.0)
        exch_exists = abs(exch_qty) > 0.0
        if exch_exists and not local_position_exists:
            return GuardResult(False, f"exchange_position_exists_without_local_state qty={exch_qty}")
        return GuardResult(True)
