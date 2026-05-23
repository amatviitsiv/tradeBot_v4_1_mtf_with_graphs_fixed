r"""Download Binance historical MTF data for backtests.

Examples:
    python .\backtest\download_history_cli.py --symbols BTCUSDT --years 2022 2023 2024 2025 --intervals 15m 1h
    python .\backtest\download_history_cli.py --symbols BTCUSDT ETHUSDT --years 2024 --intervals 5m 15m 1h 4h --data-dir data_2024

By default it uses Binance Vision monthly zip files through HistoricalDataLoader.
If Binance Vision is unavailable, pass --api-mode to use Binance API klines.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "backtest") not in sys.path:
    sys.path.insert(0, str(ROOT / "backtest"))

from historical_data_loader_v2 import HistoricalDataLoader  # noqa: E402


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Download Binance history for MTF backtests")
    p.add_argument("--symbols", nargs="+", default=["BTCUSDT"], help="Symbols, e.g. BTCUSDT ETHUSDT")
    p.add_argument("--years", nargs="+", type=int, required=True, help="Years, e.g. 2022 2023 2024 2025")
    p.add_argument("--intervals", nargs="+", default=["15m", "1h"], help="Intervals, e.g. 5m 15m 1h 4h")
    p.add_argument("--data-dir", default="", help="Output dir. Empty = data_<year> per year")
    p.add_argument("--api-mode", action="store_true", help="Use Binance API instead of Binance Vision fast mode")
    p.add_argument("--max-concurrency", type=int, default=12)
    return p.parse_args()


async def main() -> None:
    args = parse_args()
    symbols = [s.upper().strip() for s in args.symbols if s.strip()]
    intervals = [i.strip() for i in args.intervals if i.strip()]

    all_results = []
    for year in args.years:
        data_dir = args.data_dir or f"data_{year}"
        loader = HistoricalDataLoader(data_dir=data_dir, max_concurrency=args.max_concurrency)
        if args.api_mode:
            for symbol in symbols:
                for interval in intervals:
                    r = await loader.download_year_via_api(symbol, interval, year)
                    all_results.append(r)
                    print(f"[API] {symbol} {interval} {year}: rows={r.rows} files={r.files_downloaded} saved={r.output_path}")
        else:
            results = await loader.download_many_fast(symbols, intervals, year)
            all_results.extend(results)

    print("\n=== DOWNLOAD SUMMARY ===")
    for r in all_results:
        print(f"{r.symbol} {r.interval} {r.year} | rows={r.rows} | files={r.files_downloaded} | {r.output_path}")


if __name__ == "__main__":
    asyncio.run(main())
