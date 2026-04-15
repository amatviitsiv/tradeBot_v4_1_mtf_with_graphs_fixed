from __future__ import annotations

import numpy as np
import pandas as pd


def extract_symbol(df: pd.DataFrame) -> str:
    try:
        if "symbol" in df.columns and len(df) > 0:
            return str(df["symbol"].iloc[-1])
    except Exception:
        pass
    return ""


def resolve_regime_from_values(ema20: float, ema50: float, ema200: float) -> str:
    if ema20 > ema50 > ema200:
        return "bull"
    if ema20 < ema50 < ema200:
        return "bear"
    return "none"


def calc_recent_wickiness(recent: pd.DataFrame) -> float:
    try:
        highs = recent["high"].astype(float)
        lows = recent["low"].astype(float)
        opens = recent["open"].astype(float)
        closes = recent["close"].astype(float)
        ranges = (highs - lows).replace(0.0, np.nan)
        bodies = (closes - opens).abs()
        wick_share = ((ranges - bodies).clip(lower=0.0) / ranges).replace([np.inf, -np.inf], np.nan)
        value = float(wick_share.tail(min(20, len(wick_share))).mean())
        if np.isnan(value):
            return 1.0
        return max(0.0, min(1.0, value))
    except Exception:
        return 1.0


def calc_false_breakout_ratio(recent: pd.DataFrame, lookback: int = 12) -> float:
    try:
        if len(recent) < lookback + 3:
            return 0.0
        recent = recent.tail(max(lookback + 6, 18)).copy()
        highs = recent["high"].astype(float).reset_index(drop=True)
        lows = recent["low"].astype(float).reset_index(drop=True)
        closes = recent["close"].astype(float).reset_index(drop=True)
        events = 0
        failures = 0
        for i in range(lookback, len(recent) - 1):
            prev_high = float(highs.iloc[i - lookback:i].max())
            prev_low = float(lows.iloc[i - lookback:i].min())
            close_i = float(closes.iloc[i])
            next_close = float(closes.iloc[i + 1])
            if close_i > prev_high:
                events += 1
                if next_close <= prev_high:
                    failures += 1
            elif close_i < prev_low:
                events += 1
                if next_close >= prev_low:
                    failures += 1
        return float(failures / events) if events > 0 else 0.0
    except Exception:
        return 0.0
