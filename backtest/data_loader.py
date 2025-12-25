import pandas as pd
import aiohttp
import asyncio
import time

class HistoricalDataLoader:
    """
    Загрузчик исторических данных
    """

    async def fetch_binance_klines(self, session, symbol, interval, limit=1000):
        url = (
            f"https://api.binance.com/api/v3/klines?"
            f"symbol={symbol}&interval={interval}&limit={limit}"
        )

        async with session.get(url) as resp:
            data = await resp.json()

        df = pd.DataFrame(data, columns=[
            "open_time","open","high","low","close","volume",
            "close_time","qav","num_trades","tbbav","tbqav","ignore"
        ])

        df = df[["open_time","open","high","low","close","volume"]]
        df.columns = ["time","open","high","low","close","volume"]

        df["time"] = pd.to_datetime(df["time"], unit="ms")
        df = df.astype({
            "open": float, "high": float, "low": float,
            "close": float, "volume": float,
        })

        return df

    def load_csv(self, path):
        df = pd.read_csv(path)
        df["time"] = pd.to_datetime(df["time"])
        return df
