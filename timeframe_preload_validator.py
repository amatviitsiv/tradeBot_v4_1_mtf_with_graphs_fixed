"""Timeframe preload and alignment validation helpers for live/backtest.

These checks are intentionally non-alpha: they only validate that LTF/HTF
history is present, sorted, unique, and warm enough before signal evaluation.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

import pandas as pd


@dataclass(frozen=True)
class TimeframeValidationResult:
    ok: bool
    reason: str = "ok"
    rows: int = 0
    last_open_time: Optional[object] = None


def normalize_ohlcv_frame(df: pd.DataFrame | None) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    out.columns = [str(c).lower() for c in out.columns]
    if "open_time" not in out.columns:
        return out
    # Preserve numeric ms in live, datetime in backtest; sorting works for both.
    out = out.dropna(subset=["open_time"]).sort_values("open_time")
    out = out.drop_duplicates(subset=["open_time"], keep="last").reset_index(drop=True)
    return out


def validate_ohlcv_frame(
    df: pd.DataFrame | None,
    *,
    min_rows: int,
    required_columns: Iterable[str] = ("open_time", "open", "high", "low", "close", "volume"),
    timeframe_name: str = "tf",
) -> TimeframeValidationResult:
    if df is None or df.empty:
        return TimeframeValidationResult(False, f"{timeframe_name}:empty", 0, None)
    cols = {str(c).lower() for c in df.columns}
    missing = [c for c in required_columns if c.lower() not in cols]
    if missing:
        return TimeframeValidationResult(False, f"{timeframe_name}:missing_columns={','.join(missing)}", len(df), None)
    if len(df) < int(min_rows):
        return TimeframeValidationResult(False, f"{timeframe_name}:not_enough_rows={len(df)}/{min_rows}", len(df), None)
    if "open_time" in df.columns:
        if df["open_time"].isna().any():
            return TimeframeValidationResult(False, f"{timeframe_name}:open_time_na", len(df), None)
        if df["open_time"].duplicated().any():
            return TimeframeValidationResult(False, f"{timeframe_name}:duplicate_open_time", len(df), None)
        try:
            if not df["open_time"].is_monotonic_increasing:
                return TimeframeValidationResult(False, f"{timeframe_name}:not_sorted", len(df), df["open_time"].iloc[-1])
        except Exception:
            pass
        last = df["open_time"].iloc[-1]
    else:
        last = None
    return TimeframeValidationResult(True, "ok", len(df), last)


def validate_mtf_preload(
    df_15m: pd.DataFrame | None,
    df_1h: pd.DataFrame | None,
    *,
    min_15m: int = 220,
    min_1h: int = 80,
) -> tuple[bool, str]:
    r15 = validate_ohlcv_frame(df_15m, min_rows=min_15m, timeframe_name="15m")
    if not r15.ok:
        return False, r15.reason
    r1h = validate_ohlcv_frame(df_1h, min_rows=min_1h, timeframe_name="1h")
    if not r1h.ok:
        return False, r1h.reason
    return True, "ok"
