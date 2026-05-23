"""Основной LIVE-раннер для бота.

Задачи:
- инициализировать Binance DeprecatedUMFutures client,
- поднять LiveFuturesBroker,
- инициализировать StateManager и TelegramNotifier,
- запустить WebSocket-менеджер,
- в цикле по закрытию свечей обновлять данные и вызывать стратегию.

На этом этапе реализация намеренно минималистичная:
- нет фактического открытия/закрытия позиций,
- цель — каркас и инфраструктура.
"""

import asyncio
import logging
from logger_setup import setup_logging
import signal
import time
from typing import Dict, List, Optional

import pandas as pd

import config

from state_manager import StateManager
from telegram_notifier import TelegramNotifier
from broker_futures import LiveFuturesBroker
from binance_ws_manager import BinanceWSManager
from strategy import signal_from_indicators
from execution_policy import compute_trade_risk_multiplier
from position_sizing_engine import compute_position_sizing_risk_pct
from strategies import get_active_strategy
from risk import RiskManager
from position import PositionState
from indicators import compute_indicators  # type: ignore
from execution_guard import ExecutionGuard
from timeframe_preload_validator import normalize_ohlcv_frame, validate_mtf_preload
from position_management import (
    calc_tp1_price,
    maybe_move_to_break_even,
    maybe_apply_profit_lock,
    maybe_activate_trailing,
    on_tp1_hit,
    should_take_tp1,
    should_close_on_trailing,
    tp1_fraction,
    update_peak_price,
    update_trailing_stop,
    mark_tp1_bar,
    should_time_stop_after_tp1,
    should_force_exit_weak_trade,
    should_cut_adverse_trade_early,
    should_close_runner_on_stall,
)


logger = logging.getLogger(__name__)

