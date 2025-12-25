import math
import pandas as pd

async def fetch_klines_async(client, symbol: str, interval: str, limit: int = 200) -> pd.DataFrame:
    """Асинхронная обёртка над client.get_klines.

    Возвращает DataFrame с колонками:
    open_time, open, high, low, close, volume
    """
    raw = await client.get_klines(symbol=symbol, interval=interval, limit=limit)
    if not raw:
        return pd.DataFrame(columns=["open_time","open","high","low","close","volume"])

    df = pd.DataFrame(raw, columns=[
        "open_time","open","high","low","close","volume",
        "close_time","qav","num_trades","taker_base","taker_quote","ignore",
    ])
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
    for col in ["open","high","low","close","volume"]:
        df[col] = df[col].astype(float)
    return df[["open_time","open","high","low","close","volume"]]

def round_down(value: float, step: float) -> float:
    if step <= 0:
        return float(value)
    return math.floor(value / step) * step
