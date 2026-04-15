import asyncio
import aiohttp
import io
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

import pandas as pd


BINANCE_API_URL = "https://api.binance.com/api/v3/klines"
BINANCE_VISION_BASE = "https://data.binance.vision/data/spot/daily/klines"


@dataclass
class DownloadStats:
    symbol: str
    interval: str
    year: int
    rows: int
    files_downloaded: int
    output_path: str


class HistoricalDataLoader:
    """
    Версия 2:
    1) умеет скачивать любой год одной командой
    2) умеет быстро качать daily zip-архивы параллельно из Binance Vision
    """

    def __init__(
        self,
        data_dir: str = "data",
        max_concurrency: int = 8,
        request_timeout_sec: int = 30,
        user_agent: str = "HistoricalDataLoaderV2/1.0",
    ):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.max_concurrency = max_concurrency
        self.request_timeout_sec = request_timeout_sec
        self.user_agent = user_agent

    def load_csv(self, path: str | Path) -> pd.DataFrame:
        df = pd.read_csv(path)
        time_col = "time" if "time" in df.columns else "open_time"
        df[time_col] = pd.to_datetime(df[time_col])
        return df

    async def download_year_fast(
        self,
        symbol: str,
        interval: str,
        year: int,
        output_path: Optional[str | Path] = None,
    ) -> DownloadStats:
        output = Path(output_path) if output_path else self.data_dir / f"{symbol}_{interval}.csv"

        all_days = pd.date_range(f"{year}-01-01", f"{year}-12-31", freq="D")
        sem = asyncio.Semaphore(self.max_concurrency)
        timeout = aiohttp.ClientTimeout(total=self.request_timeout_sec)
        headers = {"User-Agent": self.user_agent}

        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            tasks = [
                self._download_daily_zip(session, sem, symbol, interval, day)
                for day in all_days
            ]
            results = await asyncio.gather(*tasks)

        frames = [df for df in results if df is not None and not df.empty]
        if not frames:
            raise RuntimeError(f"No data downloaded for {symbol} {interval} {year}")

        df = pd.concat(frames, ignore_index=True)
        df = self._normalize_df(df)
        df.to_csv(output, index=False)

        return DownloadStats(
            symbol=symbol,
            interval=interval,
            year=year,
            rows=len(df),
            files_downloaded=len(frames),
            output_path=str(output),
        )

    def _parse_time_column(self, series: pd.Series) -> pd.Series:
        s_num = pd.to_numeric(series, errors="coerce")

        # Если колонка уже текстовая дата
        if s_num.notna().sum() == 0:
            return pd.to_datetime(series, errors="coerce")

        max_abs = s_num.dropna().abs().max()

        # Автоопределение единицы времени по масштабу
        if max_abs > 1e17:
            unit = "ns"
        elif max_abs > 1e14:
            unit = "us"
        elif max_abs > 1e11:
            unit = "ms"
        else:
            unit = "s"

        return pd.to_datetime(s_num, unit=unit, errors="coerce")

    async def download_year_via_api(
        self,
        symbol: str,
        interval: str,
        year: int,
        output_path: Optional[str | Path] = None,
    ) -> DownloadStats:
        output = Path(output_path) if output_path else self.data_dir / f"{symbol}_{interval}_{year}.csv"
        start_ms = self._ts_ms(f"{year}-01-01 00:00:00")
        end_ms = self._ts_ms(f"{year+1}-01-01 00:00:00")

        timeout = aiohttp.ClientTimeout(total=self.request_timeout_sec)
        headers = {"User-Agent": self.user_agent}
        all_frames = []
        files_downloaded = 0

        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            current = start_ms
            while current < end_ms:
                df = await self.fetch_binance_klines(
                    session=session,
                    symbol=symbol,
                    interval=interval,
                    start_time=current,
                    end_time=end_ms,
                    limit=1000,
                )

                if df.empty:
                    break

                all_frames.append(df)
                files_downloaded += 1
                current = int(df["open_time"].iloc[-1].timestamp() * 1000) + 1
                await asyncio.sleep(0.05)

        if not all_frames:
            raise RuntimeError(f"No data downloaded for {symbol} {interval} {year}")

        df = pd.concat(all_frames, ignore_index=True)
        df = self._normalize_df(df)
        df = df[df["open_time"] >= pd.Timestamp(f"{year}-01-01")]
        df = df[df["open_time"] < pd.Timestamp(f"{year+1}-01-01")]
        df.to_csv(output, index=False)

        return DownloadStats(
            symbol=symbol,
            interval=interval,
            year=year,
            rows=len(df),
            files_downloaded=files_downloaded,
            output_path=str(output),
        )

    async def download_many_fast(
        self,
        symbols: Iterable[str],
        intervals: Iterable[str],
        year: int,
    ):
        stats = []
        for symbol in symbols:
            for interval in intervals:
                result = await self.download_year_fast(symbol, interval, year)
                stats.append(result)
                print(
                    f"[FAST] {symbol} {interval} {year}: "
                    f"{result.rows} rows, files={result.files_downloaded}, saved={result.output_path}"
                )
        return stats

    async def fetch_binance_klines(
        self,
        session: aiohttp.ClientSession,
        symbol: str,
        interval: str,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
        limit: int = 1000,
    ) -> pd.DataFrame:
        params = {
            "symbol": symbol,
            "interval": interval,
            "limit": limit,
        }
        if start_time is not None:
            params["startTime"] = start_time
        if end_time is not None:
            params["endTime"] = end_time

        async with session.get(BINANCE_API_URL, params=params) as resp:
            resp.raise_for_status()
            data = await resp.json()

        if not data:
            return pd.DataFrame(columns=["open_time", "open", "high", "low", "close", "volume"])

        df = pd.DataFrame(
            data,
            columns=[
                "open_time", "open", "high", "low", "close", "volume",
                "close_time", "qav", "trades", "tbbav", "tbqav", "ignore",
            ],
        )
        return self._normalize_df(df)

    async def _download_daily_zip(
            self,
            session: aiohttp.ClientSession,
            sem: asyncio.Semaphore,
            symbol: str,
            interval: str,
            day: pd.Timestamp,
    ):
        date_str = day.strftime("%Y-%m-%d")
        url = (
            f"{BINANCE_VISION_BASE}/{symbol}/{interval}/"
            f"{symbol}-{interval}-{date_str}.zip"
        )

        async with sem:
            try:
                async with session.get(url) as resp:
                    if resp.status == 404:
                        return None
                    resp.raise_for_status()
                    raw = await resp.read()
            except Exception:
                return None

        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                csv_names = [n for n in zf.namelist() if n.endswith(".csv")]
                if not csv_names:
                    return None

                with zf.open(csv_names[0]) as f:
                    # Сначала пробуем обычное чтение
                    df = pd.read_csv(f)

                # Если open_time нет, значит CSV без header
                if "open_time" not in df.columns and "time" not in df.columns:
                    with zf.open(csv_names[0]) as f:
                        df = pd.read_csv(
                            f,
                            header=None,
                            names=[
                                "open_time", "open", "high", "low", "close", "volume",
                                "close_time", "qav", "trades", "tbbav", "tbqav", "ignore",
                            ],
                        )
        except Exception:
            return None
        return self._normalize_df(df)

    def _normalize_df(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()

        if "time" in df.columns and "open_time" not in df.columns:
            df = df.rename(columns={"time": "open_time"})

        if "num_trades" in df.columns and "trades" not in df.columns:
            df = df.rename(columns={"num_trades": "trades"})

        if "open_time" not in df.columns:
            if len(df.columns) >= 6:
                raw_cols = [
                    "open_time", "open", "high", "low", "close", "volume",
                    "close_time", "qav", "trades", "tbbav", "tbqav", "ignore",
                ]
                df.columns = raw_cols[:len(df.columns)]
            else:
                raise ValueError(f"Unexpected CSV format, columns={list(df.columns)}")

        keep_cols = [c for c in df.columns if c in {
            "open_time", "open", "high", "low", "close", "volume",
            "close_time", "qav", "trades", "tbbav", "tbqav", "ignore"
        }]
        df = df[keep_cols]

        df["open_time"] = self._parse_time_column(df["open_time"])

        for col in ["open", "high", "low", "close", "volume"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        if "close_time" in df.columns:
            df["close_time"] = pd.to_numeric(df["close_time"], errors="coerce")

        df = df.dropna(subset=["open_time", "open", "high", "low", "close", "volume"])
        df = df.sort_values("open_time").drop_duplicates(subset=["open_time"]).reset_index(drop=True)
        return df

    @staticmethod
    def _ts_ms(ts: str) -> int:
        return int(pd.Timestamp(ts, tz="UTC").timestamp() * 1000)


if __name__ == "__main__":
    async def main():
        loader = HistoricalDataLoader(data_dir="data", max_concurrency=12)

        # Пример 1: быстро скачать год через daily zip
        result = await loader.download_year_fast("ETHUSDT", "15m", 2024)
        print(result)

        # Пример 2: скачать тот же год через API
        # result = await loader.download_year_via_api("ETHUSDT", "15m", 2024)
        # print(result)

    asyncio.run(main())
