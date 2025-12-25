import pandas as pd
import numpy as np
import config as cfg


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Расчёт набора индикаторов для стратегии.

    Ожидает колонки: open, high, low, close, volume.
    Добавляет:
    - SMA_TREND
    - EMA_Fast / EMA_Slow (из конфига)
    - EMA20 / EMA50 / EMA200 (для строгого тренд-фильтра)
    - MACD, MACD_Signal, MACD_Hist
    - ATR
    - ADX
    - RSI (короткий, по умолчанию 7)
    """

    if df is None or len(df) == 0:
        return df

    df = df.copy()

    for col in ["open", "high", "low", "close", "volume"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    close = df["close"]
    high = df["high"]
    low = df["low"]

    # ---------------- SMA TREND ----------------
    sma_period = int(getattr(cfg, "SMA_TREND_PERIOD", 200))
    df["SMA_TREND"] = close.rolling(sma_period).mean()

    # ---------------- EMA fast/slow (старый базовый тренд-фильтр) ----------------
    ema_fast_period = int(getattr(cfg, "EMA_FAST_PERIOD", 20))
    ema_slow_period = int(getattr(cfg, "EMA_SLOW_PERIOD", 50))
    df["EMA_Fast"] = close.ewm(span=ema_fast_period, adjust=False).mean()
    df["EMA_Slow"] = close.ewm(span=ema_slow_period, adjust=False).mean()

    # ---------------- EMA20 / EMA50 / EMA200 (для строгого тренда, вариант C) -----
    df["EMA20"] = close.ewm(span=20, adjust=False).mean()
    df["EMA50"] = close.ewm(span=50, adjust=False).mean()
    df["EMA200"] = close.ewm(span=200, adjust=False).mean()

    # ---------------- MACD (12/26/9) ---------------------------------------------
    ema_fast_macd = close.ewm(span=12, adjust=False).mean()
    ema_slow_macd = close.ewm(span=26, adjust=False).mean()
    macd = ema_fast_macd - ema_slow_macd
    macd_signal = macd.ewm(span=9, adjust=False).mean()
    df["MACD"] = macd
    df["MACD_Signal"] = macd_signal
    df["MACD_Hist"] = macd - macd_signal

    # ---------------- ATR --------------------------------------------------------
    atr_period = int(getattr(cfg, "ATR_PERIOD", 14))
    prev_close = close.shift(1)
    tr1 = (high - low).abs()
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    df["ATR"] = tr.rolling(atr_period).mean()

    # ---------------- ADX --------------------------------------------------------
    adx_period = int(getattr(cfg, "ADX_PERIOD", 14))
    up_move = high - high.shift(1)
    down_move = low.shift(1) - low

    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    tr_smooth = tr.rolling(adx_period).mean()
    plus_di = 100 * pd.Series(plus_dm, index=df.index).rolling(adx_period).mean() / tr_smooth
    minus_di = 100 * pd.Series(minus_dm, index=df.index).rolling(adx_period).mean() / tr_smooth

    dx = (plus_di - minus_di).abs() / (plus_di + minus_di).abs() * 100
    df["ADX"] = dx.rolling(adx_period).mean()

    # ---------------- RSI (короткий, по умолчанию 7) ----------------------------
    rsi_period = int(getattr(cfg, "RSI_PERIOD_SHORT", 7))
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.rolling(rsi_period).mean()
    avg_loss = loss.rolling(rsi_period).mean()
    rs = avg_gain / avg_loss
    df["RSI"] = 100 - (100 / (1 + rs))

    return df