class LiveRunner:
    def __init__(self) -> None:
        self.symbols: List[str] = getattr(config, "FUTURES_SYMBOLS", [])
        self.state = StateManager()
        self.notifier = TelegramNotifier()
        self._broker: LiveFuturesBroker | None = None
        self._ws_manager: BinanceWSManager | None = None

        # локальные хранилища данных по символам и таймфреймам (LTF/HTF)
        self._data_15m: Dict[str, pd.DataFrame] = {}
        self._data_1h: Dict[str, pd.DataFrame] = {}

        # риск-менеджер и локальный кэш позиций
        self._risk = RiskManager()
        # В памяти держим копию позиций; при старте синхронизируемся с файлом state
        self._positions: Dict[str, PositionState] = {}

        # ===== Protective layer (Step9) =====
        # флаг, запрещающий открытие новых позиций (по рискам / несоответствию позиций)
        self._trading_disabled: bool = False
        # таймстемпы открытий позиций (для лимита сделок в час)
        self._trade_timestamps: List[float] = []
        # время последнего открытия по символу (анти-луп)
        self._last_open_time: Dict[str, float] = {}
        # время последней полученной закрытой свечи по символу (legacy watchdog WS)
        self._last_kline_ts: Dict[str, float] = {}
        # время последней закрытой свечи по symbol/timeframe для production watchdog
        self._last_closed_kline_ts: Dict[str, Dict[str, float]] = {}
        # REST fallback remembers which closed candle was already injected so
        # a silent WS cannot spam duplicate strategy evaluations.
        self._last_rest_fallback_open_time: Dict[str, Dict[str, int]] = {}
        # Last closed candle open_time that was actually processed by the live strategy.
        # This prevents both REST fallback and WS from re-processing preload/current bars.
        self._last_processed_closed_open_time: Dict[str, Dict[str, int]] = {}
        # лимит сделок в час (0 = без лимита)
        self._max_trades_per_hour: int = int(getattr(config, "MAX_TRADES_PER_HOUR", 0) or 0)
        # cooldown после убыточных stop-loss по symbol + direction
        self._entry_cooldowns: Dict[str, Dict[str, float]] = {}
        self._stop_loss_streaks: Dict[str, Dict[str, int]] = {}
        self._latest_bar_open_time_ms: Dict[str, float] = {}
        self._execution_guard = ExecutionGuard(
            min_order_interval_sec=float(getattr(config, "V89_MIN_ORDER_INTERVAL_SEC", 20.0)),
            max_signal_age_sec=float(getattr(config, "V89_MAX_SIGNAL_AGE_SEC", 20 * 60.0)),
        )
        self._exchange_position_cache: Dict[str, float] = {}
        self._exchange_position_cache_ts: float = 0.0
    async def _init_broker(self) -> None:
        """Инициализация брокера и проверка API ключей."""
        api_key = getattr(config, "BINANCE_API_KEY", "") or getattr(config, "API_KEY", "")
        api_secret = getattr(config, "BINANCE_API_SECRET", "") or getattr(config, "API_SECRET", "")

        if not api_key or not api_secret:
            raise RuntimeError("API ключи Binance не заданы (BINANCE_API_KEY / API_KEY)")

        broker = await LiveFuturesBroker.create(api_key=api_key, api_secret=api_secret)
        self._broker = broker
        logger.info("[RUNNER] LiveFuturesBroker initialized")

    async def _preload_history(self) -> None:
        """Подгрузить историю (15m/1h) через REST, чтобы стратегия не ждала часы на прогрев."""
        if not getattr(config, "PRELOAD_HISTORY", True):
            logger.info("[RUNNER] preload history disabled")
            return
        if self._broker is None:
            raise RuntimeError("Broker is not initialized")

        limit_15 = int(getattr(config, "PRELOAD_15M_LIMIT", 500))
        limit_1h = int(getattr(config, "PRELOAD_1H_LIMIT", 200))

        async def fetch_df(symbol: str, interval: str, limit: int) -> pd.DataFrame:
            raw = await self._broker.client.futures_klines(symbol=symbol, interval=interval, limit=limit)
            # raw: [ [open_time, open, high, low, close, volume, close_time, qav, trades, tbbav, tbqav, ignore], ... ]
            rows = []
            now_ms = int(time.time() * 1000)
            for r in raw:
                try:
                    close_time = int(r[6])
                    # Binance REST returns the currently forming candle as the last row.
                    # Live strategy must preload only CLOSED candles; otherwise REST fallback
                    # sees the unfinished bar open_time and treats the next real close as duplicate.
                    if close_time > now_ms:
                        continue
                    rows.append({
                        "open_time": int(r[0]),
                        "open": float(r[1]),
                        "high": float(r[2]),
                        "low": float(r[3]),
                        "close": float(r[4]),
                        "volume": float(r[5]),
                    })
                except Exception:
                    return pd.DataFrame()
            df = normalize_ohlcv_frame(pd.DataFrame(rows))
            return df

        logger.info("[RUNNER] preloading history via REST: 15m=%d, 1h=%d (per symbol)", limit_15, limit_1h)
        for sym in self.symbols:
            try:
                df15 = await fetch_df(sym, "15m", limit_15)
                df1h = await fetch_df(sym, "1h", limit_1h)
                ok, reason = validate_mtf_preload(
                    df15,
                    df1h,
                    min_15m=int(getattr(config, "V89_MIN_PRELOAD_15M_ROWS", 220)),
                    min_1h=int(getattr(config, "V89_MIN_PRELOAD_1H_ROWS", 80)),
                )
                if not ok:
                    logger.warning("[RUNNER] preload validation failed for %s: %s (15m=%d 1h=%d)", sym, reason, len(df15), len(df1h))
                if not df15.empty:
                    self._data_15m[sym] = df15
                    try:
                        self._last_processed_closed_open_time.setdefault(sym, {})["15m"] = int(df15["open_time"].iloc[-1])
                    except Exception:
                        pass
                if not df1h.empty:
                    self._data_1h[sym] = df1h
                    try:
                        self._last_processed_closed_open_time.setdefault(sym, {})["1h"] = int(df1h["open_time"].iloc[-1])
                    except Exception:
                        pass
                logger.info("[RUNNER] preload %s: 15m=%d 1h=%d validation=%s", sym, len(df15), len(df1h), reason)
            except Exception as e:
                logger.exception("[RUNNER] preload failed for %s: %s", sym, e)

    async def _on_kline_15m(self, k: dict) -> None:
        """Колбек на приход новых kline M15.

        Здесь мы смотрим только на закрытые свечи (k['x'] == True),
        обновляем локальный DataFrame и запускаем логику.
        """
        if not k.get("x"):  # свеча ещё не закрыта
            return
        symbol = k.get("s")
        if not symbol:
            return
        try:
            open_time = int(k["t"])
        except Exception:
            return
        last_processed = self._last_processed_closed_open_time.setdefault(symbol, {}).get("15m")
        if last_processed is not None and open_time <= int(last_processed):
            # Duplicate or historical/preload candle. Mark liveness, but do not rerun strategy.
            self._last_closed_kline_ts.setdefault(symbol, {})["15m"] = time.time()
            logger.info("[RUNNER] duplicate/old closed candle skipped %s 15m open_time=%s last_processed=%s", symbol, open_time, last_processed)
            return
        # отметим время последней полученной свечи для watchdog
        try:
            now_ts = time.time()
            self._last_kline_ts[symbol] = now_ts
            self._last_closed_kline_ts.setdefault(symbol, {})["15m"] = now_ts
            self._last_processed_closed_open_time.setdefault(symbol, {})["15m"] = open_time
            self._last_rest_fallback_open_time.setdefault(symbol, {})["15m"] = open_time
            logger.info("[RUNNER] closed candle received %s 15m open_time=%s close=%s", symbol, open_time, k.get("c"))
        except Exception:
            pass
        df = self._data_15m.get(symbol)
        row = {
            "open_time": open_time,
            "open": float(k["o"]),
            "high": float(k["h"]),
            "low": float(k["l"]),
            "close": float(k["c"]),
            "volume": float(k["v"]),
        }
        if df is None:
            df = pd.DataFrame([row])
        else:
            df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
        self._data_15m[symbol] = normalize_ohlcv_frame(df)

        await self._run_strategy_if_ready(symbol)

    async def _on_kline_1h(self, k: dict) -> None:
        if not k.get("x"):
            return
        symbol = k.get("s")
        if not symbol:
            return
        try:
            open_time = int(k["t"])
        except Exception:
            return
        last_processed = self._last_processed_closed_open_time.setdefault(symbol, {}).get("1h")
        if last_processed is not None and open_time <= int(last_processed):
            self._last_closed_kline_ts.setdefault(symbol, {})["1h"] = time.time()
            logger.info("[RUNNER] duplicate/old closed candle skipped %s 1h open_time=%s last_processed=%s", symbol, open_time, last_processed)
            return
        try:
            now_ts = time.time()
            self._last_kline_ts[symbol] = now_ts
            self._last_closed_kline_ts.setdefault(symbol, {})["1h"] = now_ts
            self._last_processed_closed_open_time.setdefault(symbol, {})["1h"] = open_time
            self._last_rest_fallback_open_time.setdefault(symbol, {})["1h"] = open_time
            logger.info("[RUNNER] closed candle received %s 1h open_time=%s close=%s", symbol, open_time, k.get("c"))
        except Exception:
            pass
        df = self._data_1h.get(symbol)
        row = {
            "open_time": open_time,
            "open": float(k["o"]),
            "high": float(k["h"]),
            "low": float(k["l"]),
            "close": float(k["c"]),
            "volume": float(k["v"]),
        }
        if df is None:
            df = pd.DataFrame([row])
        else:
            df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
        self._data_1h[symbol] = normalize_ohlcv_frame(df)


    async def _inject_latest_closed_kline_from_rest(self, symbol: str, interval: str) -> bool:
        """Fetch the latest closed kline via REST and feed it into the normal WS handler.

        This is a live-infra fallback only. It does not change alpha logic; it
        simply prevents a half-open/silent WS from stopping candle processing.
        """
        if self._broker is None:
            return False
        if interval not in ("15m", "1h"):
            return False
        try:
            raw = await self._broker.client.futures_klines(symbol=symbol, interval=interval, limit=3)
        except Exception as e:
            logger.warning("[RUNNER] REST kline fallback failed %s %s: %s", symbol, interval, e)
            return False
        if not raw:
            return False
        now_ms = int(time.time() * 1000)
        selected = None
        for r in reversed(raw):
            try:
                close_time = int(r[6])
                if close_time <= now_ms:
                    selected = r
                    break
            except Exception:
                continue
        if selected is None:
            return False
        try:
            open_time = int(selected[0])
        except Exception:
            return False
        already = self._last_rest_fallback_open_time.setdefault(symbol, {}).get(interval)
        if already == open_time:
            return False
        last_processed = self._last_processed_closed_open_time.setdefault(symbol, {}).get(interval)
        if last_processed is not None and open_time <= int(last_processed):
            return False
        k = {
            "s": symbol,
            "i": interval,
            "t": open_time,
            "o": str(selected[1]),
            "h": str(selected[2]),
            "l": str(selected[3]),
            "c": str(selected[4]),
            "v": str(selected[5]),
            "x": True,
        }
        self._last_rest_fallback_open_time.setdefault(symbol, {})[interval] = open_time
        logger.warning(
            "[RUNNER] REST fallback injected closed candle %s %s open_time=%s close=%s",
            symbol, interval, open_time, selected[4],
        )
        if interval == "15m":
            await self._on_kline_15m(k)
        else:
            await self._on_kline_1h(k)
        return True


    async def _refresh_exchange_position_cache(self) -> Dict[str, float]:
        if self._broker is None:
            return {}
        now = time.time()
        ttl = float(getattr(config, "V89_EXCHANGE_POSITION_CACHE_TTL_SEC", 10.0))
        if self._exchange_position_cache and now - self._exchange_position_cache_ts < ttl:
            return self._exchange_position_cache
        out: Dict[str, float] = {}
        try:
            for p in await self._broker.get_positions():
                sym = str(p.get("symbol", ""))
                if not sym:
                    continue
                out[sym] = float(p.get("positionAmt", 0.0) or 0.0)
        except Exception as e:
            logger.warning("[RUNNER] exchange position sync unavailable: %s", e)
            return self._exchange_position_cache
        self._exchange_position_cache = out
        self._exchange_position_cache_ts = now
        return out

    def _attach_btc_regime_columns(self, df_15_idx: pd.DataFrame) -> pd.DataFrame:
        btc_symbol = str(getattr(config, "BTC_REGIME_FILTER_SYMBOL", "BTCUSDT"))
        df_btc_1h = self._data_1h.get(btc_symbol)
        htf_cols = ["SMA_TREND", "EMA20", "EMA50", "EMA200", "ATR", "ADX", "RSI"]

        if df_btc_1h is None or df_btc_1h.empty:
            for col in htf_cols:
                df_15_idx[f"BTC_HTF_{col}"] = pd.NA
            df_15_idx["BTC_close"] = pd.NA
            return df_15_idx

        try:
            df_btc_1h_ind = compute_indicators(df_btc_1h.copy())
            if "open_time" not in df_btc_1h_ind.columns:
                raise ValueError("BTC HTF open_time missing")
            df_btc_1h_ind = df_btc_1h_ind.set_index("open_time")
            if df_btc_1h_ind.index.has_duplicates:
                df_btc_1h_ind = df_btc_1h_ind[~df_btc_1h_ind.index.duplicated(keep="last")].sort_index()
            df_btc_sync = df_btc_1h_ind.reindex(df_15_idx.index, method="pad")
            for col in htf_cols:
                out_col = f"BTC_HTF_{col}"
                df_15_idx[out_col] = df_btc_sync[col] if col in df_btc_sync.columns else pd.NA
            df_15_idx["BTC_close"] = df_btc_sync["close"] if "close" in df_btc_sync.columns else pd.NA
        except Exception as e:
            logger.exception("[RUNNER] failed to attach BTC regime columns: %s", e)
            for col in htf_cols:
                df_15_idx[f"BTC_HTF_{col}"] = pd.NA
            df_15_idx["BTC_close"] = pd.NA
        return df_15_idx

    def _count_same_side_alt_positions(self, side: str) -> int:
        alt_symbols = set(getattr(config, "BTC_REGIME_ALT_SYMBOLS", ["ETHUSDT"]) or [])
        return sum(1 for sym, pos in self._positions.items() if pos is not None and sym in alt_symbols and pos.side == side)

    def _symbol_risk_multiplier(self, symbol: str) -> float:
        try:
            symbol = str(symbol or '').upper()
            specific = config.get_symbol_param(symbol, 'RISK_MULTIPLIER', None)
            if specific is not None:
                return max(0.0, float(specific))
            if symbol == 'BTCUSDT':
                return max(0.0, float(getattr(config, 'BTC_POSITION_RISK_MULTIPLIER', getattr(config, 'BASE_POSITION_RISK_MULTIPLIER', 1.0))))
            alt_symbols = set(getattr(config, 'BTC_REGIME_ALT_SYMBOLS', []) or [])
            if symbol in alt_symbols:
                key = symbol.replace('USDT', '') + '_POSITION_RISK_MULTIPLIER'
                return max(0.0, float(getattr(config, key, getattr(config, 'ALT_POSITION_RISK_MULTIPLIER', 0.7))))
        except Exception:
            pass
        return max(0.0, float(getattr(config, 'BASE_POSITION_RISK_MULTIPLIER', 1.0)))


    def _asset_selection_live_score(self, symbol: str) -> float:
        try:
            df15 = self._data_15m.get(symbol)
            df1h = self._data_1h.get(symbol)
            if df15 is None or df15.empty:
                return -1.0
            close = float(df15.iloc[-1].get("close", 0.0) or 0.0)
            if close <= 0:
                return -1.0
            if df1h is not None and len(df1h) >= 50:
                ind = compute_indicators(df1h.copy())
                row = ind.iloc[-1]
                adx = float(row.get("ADX", 0.0) or 0.0)
                atr = float(row.get("ATR", 0.0) or 0.0)
                ema20 = float(row.get("EMA20", close) or close)
                ema50 = float(row.get("EMA50", close) or close)
            else:
                ind = compute_indicators(df15.copy())
                row = ind.iloc[-1]
                adx = float(row.get("ADX", 0.0) or 0.0)
                atr = float(row.get("ATR", 0.0) or 0.0)
                ema20 = float(row.get("EMA20", close) or close)
                ema50 = float(row.get("EMA50", close) or close)
            atr_pct = atr / close if close > 0 else 0.0
            drift = abs(ema20 - ema50) / close if close > 0 else 0.0
            score = (adx / 50.0) + (drift * 80.0) + (atr_pct * 35.0)
            if symbol == str(getattr(config, "BTC_REGIME_FILTER_SYMBOL", "BTCUSDT")):
                score += float(getattr(config, "V29_ASSET_SELECTION_BTC_BONUS", 0.10))
            if symbol == "ETHUSDT":
                score += float(getattr(config, "V29_ASSET_SELECTION_ETH_BONUS", 0.05))
            return float(score)
        except Exception:
            return -1.0

    def _is_symbol_selected_for_new_entry(self, symbol: str) -> bool:
        if not bool(getattr(config, "V29_ASSET_SELECTION_ENABLED", False)):
            return True
        if len(getattr(self, "symbols", []) or []) <= 1:
            return True
        if bool(getattr(config, "V32_SMART_ROTATION_ENABLED", False)) and symbol in set(getattr(config, "V32_DISABLED_SYMBOLS", []) or []):
            return False
        if bool(getattr(config, "V32_SMART_ROTATION_ENABLED", False)):
            top_n = int(getattr(config, "V32_ROTATION_TOP_N", getattr(config, "V29_ASSET_SELECTION_TOP_N", len(self.symbols))) or len(self.symbols))
            min_score = float(getattr(config, "V32_ROTATION_MIN_SCORE", getattr(config, "V29_ASSET_SELECTION_MIN_SCORE", -1.0)))
            disabled = set(getattr(config, "V32_DISABLED_SYMBOLS", []) or [])
        else:
            top_n = int(getattr(config, "V29_ASSET_SELECTION_TOP_N", len(self.symbols)) or len(self.symbols))
            min_score = float(getattr(config, "V29_ASSET_SELECTION_MIN_SCORE", -1.0))
            disabled = set()
        ranked = []
        for sym in self.symbols:
            if sym in disabled:
                continue
            score = self._asset_selection_live_score(sym)
            if score >= min_score:
                ranked.append((score, sym))
        ranked.sort(key=lambda x: x[0], reverse=True)
        selected = {sym for _, sym in ranked[:max(1, top_n)]}
        if not selected and ranked:
            selected = {ranked[0][1]}
        return symbol in selected

    async def _run_strategy_if_ready(self, symbol: str) -> None:
        """Запускается при закрытии M15 свечи.

        Здесь мы:
        - строим MTF-DataFrame (H1 индикаторы растянуты по времени M15),
        - считаем LTF-индикаторы,
        - получаем сигнал стратегии,
        - управляем открытой позицией (SL/TP/трейлинг/реверс),
        - при отсутствии позиции открываем новую по сигналу с учётом риска.
        """
        df_15 = self._data_15m.get(symbol)
        df_1h = self._data_1h.get(symbol)
        if df_15 is None or df_1h is None:
            return
        if df_15.empty or df_1h.empty:
            return

        # Минимальный прогрев и валидация данных (как в бэктесте примерно)
        ok_preload, preload_reason = validate_mtf_preload(
            df_15,
            df_1h,
            min_15m=int(getattr(config, "V89_MIN_READY_15M_ROWS", 200)),
            min_1h=int(getattr(config, "V89_MIN_READY_1H_ROWS", 50)),
        )
        if not ok_preload:
            logger.debug("[RUNNER] not enough/invalid MTF data for %s: %s (len_15m=%s, len_1h=%s)", symbol, preload_reason, len(df_15), len(df_1h))
            return

        try:
            # --- строим MTF DataFrame (аналог run_backtest_mtf.py) ---
            df_1h_ind = compute_indicators(df_1h.copy())

            if "open_time" not in df_1h_ind.columns or "open_time" not in df_15.columns:
                logger.warning("[RUNNER] open_time missing for %s", symbol)
                return

            df_1h_ind = df_1h_ind.set_index("open_time")
            df_15_idx = df_15.set_index("open_time")

            if df_1h_ind.index.has_duplicates:
                logger.warning("[MTF] duplicate HTF index detected, cleaning (symbol=%s)", symbol)
                df_1h_ind = df_1h_ind[~df_1h_ind.index.duplicated(keep="last")].sort_index()

            if df_15_idx.index.has_duplicates:
                logger.warning("[MTF] duplicate LTF index detected, cleaning (symbol=%s)", symbol)
                df_15_idx = df_15_idx[~df_15_idx.index.duplicated(keep="last")].sort_index()

            df_1h_sync = df_1h_ind.reindex(df_15_idx.index, method="pad")

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
                    df_15_idx[hcol] = df_1h_sync[col]
                else:
                    df_15_idx[hcol] = pd.NA

            df_15_idx = self._attach_btc_regime_columns(df_15_idx)
            df_mtf = df_15_idx.reset_index()
            df_mtf["symbol"] = symbol
            # считаем LTF-индикаторы (ATR/RSI и др.)
            df_mtf = compute_indicators(df_mtf)
        except Exception as e:
            logger.exception("[RUNNER] failed to build MTF frame for %s: %s", symbol, e)
            return

        if df_mtf.empty:
            return

        i = len(df_mtf) - 1
        row = df_mtf.iloc[-1]
        try:
            self._latest_bar_open_time_ms[symbol] = float(row.get("open_time", 0.0) or 0.0)
        except Exception:
            self._latest_bar_open_time_ms[symbol] = 0.0

        try:
            price = float(row["close"])
            atr = float(row.get("ATR", 0.0))
        except Exception:
            return

        if price <= 0 or atr <= 0:
            return

        # --- базовые параметры из конфига ---
        risk_per_trade = float(getattr(config, "RISK_PER_TRADE", 0.01))
        leverage = int(getattr(config, "FUTURES_LEVERAGE_DEFAULT", 5))
        atr_sl_mult = float(config.get_symbol_param(symbol, "ATR_SL_MULT", getattr(config, "ATR_SL_MULT", 4.0)))

        # Текущий сигнал стратегии (по полной истории df_mtf)
        logger.debug("[RUNNER] calling strategy for %s, len(df_mtf)=%d", symbol, len(df_mtf))
        signal = signal_from_indicators(df_mtf)
        logger.debug("[RUNNER] strategy returned signal=%r for %s", signal, symbol)
        sig_meta = {}
        trade_risk_mult = 1.0
        signal_side = "long" if signal == "buy" else ("short" if signal == "sell" else None)
        try:
            sig_meta = getattr(get_active_strategy(), "last_signal_meta", {}) or {}
            trade_risk_mult = compute_trade_risk_multiplier(
                sig_meta=sig_meta,
                side=signal_side,
                cfg=config,
            )
        except Exception:
            trade_risk_mult = 1.0

        # --- оценка текущей equity и обновление пика ---
        equity = 0.0
        if self._broker is not None:
            try:
                equity = float(await self._broker.get_balance_usdt())
            except Exception as e:
                logger.exception("[RUNNER] failed to get balance for equity calc: %s", e)
                equity = 0.0

        if equity > 0:
            self.state.update_balance("USDT", free=equity, equity=equity)
            self.state.update_equity_peak(equity)

        # === Hard equity drawdown guard (Step9) ===
        dd_pct = 0.0
        try:
            peak = self.state.data.get("equity_peak")
        except Exception:
            peak = None
        try:
            hard_dd = float(getattr(config, "HARD_MAX_DRAWDOWN_PCT", 0.0) or 0.0)
        except Exception:
            hard_dd = 0.0
        if peak is not None and hard_dd > 0 and equity > 0:
            try:
                peak_val = float(peak)
                if peak_val > 0:
                    dd_pct = max(0.0, (peak_val - equity) / peak_val * 100.0)
            except Exception:
                dd_pct = 0.0
        if hard_dd > 0 and dd_pct >= hard_dd:
            if not self._trading_disabled:
                logger.error(
                    "[RUNNER] hard drawdown triggered: current DD=%.2f%%, limit=%.2f%% -> disabling new entries",
                    dd_pct,
                    hard_dd,
                )
                try:
                    self.notifier.notify_error(
                        "risk_guard",
                        f"Hard drawdown triggered: DD={dd_pct:.2f}%, limit={hard_dd:.2f}%. Trading disabled.",
                    )
                except Exception:
                    logger.exception("[RUNNER] failed to send risk_guard notification")
            self._trading_disabled = True

        pos = self._positions.get(symbol)

        # ===== 1. Управление уже открытой позицией =====
        if pos is not None:
            # Жёсткий стоп-лосс
            closed = False
            if pos.stop_loss is not None:
                if pos.side == "long" and price <= pos.stop_loss:
                    await self._close_position_live(symbol, pos, price, reason="stop_loss")
                    closed = True
                elif pos.side == "short" and price >= pos.stop_loss:
                    await self._close_position_live(symbol, pos, price, reason="stop_loss")
                    closed = True

            if closed:
                return

            update_peak_price(pos, price, i)
            maybe_move_to_break_even(pos, price, atr)
            maybe_apply_profit_lock(pos, price, atr)

            # Первая цель по прибыли: фиксируем меньшую часть раньше и оставляем хвост под тренд
            if pos.tp1 is not None and pos.qty > 0 and should_take_tp1(pos, price):
                tp1_frac = tp1_fraction(pos)
                if tp1_frac >= 1.0:
                    await self._close_position_live(symbol, pos, price, reason="tp1_full")
                    return
                await self._close_fraction_live(symbol, pos, price, fraction=tp1_frac, reason="tp1")
                on_tp1_hit(pos, price, atr)
                mark_tp1_bar(pos, i)
                self._update_position_state(symbol, pos)

            # Менее шумный трейлинг: ведём его от лучшей достигнутой цены
            maybe_activate_trailing(pos, price, atr)
            update_trailing_stop(pos, atr)
            if pos.trailing_stop is not None and pos.qty > 0 and should_close_on_trailing(pos, price):
                await self._close_position_live(symbol, pos, price, reason="trailing_stop")
                return
            self._update_position_state(symbol, pos)

            if pos.qty > 0 and should_cut_adverse_trade_early(pos, price, atr):
                await self._close_position_live(symbol, pos, price, reason="early_cut_loss")
                return

            if pos.qty > 0 and should_force_exit_weak_trade(pos, price, atr, i):
                await self._close_position_live(symbol, pos, price, reason="weak_trade_exit")
                return

            if pos.qty > 0 and should_close_runner_on_stall(pos, i):
                await self._close_position_live(symbol, pos, price, reason="runner_stall")
                return

            if pos.qty > 0 and should_time_stop_after_tp1(pos, i):
                await self._close_position_live(symbol, pos, price, reason="time_stop_after_tp1")
                return

            # Ограничение максимального времени жизни позиции (тайм-стоп)
            mtf_max_bars = int(getattr(config, "MTF_MAX_BARS_IN_POSITION", 0) or 0)
            if mtf_max_bars > 0:
                try:
                    age_bars = int(i - pos.open_time)
                except Exception:
                    age_bars = 0
                if age_bars >= mtf_max_bars:
                    await self._close_position_live(symbol, pos, price, reason="time_stop")
                    return

            # Обратный сигнал стратегии полностью закрывает позицию
            if signal in {"buy", "sell"}:
                if pos.side == "long" and signal == "sell":
                    await self._close_position_live(symbol, pos, price, reason="reverse_signal")
                    return
                if pos.side == "short" and signal == "buy":
                    await self._close_position_live(symbol, pos, price, reason="reverse_signal")
                    return

            if self._can_pyramid_position(symbol, pos, price, atr, signal, sig_meta):
                added = await self._apply_pyramid_addition_live(symbol, pos, price, atr, equity, pos.side, sig_meta, i)
                if added:
                    return

            # Если позиция открыта и не закрылась по условиям — новых входов по этому символу не делаем
            return

        # ===== 2. Открытие новой позиции по сигналу =====
        if signal not in {"buy", "sell"}:
            return

        signal_bar_open_time = row.get("open_time", None)
        guard_result = self._execution_guard.validate_signal_freshness(symbol=symbol, signal=signal, bar_open_time=signal_bar_open_time)
        if not guard_result.ok:
            logger.info("[RUNNER] execution guard rejected %s signal for %s: %s", signal, symbol, guard_result.reason)
            return
        guard_result = self._execution_guard.prevent_duplicate_signal_bar(symbol=symbol, signal=signal, bar_open_time=signal_bar_open_time)
        if not guard_result.ok:
            logger.info("[RUNNER] execution guard rejected duplicate signal for %s: %s", symbol, guard_result.reason)
            return

        if not self._is_symbol_selected_for_new_entry(symbol):
            logger.info("[RUNNER] V29 asset selection skipped new entry for %s", symbol)
            return

        side = "long" if signal == "buy" else "short"

        # cooldown после stop-loss по тому же symbol + direction
        if bool(getattr(config, "ENTRY_COOLDOWN_AFTER_STOP_ENABLED", True)):
            now_ts = max(time.time(), float(self._latest_bar_open_time_ms.get(symbol, 0.0) or 0.0) / 1000.0)
            cooldown_until = self._get_entry_cooldown_ts(symbol, side)
            if cooldown_until > now_ts:
                remain_sec = cooldown_until - now_ts
                logger.info(
                    "[RUNNER] cooldown active for %s %s: %.0fs remaining, skip entry",
                    symbol,
                    side,
                    remain_sec,
                )
                return

        # если risk guard отключил торговлю — новые позиции не открываем
        if self._trading_disabled:
            logger.info("[RUNNER] trading disabled by risk guard, skip opening %s", symbol)
            return

        # ===== trade rate limiter =====
        now_ts = time.time()
        if self._max_trades_per_hour > 0:
            # очищаем старые записи старше часа
            self._trade_timestamps = [t for t in self._trade_timestamps if now_ts - t < 3600]
            if len(self._trade_timestamps) >= self._max_trades_per_hour:
                logger.warning(
                    "[RUNNER] trade rate limit reached (%s trades/h), skip opening %s",
                    self._max_trades_per_hour,
                    symbol,
                )
                return

        # ===== anti-loop per symbol =====
        try:
            min_reopen = int(getattr(config, "MIN_REOPEN_INTERVAL_SEC", 0) or 0)
        except Exception:
            min_reopen = 0
        if min_reopen > 0:
            last_open = self._last_open_time.get(symbol)
            if last_open is not None and now_ts - last_open < min_reopen:
                logger.info(
                    "[RUNNER] anti-loop: last %s open was %.1fs ago (<%ss), skip re-open",
                    symbol,
                    now_ts - last_open,
                    min_reopen,
                )
                return

        btc_regime_cap = int(getattr(config, "BTC_REGIME_MAX_SAME_SIDE_ALT_POSITIONS", 0) or 0)
        alt_symbols = set(getattr(config, "BTC_REGIME_ALT_SYMBOLS", ["ETHUSDT"]) or [])
        if btc_regime_cap > 0 and symbol in alt_symbols:
            same_side_alt_count = self._count_same_side_alt_positions(side)
            if same_side_alt_count >= btc_regime_cap:
                logger.info(
                    "[RUNNER] BTC regime alt cap reached for %s side=%s: %s/%s",
                    symbol,
                    side,
                    same_side_alt_count,
                    btc_regime_cap,
                )
                return

        # Ограничение по количеству одновременных позиций
        open_count = sum(1 for p in self._positions.values() if p is not None)
        max_positions = int(getattr(config, "MAX_OPEN_POSITIONS", 3))
        strategy_name = str(getattr(config, "STRATEGY_NAME", "htf_breakout")).lower()
        mtf_max_pos = int(getattr(config, "MTF_MAX_OPEN_POSITIONS", max_positions))
        if strategy_name in {"mtf_breakout", "mtf"}:
            eff_max_positions = min(max_positions, mtf_max_pos)
        else:
            eff_max_positions = max_positions

        if open_count >= eff_max_positions:
            logger.info("[RUNNER] cannot open %s: max open positions reached (%s)", symbol, eff_max_positions)
            return

        if equity <= 0:
            logger.info("[RUNNER] equity<=0, skip opening %s", symbol)
            return

        trade_type = str(sig_meta.get("trade_type", "unknown") or "unknown")
        market_state = str(sig_meta.get("market_state", "unknown") or "unknown")
        initial_stop = calc_initial_stop_price(price, atr, side, symbol, None, trade_type=trade_type, market_state=market_state)
        if bool(getattr(config, "V45_USE_STRUCTURAL_STOP_IN_LIVE", False)) and trade_type == "pullback":
            try:
                v45_stop = sig_meta.get("v45_struct_stop_price")
                if v45_stop is None and isinstance(sig_meta.get("pullback_meta"), dict):
                    v45_stop = sig_meta.get("pullback_meta", {}).get("v45_struct_stop_price")
                if v45_stop is not None:
                    v45_stop = float(v45_stop)
                    if (side == "long" and v45_stop < price) or (side == "short" and v45_stop > price):
                        initial_stop = v45_stop
            except Exception:
                pass
        stop_distance_pct = abs(price - initial_stop) / price * 100.0
        if stop_distance_pct <= 0:
            logger.info("[RUNNER] invalid stop distance for %s (price=%.5f stop=%.5f)", symbol, price, initial_stop)
            return
        risk_multiplier = self._symbol_risk_multiplier(symbol)
        eff_risk_per_trade = risk_per_trade * risk_multiplier * trade_risk_mult
        try:
            peak_val = float(self.state.data.get("equity_peak") or equity or 0.0)
        except Exception:
            peak_val = float(equity or 0.0)
        try:
            sized_risk_per_trade, _v25_flags = compute_position_sizing_risk_pct(
                cfg=config,
                sig_meta=sig_meta,
                symbol=symbol,
                side=side,
                base_risk_per_trade=eff_risk_per_trade,
                equity=equity,
                equity_peak=peak_val,
            )
        except Exception:
            sized_risk_per_trade = eff_risk_per_trade
        notional, qty = self._risk.calc_futures_size_from_risk(
            equity=equity,
            price=price,
            stop_distance_pct=stop_distance_pct,
            risk_per_trade=sized_risk_per_trade,
            leverage=leverage,
        )
        if notional <= 0 or qty <= 0:
            logger.info("[RUNNER] position size too small for %s (equity=%.2f, price=%.2f, atr=%.5f)", symbol, equity, price, atr)
            return

        try:
            if self._broker is None:
                logger.error("[RUNNER] broker is not initialized, cannot open position for %s", symbol)
                return

            if bool(getattr(config, "V89_EXCHANGE_POSITION_SYNC_ENABLED", True)):
                exchange_positions = await self._refresh_exchange_position_cache()
                sync_guard = self._execution_guard.validate_local_exchange_position_sync(
                    symbol=symbol,
                    local_position_exists=symbol in self._positions and self._positions.get(symbol) is not None,
                    exchange_positions=exchange_positions,
                )
                if not sync_guard.ok:
                    logger.error("[RUNNER] execution guard blocked open for %s: %s", symbol, sync_guard.reason)
                    return
            order_side = "BUY" if side == "long" else "SELL"
            order_guard = self._execution_guard.prevent_order_burst(symbol=symbol, side=order_side, reduce_only=False)
            if not order_guard.ok:
                logger.warning("[RUNNER] execution guard blocked order for %s: %s", symbol, order_guard.reason)
                return
            res = await self._broker.create_market_order(
                symbol=symbol,
                side=order_side,
                qty=qty,
                reduce_only=False,
            )
            used_qty = float(res.get("_used_qty", qty))
            qty = used_qty
            notional = float(qty) * float(price)
        except Exception as e:
            logger.exception("[RUNNER] failed to open %s position for %s: %s", side, symbol, e)
            try:
                self.notifier.notify_order_error(symbol=symbol, side=side, qty=qty, error=str(e))
            except Exception:
                logger.exception("[RUNNER] failed to send order error notification for %s", symbol)
            return

        stop_loss = initial_stop
        tp1 = calc_tp1_price(price, atr, side, symbol)

        pos = PositionState(
            symbol=symbol,
            entry_price=price,
            qty=qty,
            notional=notional,
            side=side,
            mode="futures",
            open_time=float(i),
            stop_loss=stop_loss,
            tp1=tp1,
            tp2=None,
            peak_price=price,
            trailing_stop=None,
            be_moved=False,
            tp1_hit=False,
            trail_active=False,
            pyramid_level=0,
            trade_type=trade_type,
            market_state=market_state,
        )
        pos.tp1 = calc_tp1_price(price, atr, side, symbol, pos)
        pos.strong_setup = bool(sig_meta.get("strong_setup", False))
        pos.entry_adx_h = float(sig_meta.get("adx_h", 0.0) or 0.0)
        pos.entry_drift = float(sig_meta.get("drift", 0.0) or 0.0)
        self._positions[symbol] = pos
        self._update_position_state(symbol, pos)

        logger.info(
            "[RUNNER] OPEN %s %s qty=%.6f price=%.4f sl=%.4f tp1=%.4f (equity=%.2f)",
            side.upper(),
            symbol,
            qty,
            price,
            stop_loss,
            tp1,
            equity,
        )
        # Telegram notification about opened position
        try:
            self.notifier.notify_open_position(
                symbol=symbol,
                side=side,
                qty=qty,
                entry_price=price,
                leverage=leverage,
            )
        except Exception as e:  # pragma: no cover
            logger.exception("[RUNNER] failed to send open position notification for %s: %s", symbol, e)

        # зарегистрируем открытие в защитном слое
        try:
            open_ts = time.time()
            self._last_open_time[symbol] = open_ts
            self._trade_timestamps.append(open_ts)
        except Exception:
            logger.exception("[RUNNER] failed to register trade timestamp for %s", symbol)



    def _get_entry_cooldown_ts(self, symbol: str, side: str) -> float:
        return float((self._entry_cooldowns.get(symbol) or {}).get(side, 0.0) or 0.0)

    def _get_stop_streak(self, symbol: str, side: str) -> int:
        return int((self._stop_loss_streaks.get(symbol) or {}).get(side, 0) or 0)

    def _set_entry_cooldown(self, symbol: str, side: str, until_ts: float, stop_streak: int, reason: str | None = None) -> None:
        self._entry_cooldowns.setdefault(symbol, {})[side] = float(until_ts)
        self._stop_loss_streaks.setdefault(symbol, {})[side] = int(stop_streak)
        try:
            self.state.set_entry_cooldown(symbol, side, until_ts=until_ts, stop_streak=stop_streak, last_reason=reason)
        except Exception:
            logger.exception("[RUNNER] failed to persist entry cooldown for %s %s", symbol, side)

    def _reset_entry_cooldown_streak(self, symbol: str, side: str, keep_until_ts: bool = False) -> None:
        until_ts = self._get_entry_cooldown_ts(symbol, side) if keep_until_ts else 0.0
        self._entry_cooldowns.setdefault(symbol, {})[side] = float(until_ts)
        self._stop_loss_streaks.setdefault(symbol, {})[side] = 0
        try:
            self.state.reset_entry_cooldown_streak(symbol, side, keep_until_ts=keep_until_ts)
        except Exception:
            logger.exception("[RUNNER] failed to reset cooldown streak for %s %s", symbol, side)

    def _register_stop_loss_cooldown(self, symbol: str, side: str, bar_open_ts_ms: float, pnl: float) -> None:
        if not bool(getattr(config, "ENTRY_COOLDOWN_AFTER_STOP_ENABLED", True)):
            return
        if pnl > 0:
            if bool(getattr(config, "ENTRY_COOLDOWN_RESET_ON_NON_LOSS_EXIT", True)):
                self._reset_entry_cooldown_streak(symbol, side, keep_until_ts=False)
            return

        base_bars = int(getattr(config, "ENTRY_COOLDOWN_AFTER_STOP_BARS", 0) or 0)
        streak_threshold = int(getattr(config, "ENTRY_COOLDOWN_STREAK_THRESHOLD", 2) or 0)
        extra_bars = int(getattr(config, "ENTRY_COOLDOWN_STREAK_EXTRA_BARS", 0) or 0)
        bar_seconds = int(getattr(config, "ENTRY_COOLDOWN_BAR_SECONDS", 15 * 60) or 15 * 60)
        if base_bars <= 0 or bar_seconds <= 0:
            return

        new_streak = self._get_stop_streak(symbol, side) + 1
        cooldown_bars = base_bars
        if streak_threshold > 0 and new_streak >= streak_threshold:
            cooldown_bars += extra_bars

        until_ts = float(bar_open_ts_ms) / 1000.0 + cooldown_bars * bar_seconds
        self._set_entry_cooldown(symbol, side, until_ts=until_ts, stop_streak=new_streak, reason="stop_loss")
        logger.info(
            "[RUNNER] entry cooldown set for %s %s: bars=%s streak=%s until_ts=%.0f",
            symbol,
            side,
            cooldown_bars,
            new_streak,
            until_ts,
        )

    def _can_pyramid_position(self, symbol: str, pos: PositionState, price: float, atr: float, signal: str, sig_meta: dict) -> bool:
        if pos is None or pos.qty <= 0 or atr <= 0 or price <= 0:
            return False
        if symbol != "BTCUSDT":
            return False
        if not bool(config.get_symbol_param_bool(symbol, "BTC_PYRAMIDING_ENABLED", bool(getattr(config, "BTC_PYRAMIDING_ENABLED", False)))):
            return False
        max_adds = int(config.get_symbol_param_int(symbol, "BTC_PYRAMID_MAX_ADDS", int(getattr(config, "BTC_PYRAMID_MAX_ADDS", 1))))
        if int(getattr(pos, "pyramid_level", 0) or 0) >= max_adds:
            return False
        wanted_signal = "buy" if pos.side == "long" else "sell"
        if signal != wanted_signal:
            return False
        if bool(getattr(pos, "trail_active", False)):
            return False
        if bool(getattr(pos, "tp1_hit", False)) and not bool(config.get_symbol_param_bool(symbol, "BTC_PYRAMID_ALLOW_AFTER_TP1", bool(getattr(config, "BTC_PYRAMID_ALLOW_AFTER_TP1", True)))):
            return False
        allowed = {str(x).lower() for x in (config.get_symbol_param(symbol, "BTC_PYRAMID_ALLOWED_TRADE_TYPES", getattr(config, "BTC_PYRAMID_ALLOWED_TRADE_TYPES", ["continuation", "cont_compression", "impulse", "liquidity_reversal"])) or [])}
        trade_type = str(sig_meta.get("trade_type", "") or "").lower()
        if allowed and trade_type not in allowed:
            return False
        adx_h = float(sig_meta.get("adx_h", 0.0) or 0.0)
        drift = abs(float(sig_meta.get("drift", 0.0) or 0.0))
        progress = (price - float(pos.entry_price)) / atr if pos.side == "long" else (float(pos.entry_price) - price) / atr
        if trade_type == "liquidity_reversal":
            if not bool(config.get_symbol_param_bool(symbol, "BTC_LIQUIDITY_PYRAMID_ENABLED", True)):
                return False
            max_adds = int(config.get_symbol_param_int(symbol, "BTC_LIQUIDITY_PYRAMID_MAX_ADDS", 1))
            if int(getattr(pos, "pyramid_level", 0) or 0) >= max_adds:
                return False
            if bool(getattr(pos, "tp1_hit", False)) and not bool(config.get_symbol_param_bool(symbol, "BTC_LIQUIDITY_PYRAMID_ALLOW_AFTER_TP1", True)):
                return False
            if adx_h > float(config.get_symbol_param_float(symbol, "BTC_LIQUIDITY_PYRAMID_MAX_ADX_H", 22.5)):
                return False
            if drift > float(config.get_symbol_param_float(symbol, "BTC_LIQUIDITY_PYRAMID_MAX_DRIFT_PCT", 0.0050)):
                return False
            min_progress_atr = float(config.get_symbol_param_float(symbol, "BTC_LIQUIDITY_PYRAMID_MIN_PROGRESS_ATR", 0.22))
            return progress >= min_progress_atr
        if bool(config.get_symbol_param_bool(symbol, "BTC_PYRAMID_REQUIRE_STRONG_SETUP", bool(getattr(config, "BTC_PYRAMID_REQUIRE_STRONG_SETUP", True)))) and not bool(sig_meta.get("strong_setup", False)):
            return False
        if adx_h < float(config.get_symbol_param_float(symbol, "BTC_PYRAMID_MIN_ADX_H", float(getattr(config, "BTC_PYRAMID_MIN_ADX_H", 24.0)))):
            return False
        if drift < float(config.get_symbol_param_float(symbol, "BTC_PYRAMID_MIN_DRIFT", float(getattr(config, "BTC_PYRAMID_MIN_DRIFT", 0.0012)))):
            return False
        min_progress_atr = float(config.get_symbol_param_float(symbol, "BTC_PYRAMID_MIN_PROGRESS_ATR", float(getattr(config, "BTC_PYRAMID_MIN_PROGRESS_ATR", 0.45))))
        return progress >= min_progress_atr

    async def _apply_pyramid_addition_live(self, symbol: str, pos: PositionState, price: float, atr: float, equity: float, side: str, sig_meta: dict, bar_index: int) -> bool:
        if self._broker is None:
            return False
        leverage = int(getattr(config, "FUTURES_LEVERAGE_DEFAULT", 5))
        trade_type = str(sig_meta.get("trade_type", getattr(pos, "trade_type", "continuation")) or "continuation")
        market_state = str(sig_meta.get("market_state", getattr(pos, "market_state", "unknown")) or "unknown")
        if trade_type == "liquidity_reversal":
            risk_fraction = float(config.get_symbol_param_float(symbol, "BTC_LIQUIDITY_PYRAMID_RISK_FRACTION", 0.35))
        else:
            risk_fraction = float(config.get_symbol_param_float(symbol, "BTC_PYRAMID_RISK_FRACTION", float(getattr(config, "BTC_PYRAMID_RISK_FRACTION", 0.55))))
        initial_stop = calc_initial_stop_price(price, atr, side, symbol, pos, trade_type=trade_type, market_state=market_state)
        if bool(getattr(config, "V45_USE_STRUCTURAL_STOP_IN_LIVE", False)) and trade_type == "pullback":
            try:
                v45_stop = sig_meta.get("v45_struct_stop_price")
                if v45_stop is None and isinstance(sig_meta.get("pullback_meta"), dict):
                    v45_stop = sig_meta.get("pullback_meta", {}).get("v45_struct_stop_price")
                if v45_stop is not None:
                    v45_stop = float(v45_stop)
                    if (side == "long" and v45_stop < price) or (side == "short" and v45_stop > price):
                        initial_stop = v45_stop
            except Exception:
                pass
        stop_distance_pct = abs(price - initial_stop) / price * 100.0
        if stop_distance_pct <= 0:
            return False
        risk_multiplier = self._symbol_risk_multiplier(symbol)
        base_risk_per_trade = float(getattr(config, "RISK_PER_TRADE", 0.01))
        try:
            trade_risk_mult = compute_trade_risk_multiplier(sig_meta=sig_meta, side=side, cfg=config, market_state_fallback=market_state, enable_legacy_v812=True)
        except Exception:
            trade_risk_mult = 1.0
        eff_risk_per_trade = base_risk_per_trade * risk_multiplier * trade_risk_mult * max(0.05, risk_fraction)
        try:
            peak_val = float(self.state.data.get("equity_peak") or equity or 0.0)
        except Exception:
            peak_val = float(equity or 0.0)
        try:
            sized_risk_per_trade, _ = compute_position_sizing_risk_pct(cfg=config, sig_meta=sig_meta, symbol=symbol, side=side, base_risk_per_trade=eff_risk_per_trade, equity=equity, equity_peak=peak_val)
        except Exception:
            sized_risk_per_trade = eff_risk_per_trade
        notional, qty = self._risk.calc_futures_size_from_risk(equity=equity, price=price, stop_distance_pct=stop_distance_pct, risk_per_trade=sized_risk_per_trade, leverage=leverage)
        if notional <= 0 or qty <= 0:
            return False
        order_side = "BUY" if side == "long" else "SELL"
        try:
            res = await self._broker.create_market_order(symbol=symbol, side=order_side, qty=qty, reduce_only=False)
            used_qty = float(res.get("_used_qty", qty))
            qty = used_qty
            notional = float(qty) * float(price)
        except Exception as e:
            logger.exception("[RUNNER] failed to pyramid %s position for %s: %s", side, symbol, e)
            try:
                self.notifier.notify_order_error(symbol=symbol, side=side, qty=qty, error=str(e))
            except Exception:
                logger.exception("[RUNNER] failed to send pyramid order error notification for %s", symbol)
            return False
        old_qty = float(pos.qty)
        new_qty = old_qty + float(qty)
        if new_qty <= 0:
            return False
        pos.entry_price = ((float(pos.entry_price) * old_qty) + (float(price) * float(qty))) / new_qty
        pos.qty = new_qty
        pos.notional = float(pos.entry_price) * float(pos.qty)
        pos.stop_loss = initial_stop
        pos.tp1 = calc_tp1_price(float(pos.entry_price), atr, side, symbol, pos)
        pos.trailing_stop = None
        pos.trail_active = False
        pos.be_moved = False
        pos.peak_price = max(float(getattr(pos, "peak_price", price) or price), float(price)) if side == "long" else min(float(getattr(pos, "peak_price", price) or price), float(price))
        pos.pyramid_level = int(getattr(pos, "pyramid_level", 0) or 0) + 1
        pos.trade_type = trade_type
        pos.market_state = market_state
        try:
            pos.open_time = min(float(getattr(pos, "open_time", bar_index) or bar_index), float(bar_index))
        except Exception:
            pos.open_time = float(bar_index)
        self._update_position_state(symbol, pos)
        logger.info("[RUNNER] PYRAMID %s %s add_qty=%.6f price=%.4f new_qty=%.6f sl=%.4f tp1=%.4f level=%s", side.upper(), symbol, qty, price, pos.qty, pos.stop_loss or 0.0, pos.tp1 or 0.0, pos.pyramid_level)
        return True

    def _update_position_state(self, symbol: str, pos: PositionState | None) -> None:
        """Сохранить позицию в локальный кэш и файл состояния."""
        if pos is None:
            self._positions.pop(symbol, None)
            self.state.del_position(symbol)
        else:
            self._positions[symbol] = pos
            self.state.set_position(symbol, pos)

    async def _close_position_live(self, symbol: str, pos: PositionState, price: float, reason: str) -> None:
        """Полное закрытие позиции рыночным ордером."""
        if self._broker is None:
            logger.error("[RUNNER] broker is not initialized, cannot close position for %s", symbol)
            return
        if pos.qty <= 0:
            self._update_position_state(symbol, None)
            return

        order_side = "SELL" if pos.side == "long" else "BUY"
        qty = pos.qty
        try:
            res = await self._broker.create_market_order(
                symbol=symbol,
                side=order_side,
                qty=qty,
                reduce_only=True,
            )
            used_qty = float(res.get("_used_qty", qty))
            qty = used_qty
        except Exception as e:
            logger.exception("[RUNNER] failed to close position for %s (%s): %s", symbol, reason, e)
            try:
                self.notifier.notify_order_error(symbol=symbol, side=pos.side, qty=qty, error=str(e))
            except Exception:
                logger.exception("[RUNNER] failed to send order error notification for %s", symbol)
            return

        logger.info(
            "[RUNNER] CLOSE %s %s qty=%.6f price=%.4f reason=%s",
            pos.side.upper(),
            symbol,
            qty,
            price,
            reason,
        )

        # Telegram notification about closed position with PnL/ROE
        pnl = 0.0
        side = pos.side
        try:
            entry = float(pos.entry_price)
            exit_price = float(price)
            qty_val = float(qty)
            sign = 1.0 if side == "long" else -1.0
            pnl = (exit_price - entry) * qty_val * sign
            roe_pct = None
            notional = float(getattr(pos, "notional", 0.0) or 0.0)
            if notional > 0:
                roe_pct = pnl / notional * 100.0
            duration_str = None
            open_ts = float(getattr(pos, "open_time", 0.0) or 0.0)
            if open_ts > 0:
                now_ts = time.time()
                delta = max(0.0, now_ts - open_ts)
                mins, secs = divmod(int(delta), 60)
                hours, mins = divmod(mins, 60)
                if hours > 0:
                    duration_str = f"{hours}h {mins}m {secs}s"
                elif mins > 0:
                    duration_str = f"{mins}m {secs}s"
                else:
                    duration_str = f"{secs}s"

            # обновим реализованный PnL в состоянии
            try:
                self.state.add_realized_pnl(pnl)
            except Exception:
                logger.exception("[RUNNER] failed to update realized pnl for %s", symbol)

            self.notifier.notify_close_position(
                symbol=symbol,
                side=side,
                qty=qty_val,
                entry_price=entry,
                exit_price=exit_price,
                pnl=pnl,
                roe_pct=roe_pct,
                duration_str=duration_str,
                reason=reason,
            )
        except Exception as e:  # pragma: no cover
            logger.exception("[RUNNER] failed to send close position notification for %s: %s", symbol, e)

        try:
            bar_open_ts_ms = float(self._latest_bar_open_time_ms.get(symbol, 0.0) or 0.0)
            if reason == "stop_loss":
                self._register_stop_loss_cooldown(symbol, side, bar_open_ts_ms=bar_open_ts_ms or time.time() * 1000.0, pnl=pnl)
            elif bool(getattr(config, "ENTRY_COOLDOWN_RESET_ON_NON_LOSS_EXIT", True)):
                self._reset_entry_cooldown_streak(symbol, side, keep_until_ts=False)
        except Exception:
            logger.exception("[RUNNER] failed to update cooldown state for %s", symbol)

        self._update_position_state(symbol, None)

    async def _close_fraction_live(self, symbol: str, pos: PositionState, price: float, fraction: float, reason: str) -> None:
        """Частичное закрытие позиции (fraction от текущего qty)."""
        if self._broker is None:
            logger.error("[RUNNER] broker is not initialized, cannot close fraction for %s", symbol)
            return
        if pos.qty <= 0 or fraction <= 0 or fraction >= 1:
            return

        qty_close = pos.qty * fraction
        if qty_close <= 0:
            return

        order_side = "SELL" if pos.side == "long" else "BUY"
        try:
            res = await self._broker.create_market_order(
                symbol=symbol,
                side=order_side,
                qty=qty_close,
                reduce_only=True,
            )
            used_qty = float(res.get("_used_qty", qty_close))
            qty_close = used_qty
        except Exception as e:
            logger.exception("[RUNNER] failed to close fraction for %s (%s): %s", symbol, reason, e)
            return

        # Рассчитываем реализованный PnL по частично закрытой части и пишем в state
        try:
            entry = float(pos.entry_price)
            exit_price = float(price)
            qty_val = float(qty_close)
            side = pos.side
            sign = 1.0 if side == "long" else -1.0
            pnl = (exit_price - entry) * qty_val * sign
            roe_pct = None
            notional = float(getattr(pos, "notional", 0.0) or 0.0)
            if notional > 0:
                roe_pct = pnl / notional * 100.0

            try:
                self.state.add_realized_pnl(pnl)
            except Exception:
                logger.exception("[RUNNER] failed to update realized pnl for %s (partial)", symbol)

            try:
                self.notifier.notify_partial_close_position(
                    symbol=symbol,
                    side=side,
                    qty=qty_val,
                    entry_price=entry,
                    exit_price=exit_price,
                    pnl=pnl,
                    roe_pct=roe_pct,
                    remaining_qty=max(0.0, float(pos.qty - qty_close)),
                    reason=reason,
                )
            except Exception:
                logger.exception("[RUNNER] failed to send partial close notification for %s", symbol)
        except Exception:
            logger.exception("[RUNNER] failed to compute partial PnL for %s", symbol)

        # обновляем локальное состояние позиции
        pos.qty -= qty_close
        if pos.qty < 0:
            pos.qty = 0.0

        # нормализуем оставшееся количество по шагу биржи, чтобы не оставалось "пыли"
        try:
            pos.qty = float(self._broker._adjust_qty(symbol, float(pos.qty)))  # noqa: SLF001
        except Exception:
            pass
        if pos.qty <= 0:
            pos.qty = 0.0

        pos.notional = pos.entry_price * pos.qty
        self._update_position_state(symbol, pos)

        logger.info(
            "[RUNNER] CLOSE FRACTION %s %s qty=%.6f price=%.4f reason=%s",
            pos.side.upper(),
            symbol,
            qty_close,
            price,
            reason,
        )
    async def start(self) -> None:
        """Точка входа для live-бота."""
        self.state.load()
        # Восстанавливаем открытые позиции из файла состояния (если есть)
        try:
            saved_positions = self.state.get_positions()
            self._positions = dict(saved_positions)
            logger.info("[RUNNER] restored %s positions from state", len(self._positions))
            for sym in self.symbols:
                for side in ("long", "short"):
                    cd = self.state.get_entry_cooldown(sym, side)
                    self._entry_cooldowns.setdefault(sym, {})[side] = float(cd.get("until_ts", 0.0) or 0.0)
                    self._stop_loss_streaks.setdefault(sym, {})[side] = int(cd.get("stop_streak", 0) or 0)
        except Exception as e:
            logger.exception("[RUNNER] failed to restore positions from state: %s", e)
            self._positions = {}

        await self._init_broker()

        if self._broker is None:
            raise RuntimeError("Broker is not initialized")

        ws = BinanceWSManager(
            client=self._broker.client,
            symbols=self.symbols,
            on_kline_15m=self._on_kline_15m,
            on_kline_1h=self._on_kline_1h,
        )
        self._ws_manager = ws
        await self._preload_history()
        await ws.start()
        logger.info("[RUNNER] WebSocket manager started")

        # Heartbeat: периодически шлём сообщение в логи / Telegram
        async def heartbeat_loop() -> None:
            while True:
                try:
                    if self._broker:
                        bal = await self._broker.get_balance_usdt()
                    else:
                        bal = 0.0

                    # подсчёт открытых позиций по локальному стейту
                    try:
                        open_positions_count = sum(1 for p in self._positions.values() if p.qty > 0)
                    except Exception:
                        open_positions_count = 0

                    # watchdog по WebSocket: давно ли не было свечей
                    try:
                        stale_sec = int(getattr(config, "WS_STALE_SECONDS", 0) or 0)
                    except Exception:
                        stale_sec = 0
                    if stale_sec > 0 and self._last_kline_ts:
                        now_ts = time.time()
                        latest = max(self._last_kline_ts.values())
                        if now_ts - latest > stale_sec:
                            lag = now_ts - latest
                            logger.warning(
                                "[RUNNER] WS watchdog: no klines for %.1fs (> %ss)",
                                lag,
                                stale_sec,
                            )
                            try:
                                self.notifier.notify_error(
                                    "ws_watchdog",
                                    f"No klines received for {lag:.1f}s (limit={stale_sec}s).",
                                )
                            except Exception:
                                logger.exception("[RUNNER] failed to send ws_watchdog notification")

                    # проверка соответствия позиций биржа / локальный стейт
                    exch_positions_syms: List[str] = []
                    try:
                        if self._broker:
                            raw_positions = await self._broker.get_positions()
                            for p in raw_positions:
                                sym = p.get("symbol")
                                if sym in self.symbols:
                                    try:
                                        qty = float(p.get("positionAmt", 0.0))
                                    except Exception:
                                        qty = 0.0
                                    if qty != 0.0:
                                        exch_positions_syms.append(sym)
                    except Exception as e:
                        logger.exception("[RUNNER] heartbeat: failed to fetch exchange positions: %s", e)

                    local_syms = [s for s, p in self._positions.items() if p.qty > 0]
                    try:
                        mismatch_disable = getattr(config, "POSITION_MISMATCH_DISABLE", True)
                    except Exception:
                        mismatch_disable = True
                    if set(exch_positions_syms) != set(local_syms):
                        logger.warning(
                            "[RUNNER] position mismatch: exchange=%s, local=%s",
                            exch_positions_syms,
                            local_syms,
                        )
                        if mismatch_disable and not self._trading_disabled:
                            self._trading_disabled = True
                            try:
                                self.notifier.notify_error(
                                    "position_mismatch",
                                    f"Exchange positions {exch_positions_syms} != local {local_syms}. Trading disabled.",
                                )
                            except Exception:
                                logger.exception("[RUNNER] failed to send position_mismatch notification")

                    self.notifier.notify_heartbeat(
                        equity=bal,
                        open_positions_count=open_positions_count,
                    )
                except Exception as e:
                    logger.exception("[RUNNER] heartbeat error: %s", e)
                await asyncio.sleep(getattr(config, "EQUITY_NOTIFY_INTERVAL", 600))

        async def ws_monitor_loop() -> None:
            """Fast live watchdog for WebSocket candle delivery.

            Heartbeat notifications may run every 10 minutes, which is too slow
            to notice missing 15m/1h candles. This loop only logs/warns and does
            not change trading logic.
            """
            interval = float(getattr(config, "V89_2_WS_MONITOR_INTERVAL_SEC", 60.0) or 60.0)
            stale_15m = float(getattr(config, "V89_2_WS_STALE_15M_SEC", 20 * 60.0) or 0.0)
            stale_1h = float(getattr(config, "V89_2_WS_STALE_1H_SEC", 75 * 60.0) or 0.0)
            while True:
                try:
                    now_ts = time.time()
                    rest_poll_enabled = bool(getattr(config, "V89_4_REST_KLINE_POLL_ENABLED", True))
                    for sym in self.symbols:
                        tf_map = self._last_closed_kline_ts.get(sym, {})
                        for tf, limit in (("15m", stale_15m), ("1h", stale_1h)):
                            if limit <= 0:
                                continue
                            last = tf_map.get(tf)
                            if last is None:
                                # During startup, preload is valid but no closed WS candle may have arrived yet.
                                logger.info("[RUNNER] WS monitor: waiting first closed %s candle for %s", tf, sym)
                                if bool(getattr(config, "V89_3_REST_KLINE_FALLBACK_ENABLED", True)):
                                    await self._inject_latest_closed_kline_from_rest(sym, tf)
                                continue
                            lag = now_ts - last
                            if lag > limit:
                                logger.warning(
                                    "[RUNNER] WS stale %s %s: last closed candle %.1fs ago (> %.1fs)",
                                    sym, tf, lag, limit,
                                )
                                if bool(getattr(config, "V89_3_REST_KLINE_FALLBACK_ENABLED", True)):
                                    await self._inject_latest_closed_kline_from_rest(sym, tf)
                            elif rest_poll_enabled:
                                # v89.4: actively poll REST every monitor interval and inject only
                                # if a newer closed candle exists. This prevents a silent WS parser/
                                # callback issue from delaying 15m processing until the stale timer.
                                await self._inject_latest_closed_kline_from_rest(sym, tf)
                    await asyncio.sleep(interval)
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.exception("[RUNNER] ws_monitor error: %s", e)
                    await asyncio.sleep(interval)

        hb_task = asyncio.create_task(heartbeat_loop(), name="heartbeat-loop")
        ws_mon_task = asyncio.create_task(ws_monitor_loop(), name="ws-monitor-loop")

        # Ожидание сигналов, основная работа идёт в колбеках WS.
        try:
            while True:
                await asyncio.sleep(3600)  # просто держим процесс живым
        except asyncio.CancelledError:
            logger.info("[RUNNER] cancelled, shutting down...")
        finally:
            hb_task.cancel()
            ws_mon_task.cancel()
            if self._ws_manager:
                await self._ws_manager.stop()
            if self._broker is not None:
                await self._broker.close()
            # Notify about safe shutdown
            try:
                open_positions = len(self._positions)
            except Exception:
                open_positions = 0
            try:
                self.notifier.notify_bot_stopped(open_positions=open_positions)
            except Exception as e:  # pragma: no cover
                logger.exception("[RUNNER] failed to send bot stopped notification: %s", e)

def main() -> None:
    setup_logging()
    runner = LiveRunner()

    # Python 3.12+/3.13: get_event_loop() without an active loop is deprecated.
    # Create and own the loop explicitly so WS/reconnect behavior is deterministic.
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # Корректная обработка SIGINT/SIGTERM
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, loop.stop)
        except (NotImplementedError, RuntimeError):
            # Windows / non-main thread
            pass

    try:
        loop.run_until_complete(runner.start())
    finally:
        pending = asyncio.all_tasks(loop)
        for task in pending:
            task.cancel()
        try:
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        except Exception:
            pass
        loop.close()
        asyncio.set_event_loop(None)


if __name__ == "__main__":
    main()