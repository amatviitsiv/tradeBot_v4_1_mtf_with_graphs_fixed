import pandas as pd
from binance.client import Client

def fetch_klines(symbol: str, interval: str = "1m", limit: int = 1500):
    """
    Загружает реальные свечи с Binance Spot.
    """
    client = Client()
    raw = client.get_klines(symbol=symbol, interval=interval, limit=limit)

    df = pd.DataFrame(raw, columns=[
        "open_time","open","high","low","close","volume",
        "close_time","qav","trades","tbbav","tbqav","ignore"
    ])

    df["open"] = df["open"].astype(float)
    df["high"] = df["high"].astype(float)
    df["low"] = df["low"].astype(float)
    df["close"] = df["close"].astype(float)
    df["volume"] = df["volume"].astype(float)

    df["time"] = pd.to_datetime(df["open_time"], unit="ms")

    return df[["time","open","high","low","close","volume"]]
