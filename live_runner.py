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
import os
import signal
import time
from typing import Dict, List

import pandas as pd

import config

from state_manager import StateManager
from telegram_notifier import TelegramNotifier
from broker_futures import LiveFuturesBroker
from binance_ws_manager import BinanceWSManager
from strategy import signal_from_indicators
from risk import RiskManager
from position import PositionState
from indicators import compute_indicators  # type: ignore


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
        # время последней полученной свечи по символу (watchdog WS)
        self._last_kline_ts: Dict[str, float] = {}
        # лимит сделок в час (0 = без лимита)
        self._max_trades_per_hour: int = int(getattr(config, "MAX_TRADES_PER_HOUR", 0) or 0)
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
            for r in raw:
                try:
                    rows.append({
                        "open_time": int(r[0]),
                        "open": float(r[1]),
                        "high": float(r[2]),
                        "low": float(r[3]),
                        "close": float(r[4]),
                        "volume": float(r[5]),
                    })
                except Exception:
                    continue
            df = pd.DataFrame(rows)
            return df

        logger.info("[RUNNER] preloading history via REST: 15m=%d, 1h=%d (per symbol)", limit_15, limit_1h)
        for sym in self.symbols:
            try:
                df15 = await fetch_df(sym, "15m", limit_15)
                df1h = await fetch_df(sym, "1h", limit_1h)
                if not df15.empty:
                    self._data_15m[sym] = df15
                if not df1h.empty:
                    self._data_1h[sym] = df1h
                logger.info("[RUNNER] preload %s: 15m=%d 1h=%d", sym, len(df15), len(df1h))
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
        # отметим время последней полученной свечи для watchdog
        try:
            self._last_kline_ts[symbol] = time.time()
        except Exception:
            pass
        df = self._data_15m.get(symbol)
        row = {
            "open_time": int(k["t"]),
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
        self._data_15m[symbol] = df

        await self._run_strategy_if_ready(symbol)

    async def _on_kline_1h(self, k: dict) -> None:
        if not k.get("x"):
            return
        symbol = k.get("s")
        if not symbol:
            return
        try:
            self._last_kline_ts[symbol] = time.time()
        except Exception:
            pass
        df = self._data_1h.get(symbol)
        row = {
            "open_time": int(k["t"]),
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
        self._data_1h[symbol] = df


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

        # Минимальный прогрев данных (как в бэктесте примерно)
        if len(df_15) < 200 or len(df_1h) < 50:
            logger.debug("[RUNNER] not enough data yet for %s (len_15m=%s, len_1h=%s)", symbol, len(df_15), len(df_1h))
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

            df_mtf = df_15_idx.reset_index()
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
            price = float(row["close"])
            atr = float(row.get("ATR", 0.0))
        except Exception:
            return

        if price <= 0 or atr <= 0:
            return

        # --- базовые параметры из конфига ---
        risk_per_trade = float(getattr(config, "RISK_PER_TRADE", 0.01))
        leverage = int(getattr(config, "FUTURES_LEVERAGE_DEFAULT", 5))
        atr_sl_mult = float(getattr(config, "ATR_SL_MULT", 4.0))
        atr_tp_mult_1 = float(getattr(config, "ATR_TP_MULT_1", 8.0))
        atr_ts_mult = float(getattr(config, "ATR_TS_MULT", 4.0))

        # Текущий сигнал стратегии (по полной истории df_mtf)
        signal = signal_from_indicators(df_mtf)

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

            # Первая цель по прибыли (частичный выход + перевод в безубыток + включение трейлинга)
            if pos.tp1 is not None and pos.qty > 0:
                if pos.side == "long" and price >= pos.tp1:
                    await self._close_fraction_live(symbol, pos, price, fraction=0.5, reason="tp1")
                    pos.stop_loss = pos.entry_price
                    new_ts = price - atr_ts_mult * atr
                    if pos.trailing_stop is None or new_ts > pos.trailing_stop:
                        pos.trailing_stop = new_ts
                    pos.tp1 = None
                    self._update_position_state(symbol, pos)
                elif pos.side == "short" and price <= pos.tp1:
                    await self._close_fraction_live(symbol, pos, price, fraction=0.5, reason="tp1")
                    pos.stop_loss = pos.entry_price
                    new_ts = price + atr_ts_mult * atr
                    if pos.trailing_stop is None or new_ts < pos.trailing_stop:
                        pos.trailing_stop = new_ts
                    pos.tp1 = None
                    self._update_position_state(symbol, pos)

            # Трейлинговый стоп
            if pos.trailing_stop is not None and pos.qty > 0:
                if pos.side == "long":
                    new_ts = price - atr_ts_mult * atr
                    if new_ts > pos.trailing_stop:
                        pos.trailing_stop = new_ts
                    if price <= pos.trailing_stop:
                        await self._close_position_live(symbol, pos, price, reason="trailing_stop")
                        return
                else:
                    new_ts = price + atr_ts_mult * atr
                    if new_ts < pos.trailing_stop:
                        pos.trailing_stop = new_ts
                    if price >= pos.trailing_stop:
                        await self._close_position_live(symbol, pos, price, reason="trailing_stop")
                        return
                self._update_position_state(symbol, pos)

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

            # Если позиция открыта и не закрылась по условиям — новых входов по этому символу не делаем
            return

        # ===== 2. Открытие новой позиции по сигналу =====
        if signal not in {"buy", "sell"}:
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

        stop_distance_abs = atr_sl_mult * atr
        stop_distance_pct = stop_distance_abs / price * 100.0
        notional, qty = self._risk.calc_futures_size_from_risk(
            equity=equity,
            price=price,
            stop_distance_pct=stop_distance_pct,
            risk_per_trade=risk_per_trade,
            leverage=leverage,
        )
        if notional <= 0 or qty <= 0:
            logger.info("[RUNNER] position size too small for %s (equity=%.2f, price=%.2f, atr=%.5f)", symbol, equity, price, atr)
            return

        side = "long" if signal == "buy" else "short"
        try:
            if self._broker is None:
                logger.error("[RUNNER] broker is not initialized, cannot open position for %s", symbol)
                return

            order_side = "BUY" if side == "long" else "SELL"
            await self._broker.create_market_order(
                symbol=symbol,
                side=order_side,
                qty=qty,
                reduce_only=False,
            )
        except Exception as e:
            logger.exception("[RUNNER] failed to open %s position for %s: %s", side, symbol, e)
            try:
                self.notifier.notify_order_error(symbol=symbol, side=side, qty=qty, error=str(e))
            except Exception:
                logger.exception("[RUNNER] failed to send order error notification for %s", symbol)
            return

        if side == "long":
            stop_loss = price - atr_sl_mult * atr
            tp1 = price + atr_tp_mult_1 * atr
        else:
            stop_loss = price + atr_sl_mult * atr
            tp1 = price - atr_tp_mult_1 * atr

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
            pyramid_level=0,
        )
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
            await self._broker.create_market_order(
                symbol=symbol,
                side=order_side,
                qty=qty,
                reduce_only=True,
            )
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
        try:
            entry = float(pos.entry_price)
            exit_price = float(price)
            qty_val = float(qty)
            side = pos.side
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
            await self._broker.create_market_order(
                symbol=symbol,
                side=order_side,
                qty=qty_close,
                reduce_only=True,
            )
        except Exception as e:
            logger.exception("[RUNNER] failed to close fraction for %s (%s): %s", symbol, reason, e)
            return

        # обновляем локальное состояние позиции
        pos.qty -= qty_close
        if pos.qty < 0:
            pos.qty = 0
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

        hb_task = asyncio.create_task(heartbeat_loop())

        # Ожидание сигналов, основная работа идёт в колбеках WS.
        try:
            while True:
                await asyncio.sleep(3600)  # просто держим процесс живым
        except asyncio.CancelledError:
            logger.info("[RUNNER] cancelled, shutting down...")
        finally:
            hb_task.cancel()
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

    loop = asyncio.get_event_loop()

    # Корректная обработка SIGINT/SIGTERM
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, loop.stop)
        except NotImplementedError:
            # Windows
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


if __name__ == "__main__":
    main()