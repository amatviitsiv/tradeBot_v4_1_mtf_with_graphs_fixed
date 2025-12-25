"""MTF backtest runner: H1 тренд + M15 breakout.

Использует:
- <SYMBOL>_1h.csv  для HTF-индикаторов
- <SYMBOL>_15m.csv для LTF (основной таймфрейм бэктеста)

Стратегия: config.STRATEGY_NAME = "mtf_breakout".

Запуск:
    python backtest/run_backtest_mtf.py
"""

import os
import sys
import time
from typing import Dict

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.append(ROOT)

import config as cfg  # noqa: E402
from backtest.backtester_full import Backtester  # noqa: E402
from indicators import compute_indicators  # noqa: E402

DATA_DIR = os.path.join(ROOT, "data")


def _load_csv(path: str) -> pd.DataFrame:
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    df = pd.read_csv(path)
    # нормализуем имена колонок
    df.columns = [c.lower() for c in df.columns]
    # приводим open_time к datetime, если есть
    if "open_time" in df.columns:
        df["open_time"] = pd.to_datetime(df["open_time"])
        df = df.sort_values("open_time").reset_index(drop=True)
    return df


def load_mtf_symbol(symbol: str) -> pd.DataFrame:
    """Собираем MTF DataFrame для символа.

    HTF = 1h, LTF = 15m.

    Возвращаем DataFrame по LTF (M15) с добавленными колонками HTF_*.
    """
    path_h1 = os.path.join(DATA_DIR, f"{symbol}_1h.csv")
    path_15m = os.path.join(DATA_DIR, f"{symbol}_15m.csv")

    df_15m = _load_csv(path_15m)
    df_1h = _load_csv(path_h1)

    # Проверим минимальный набор колонок
    for need in ("open", "high", "low", "close", "volume"):
        if need not in df_15m.columns:
            raise ValueError(f"{symbol}_15m.csv missing column {need}")
        if need not in df_1h.columns:
            raise ValueError(f"{symbol}_1h.csv missing column {need}")

    # Считаем индикаторы на HTF (1h)
    df_1h_ind = compute_indicators(df_1h.copy())

    # Ставим open_time индексом и растягиваем по M15-времени
    if "open_time" not in df_1h_ind.columns or "open_time" not in df_15m.columns:
        raise ValueError("Both HTF and LTF data must have open_time column for MTF mode")

    df_1h_ind = df_1h_ind.set_index("open_time")
    df_15m_idx = df_15m.set_index("open_time")

    df_1h_sync = df_1h_ind.reindex(df_15m_idx.index, method="pad")

    # Выберем ключевые HTF-индикаторы и префиксуем их
    htf_cols = [
        "SMA_TREND",
        "EMA20",
        "EMA50",
        "EMA200",
        "ATR",
        "ADX",
        "RSI",
    ]
    for col in htf_cols:
        hcol = f"HTF_{col}"
        if col in df_1h_sync.columns:
            df_15m_idx[hcol] = df_1h_sync[col]
        else:
            df_15m_idx[hcol] = pd.NA

    df_out = df_15m_idx.reset_index()  # вернём open_time как колонку
    return df_out


def main():
    open("equity_curve.csv", "w").close()
    # В MTF-режиме принудительно используем mtf_breakout
    setattr(cfg, "STRATEGY_NAME", "mtf_breakout")

    symbols = getattr(cfg, "FUTURES_SYMBOLS", None) or getattr(cfg, "SYMBOLS", [])
    if not symbols:
        symbols = ["BTCUSDT"]

    data: Dict[str, pd.DataFrame] = {}
    max_len = 0

    print(f"DATA_DIR: {DATA_DIR}")
    print(f"Symbols (MTF): {symbols}")

    for sym in symbols:
        try:
            df_sym = load_mtf_symbol(sym)
        except Exception as e:
            print(f"[WARN] Cannot load MTF data for {sym}: {e}")
            continue
        if len(df_sym) == 0:
            print(f"[WARN] Empty data for {sym}, skip")
            continue
        data[sym] = df_sym
        max_len = max(max_len, len(df_sym))

    if not data:
        print("No MTF data loaded, abort.")
        return

    history = int(getattr(cfg, "BACKTEST_HISTORY", 300))

    bt = Backtester(data)

    print(f"History: {history}")
    print(f"Max_len: {max_len}")
    print(f"Loop count: {max_len - history}")

    t0 = time.time()
    result = bt.run()
    dt = time.time() - t0

    print(f"Backtest (MTF) finished in {dt:.1f}s")
    print("=== BACKTEST RESULTS (MTF) ===")
    print(f"PNL: {result['total_pnl']:.4f} USDT")
    print(f"ROI: {result['roi']:.4f} %")
    print(f"MaxDD: {result['max_drawdown']:.4f} %")
    # === Plot equity curve ===
    try:
        import matplotlib.pyplot as plt
        eq = result.get("equity_curve", [])
        plt.figure(figsize=(12, 6))
        plt.plot(eq, label="Equity Curve", linewidth=1.5)
        plt.title("Equity Curve (MTF Backtest)")
        plt.xlabel("Bars")
        plt.ylabel("Balance (USDT)")
        plt.grid(True, alpha=0.3)
        plt.legend()
        plt.tight_layout()
        out_path = "equity_curve_mtf.png"
        plt.savefig(out_path, dpi=200)
        print("[BACKTEST] Equity curve saved to", out_path)
    except Exception as e:
        print("[BACKTEST] Plotting failed:", e)



if __name__ == "__main__":
    main()

