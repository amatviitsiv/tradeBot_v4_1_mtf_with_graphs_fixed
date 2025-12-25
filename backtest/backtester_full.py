import numpy as np
import pandas as pd
from typing import Dict, Optional

import config as cfg
from indicators import compute_indicators
from strategy import signal_from_indicators
from risk import RiskManager
from position import PositionState as Position


class Backtester:
    """Бэктестер фьючерсной стратегии с профессиональной логикой выхода.

    Особенности:
    * торгуем только фьючерсами USDT-M
    * допускаем как LONG, так и SHORT (по сигналам "buy"/"sell")
    * не более cfg.MAX_OPEN_POSITIONS одновременных позиций
    * размер позиции считается из RISK_PER_TRADE, ATR и плеча
    * SL/TP/трейлинг основаны на ATR-множителях:
      - ATR_SL_MULT
      - ATR_TP_MULT_1
      - ATR_TS_MULT
    * возможен частичный выход по TP1 (0.5 позиции)
    """

    def __init__(self, data: Dict[str, pd.DataFrame]):
        """data[symbol] = DataFrame: open, high, low, close, volume"""
        self.raw_data = data
        self.risk = RiskManager()
        self.initial_balance = float(getattr(cfg, "INITIAL_BALANCE_USDT", 5000.0))
        self.fee_rate = float(getattr(cfg, "FUTURES_FEE_RATE", 0.0004))

    # ------------------------------------------------------------------
    def _prepare(self) -> Dict[str, pd.DataFrame]:
        out: Dict[str, pd.DataFrame] = {}
        for sym, df in self.raw_data.items():
            if df is None or df.empty:
                continue
            need_cols = {"open", "high", "low", "close", "volume"}
            if not need_cols.issubset(df.columns):
                df2 = df.copy()
                for col in ["open", "high", "low", "close", "volume"]:
                    df2[col] = df2[col].astype(float)
                df = df2[["open", "high", "low", "close", "volume"]].copy()
            out[sym] = compute_indicators(df)
        return out

    # ------------------------------------------------------------------
    def run(self) -> Dict[str, float]:
        data = self._prepare()
        if not data:
            return {"total_pnl": 0.0, "roi": 0.0, "max_drawdown": 0.0}

        symbols = sorted(data.keys())
        max_len = max(len(df) for df in data.values())
        warmup = min(200, max_len - 1)

        positions: Dict[str, Optional[Position]] = {s: None for s in symbols}
        balance = self.initial_balance
        equity_curve = []

        risk_per_trade = float(getattr(cfg, "RISK_PER_TRADE", 0.01))
        leverage = int(getattr(cfg, "FUTURES_LEVERAGE_DEFAULT", 5))
        max_positions = int(getattr(cfg, "MAX_OPEN_POSITIONS", 3))

        atr_sl_mult = float(getattr(cfg, "ATR_SL_MULT", 4.0))
        atr_tp_mult_1 = float(getattr(cfg, "ATR_TP_MULT_1", 8.0))
        atr_ts_mult = float(getattr(cfg, "ATR_TS_MULT", 4.0))

        # основной цикл по времени
        for i in range(warmup, max_len):
            prices: Dict[str, float] = {}
            atrs: Dict[str, float] = {}
            df_slices: Dict[str, pd.DataFrame] = {}

            for sym in symbols:
                df = data[sym]
                if i >= len(df):
                    continue
                row = df.iloc[i]
                prices[sym] = float(row["close"])
                atrs[sym] = float(row.get("ATR", 0.0))
                df_slices[sym] = df.iloc[: i + 1]

            if not prices:
                continue

            # считаем equity: баланс + плавающий PnL по открытым позициям
            equity = balance
            for sym, pos in positions.items():
                if pos is None:
                    continue
                price = prices.get(sym)
                if price is None:
                    continue
                if pos.side == "long":
                    pnl = (price - pos.entry_price) * pos.qty
                else:  # short
                    pnl = (pos.entry_price - price) * pos.qty
                equity += pnl
            equity_curve.append(equity)

            with open("equity_curve.csv", "a") as f:
                f.write(f"{equity}\n")

            # --- управление открытыми позициями ---
            for sym, pos in list(positions.items()):
                if pos is None:
                    continue
                price = prices.get(sym)
                atr = atrs.get(sym, 0.0)
                df_slice = df_slices.get(sym)
                if price is None or atr <= 0 or df_slice is None:
                    continue

                # 1) Жёсткий SL
                if pos.stop_loss is not None:
                    if pos.side == "long" and price <= pos.stop_loss:
                        balance = self._close_position(balance, sym, pos, price)
                        positions[sym] = None
                        continue
                    if pos.side == "short" and price >= pos.stop_loss:
                        balance = self._close_position(balance, sym, pos, price)
                        positions[sym] = None
                        continue

                # 2) Первая цель по прибыли (частичный выход + перевод в безубыток + включение трейлинга)
                if pos.tp1 is not None:
                    if pos.side == "long" and price >= pos.tp1:
                        balance = self._close_fraction(balance, sym, pos, price, fraction=0.5)
                        pos.stop_loss = pos.entry_price
                        new_ts = price - atr_ts_mult * atr
                        if pos.trailing_stop is None or new_ts > pos.trailing_stop:
                            pos.trailing_stop = new_ts
                        pos.tp1 = None
                    elif pos.side == "short" and price <= pos.tp1:
                        balance = self._close_fraction(balance, sym, pos, price, fraction=0.5)
                        pos.stop_loss = pos.entry_price
                        new_ts = price + atr_ts_mult * atr
                        if pos.trailing_stop is None or new_ts < pos.trailing_stop:
                            pos.trailing_stop = new_ts
                        pos.tp1 = None

                # 3) Трейлинг
                if pos.trailing_stop is not None:
                    if pos.side == "long":
                        new_ts = price - atr_ts_mult * atr
                        if new_ts > pos.trailing_stop:
                            pos.trailing_stop = new_ts
                        if price <= pos.trailing_stop:
                            balance = self._close_position(balance, sym, pos, price)
                            positions[sym] = None
                            continue
                    else:  # short
                        new_ts = price + atr_ts_mult * atr
                        if new_ts < pos.trailing_stop:
                            pos.trailing_stop = new_ts
                        if price >= pos.trailing_stop:
                            balance = self._close_position(balance, sym, pos, price)
                            positions[sym] = None
                            continue


                # 3.5) Ограничение максимального времени жизни позиции (тайм-стоп)
                # Для MTF-стратегии считаем возраст позиции в барах LTF (индекс i - open_time),
                # и принудительно закрываем, если он превышает порог.
                mtf_max_bars = int(getattr(cfg, "MTF_MAX_BARS_IN_POSITION", 0) or 0)
                strategy_name = str(getattr(cfg, "STRATEGY_NAME", "htf_breakout")).lower()
                if mtf_max_bars > 0 and strategy_name in {"mtf_breakout", "mtf"}:
                    try:
                        age_bars = int(i - pos.open_time)
                    except Exception:
                        age_bars = 0
                    if age_bars >= mtf_max_bars:
                        balance = self._close_position(balance, sym, pos, price)
                        positions[sym] = None
                        continue

                # 4) Обратный сигнал стратегии полностью закрывает позицию
                sig = signal_from_indicators(df_slice)
                if pos.side == "long" and sig == "sell":
                    balance = self._close_position(balance, sym, pos, price)
                    positions[sym] = None
                    continue
                if pos.side == "short" and sig == "buy":
                    balance = self._close_position(balance, sym, pos, price)
                    positions[sym] = None
                    continue

            # пересчитываем equity после возможных закрытий
            equity = balance
            for sym, pos in positions.items():
                if pos is None:
                    continue
                price = prices.get(sym)
                if price is None:
                    continue
                if pos.side == "long":
                    pnl = (price - pos.entry_price) * pos.qty
                else:
                    pnl = (pos.entry_price - price) * pos.qty
                equity += pnl

            # --- ограничение по количеству одновременных позиций ---
            open_count = sum(1 for p in positions.values() if p is not None)

            # Для MTF-стратегии можно ввести отдельный, более строгий лимит MTF_MAX_OPEN_POSITIONS.
            strategy_name = str(getattr(cfg, "STRATEGY_NAME", "htf_breakout")).lower()
            mtf_max_pos = int(getattr(cfg, "MTF_MAX_OPEN_POSITIONS", max_positions))
            if strategy_name in {"mtf_breakout", "mtf"}:
                eff_max_positions = min(max_positions, mtf_max_pos)
            else:
                eff_max_positions = max_positions

            can_open_more = open_count < eff_max_positions

            # --- открытие новых позиций по сигналам ---
            for sym in symbols:
                if not can_open_more:
                    break
                if positions[sym] is not None:
                    continue
                price = prices.get(sym)
                atr = atrs.get(sym, 0.0)
                df_slice = df_slices.get(sym)
                if price is None or atr <= 0 or df_slice is None:
                    continue

                signal = signal_from_indicators(df_slice)
                if signal not in {"buy", "sell"}:
                    continue

                side = "long" if signal == "buy" else "short"

                # расстояние до стопа в процентах
                stop_distance_pct = atr_sl_mult * atr / price * 100.0
                if stop_distance_pct <= 0:
                    continue

                notional, qty = self.risk.calc_futures_size_from_risk(
                    equity=equity,
                    price=price,
                    stop_distance_pct=stop_distance_pct,
                    risk_per_trade=risk_per_trade,
                    leverage=leverage,
                )
                if notional <= 0 or qty <= 0:
                    continue

                if side == "long":
                    stop_loss = price - atr_sl_mult * atr
                    tp1 = price + atr_tp_mult_1 * atr
                else:
                    stop_loss = price + atr_sl_mult * atr
                    tp1 = price - atr_tp_mult_1 * atr

                positions[sym] = Position(
                    symbol=sym,
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
                open_count += 1
                can_open_more = open_count < max_positions

        # Закрываем всё по последней цене
        last_prices: Dict[str, float] = {}
        for sym, df in data.items():
            if df is None or df.empty:
                continue
            last_prices[sym] = float(df.iloc[-1]["close"])

        for sym, pos in positions.items():
            if pos is None:
                continue
            price = last_prices.get(sym)
            if price is None:
                continue
            balance = self._close_position(balance, sym, pos, price)

        total_pnl = balance - self.initial_balance
        roi = total_pnl / self.initial_balance * 100.0 if self.initial_balance > 0 else 0.0

        equity_arr = np.array(equity_curve, dtype=float)
        max_dd = self._max_drawdown(equity_arr) if len(equity_arr) > 1 else 0.0

        return {
            "total_pnl": float(total_pnl),
            "roi": float(roi),
            "max_drawdown": float(max_dd),
            "equity_curve": equity_curve,
        }

    # ------------------------------------------------------------------
    def _close_fraction(self, balance: float, sym: str, pos: Position, price: float, fraction: float) -> float:
        """Закрыть часть позиции (fraction от qty), вернуть новый баланс и скорректировать позицию."""
        if fraction <= 0 or fraction >= 1 or pos.qty <= 0:
            return balance

        qty_close = pos.qty * fraction
        if qty_close <= 0:
            return balance

        if pos.side == "long":
            pnl = (price - pos.entry_price) * qty_close
        else:
            pnl = (pos.entry_price - price) * qty_close

        notional_entry = pos.entry_price * qty_close
        notional_exit = price * qty_close
        fee = (notional_entry + notional_exit) * self.fee_rate
        pnl_after_fee = pnl - fee

        new_balance = balance + pnl_after_fee

        # уменьшаем позицию
        pos.qty -= qty_close
        if pos.qty < 0:
            pos.qty = 0
        pos.notional = pos.entry_price * pos.qty

        return new_balance

    # ------------------------------------------------------------------
    def _close_position(self, balance: float, sym: str, pos: Position, price: float) -> float:
        """Полное закрытие позиции и возврат обновлённого баланса с учётом комиссии."""
        if pos.qty <= 0:
            return balance

        if pos.side == "long":
            pnl = (price - pos.entry_price) * pos.qty
        else:
            pnl = (pos.entry_price - price) * pos.qty

        notional_entry = pos.entry_price * pos.qty
        notional_exit = price * pos.qty
        fee = (notional_entry + notional_exit) * self.fee_rate
        pnl_after_fee = pnl - fee
        return balance + pnl_after_fee

    # ------------------------------------------------------------------
    def _max_drawdown(self, equity: np.ndarray) -> float:
        peak = float(equity[0])
        max_dd = 0.0
        for x in equity:
            x = float(x)
            if x > peak:
                peak = x
            dd = (peak - x) / peak * 100.0
            if dd > max_dd:
                max_dd = dd
        return max_dd
