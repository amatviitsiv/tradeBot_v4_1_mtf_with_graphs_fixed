"""Helpers for the top-level MTF signal orchestrator.

These helpers only prepare validated context for signal evaluation.
They do not change trading rules; they just move repetitive extraction
and validation work out of the main strategy file.
"""

from __future__ import annotations

import math
from typing import Any

import pandas as pd

HTF_REQUIRED_COLUMNS = (
    "HTF_EMA20",
    "HTF_EMA50",
    "HTF_EMA200",
    "HTF_ATR",
    "HTF_ADX",
    "HTF_RSI",
    "HTF_SMA_TREND",
)


def extract_signal_context(df: pd.DataFrame) -> dict[str, Any] | None:
    if df is None or len(df) < 100:
        return None

    last = df.iloc[-1]
    try:
        close = float(last.get("close"))
        high = float(last.get("high"))
        low = float(last.get("low"))
        volume = float(last.get("volume"))
        rsi_ltf = float(last.get("RSI"))
        atr_ltf = float(last.get("ATR"))
    except (TypeError, ValueError):
        return None

    if any(col not in df.columns for col in HTF_REQUIRED_COLUMNS):
        return None

    try:
        ema20_h = float(last["HTF_EMA20"])
        ema50_h = float(last["HTF_EMA50"])
        ema200_h = float(last["HTF_EMA200"])
        atr_h = float(last["HTF_ATR"])
        adx_h = float(last["HTF_ADX"])
        rsi_h = float(last["HTF_RSI"])
        sma_trend_h = float(last["HTF_SMA_TREND"])
    except (TypeError, ValueError):
        return None

    values = [close, high, low, volume, rsi_ltf, atr_ltf, ema20_h, ema50_h, ema200_h, atr_h, adx_h, rsi_h, sma_trend_h]
    if any(math.isnan(x) for x in values):
        return None

    return {
        "last": last,
        "close": close,
        "high": high,
        "low": low,
        "volume": volume,
        "rsi_ltf": rsi_ltf,
        "atr_ltf": atr_ltf,
        "ema20_h": ema20_h,
        "ema50_h": ema50_h,
        "ema200_h": ema200_h,
        "atr_h": atr_h,
        "adx_h": adx_h,
        "rsi_h": rsi_h,
        "sma_trend_h": sma_trend_h,
    }


def compute_drift_metrics(df: pd.DataFrame, cfg) -> dict[str, float | int]:
    drift_lookback = int(getattr(cfg, "MTF_DRIFT_LOOKBACK_BARS", 96))
    drift_min_pct = float(getattr(cfg, "MTF_DRIFT_MIN_PCT", 0.003))
    drift_strong_pct = float(getattr(cfg, "MTF_DRIFT_STRONG_TREND_PCT", 0.01))

    drift = 0.0
    if len(df) > drift_lookback + 1:
        try:
            close_series = df["close"].astype(float)
            last_price = float(close_series.iloc[-1])
            prev_price = float(close_series.iloc[-drift_lookback - 1])
            if last_price > 0 and prev_price > 0:
                drift = abs(last_price - prev_price) / last_price
        except Exception:
            drift = 0.0

    drift_h = 0.0
    htf_drift_lookback = int(getattr(cfg, "HTF_DRIFT_LOOKBACK_BARS", 16))
    if len(df) > htf_drift_lookback + 1:
        try:
            close_series_h = df["close"].astype(float)
            last_h = float(close_series_h.iloc[-1])
            prev_h = float(close_series_h.iloc[-htf_drift_lookback - 1])
            if last_h > 0 and prev_h > 0:
                drift_h = abs(last_h - prev_h) / last_h
        except Exception:
            drift_h = 0.0

    return {
        "drift": drift,
        "drift_h": drift_h,
        "drift_lookback": drift_lookback,
        "drift_min_pct": drift_min_pct,
        "drift_strong_pct": drift_strong_pct,
        "htf_drift_lookback": htf_drift_lookback,
    }
