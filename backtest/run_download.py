import asyncio
from historical_data_loader_v2 import HistoricalDataLoader

YEAR = 2024

SYMBOLS = [
    "BTCUSDT"
]

INTERVALS = [
    "15m",
    "1h",
]

DATA_DIR = "data"
MAX_CONCURRENCY = 12
USE_FAST_MODE = True  # True = Binance Vision zip, False = Binance API


async def main():
    loader = HistoricalDataLoader(
        data_dir=DATA_DIR,
        max_concurrency=MAX_CONCURRENCY,
    )

    if USE_FAST_MODE:
        results = await loader.download_many_fast(SYMBOLS, INTERVALS, YEAR)
    else:
        results = []
        for symbol in SYMBOLS:
            for interval in INTERVALS:
                result = await loader.download_year_via_api(symbol, interval, YEAR)
                results.append(result)
                print(
                    f"[API] {symbol} {interval} {YEAR}: "
                    f"{result.rows} rows, files={result.files_downloaded}, saved={result.output_path}"
                )

    print("\n=== DOWNLOAD SUMMARY ===")
    for r in results:
        print(
            f"{r.symbol} {r.interval} {r.year} | "
            f"rows={r.rows} | files={r.files_downloaded} | {r.output_path}"
        )


if __name__ == "__main__":
    asyncio.run(main())