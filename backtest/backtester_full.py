import numpy as np
import pandas as pd
from typing import Any, Dict, List, Optional

import config as cfg
from indicators import compute_indicators
from strategy import signal_from_indicators
from risk import RiskManager
from position import PositionState as Position
from position_management import (
    calc_tp1_price,
    maybe_move_to_break_even,
    maybe_activate_trailing,
    on_tp1_hit,
    should_take_tp1,
    should_close_on_trailing,
    tp1_fraction,
    update_peak_price,
    update_trailing_stop,
)


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
        self.closed_trades: List[Dict[str, Any]] = []
        self.partial_closes: List[Dict[str, Any]] = []

    # ------------------------------------------------------------------
    def _attach_btc_regime_columns(self, out: Dict[str, pd.DataFrame]) -> Dict[str, pd.DataFrame]:
        btc_symbol = str(getattr(cfg, "BTC_REGIME_FILTER_SYMBOL", "BTCUSDT"))
        btc_df = out.get(btc_symbol)
        htf_cols = ["HTF_SMA_TREND", "HTF_EMA20", "HTF_EMA50", "HTF_EMA200", "HTF_ATR", "HTF_ADX", "HTF_RSI"]
        if btc_df is None or btc_df.empty or "open_time" not in btc_df.columns:
            for sym, df in out.items():
                for col in htf_cols:
                    df[f"BTC_{col}"] = pd.NA
            return out

        btc_sync_base = btc_df.copy()
        btc_sync_base = btc_sync_base.sort_values("open_time").drop_duplicates(subset=["open_time"], keep="last")
        btc_sync_base = btc_sync_base.set_index("open_time")

        for sym, df in out.items():
            if "open_time" not in df.columns:
                for col in htf_cols:
                    df[f"BTC_{col}"] = pd.NA
                continue
            idx_df = df.sort_values("open_time").drop_duplicates(subset=["open_time"], keep="last").set_index("open_time")
            btc_sync = btc_sync_base.reindex(idx_df.index, method="pad")
            for col in htf_cols:
                out_col = f"BTC_{col}"
                idx_df[out_col] = btc_sync[col] if col in btc_sync.columns else pd.NA
            idx_df["symbol"] = sym
            out[sym] = idx_df.reset_index()
        return out

    def _count_same_side_alt_positions(self, positions: Dict[str, Optional[Position]], side: str) -> int:
        alt_symbols = set(getattr(cfg, "BTC_REGIME_ALT_SYMBOLS", ["ETHUSDT", "SOLUSDT", "BNBUSDT", "AVAXUSDT"]) or [])
        return sum(1 for sym, pos in positions.items() if pos is not None and sym in alt_symbols and pos.side == side)

    def _symbol_risk_multiplier(self, sym: str) -> float:
        try:
            sym = str(sym or '').upper()
            specific = cfg.get_symbol_param(sym, 'RISK_MULTIPLIER', None)
            if specific is not None:
                return max(0.0, float(specific))
            if sym == 'BTCUSDT':
                return max(0.0, float(getattr(cfg, 'BTC_POSITION_RISK_MULTIPLIER', getattr(cfg, 'BASE_POSITION_RISK_MULTIPLIER', 1.0))))
            alt_symbols = set(getattr(cfg, 'BTC_REGIME_ALT_SYMBOLS', []) or [])
            if sym in alt_symbols:
                key = sym.replace('USDT', '') + '_POSITION_RISK_MULTIPLIER'
                return max(0.0, float(getattr(cfg, key, getattr(cfg, 'ALT_POSITION_RISK_MULTIPLIER', 0.7))))
        except Exception:
            pass
        return max(0.0, float(getattr(cfg, 'BASE_POSITION_RISK_MULTIPLIER', 1.0)))

    def _record_partial_close(
        self,
        sym: str,
        pos: Position,
        price: float,
        qty_closed: float,
        pnl_after_fee: float,
        reason: str,
        bar_index: Optional[int] = None,
    ) -> None:
        self.partial_closes.append(
            {
                "symbol": sym,
                "side": str(pos.side).lower(),
                "entry_price": float(pos.entry_price),
                "exit_price": float(price),
                "qty": float(qty_closed),
                "pnl": float(pnl_after_fee),
                "reason": reason,
                "bar_index": int(bar_index) if bar_index is not None else None,
                "entry_bar_index": int(pos.open_time) if getattr(pos, "open_time", None) is not None else None,
            }
        )

    def _record_closed_trade(
        self,
        sym: str,
        pos: Position,
        price: float,
        pnl_after_fee: float,
        reason: str,
        bar_index: Optional[int] = None,
    ) -> None:
        entry_notional = float(pos.entry_price * pos.qty) if pos.qty > 0 else 0.0
        pnl_pct_on_notional = (float(pnl_after_fee) / entry_notional * 100.0) if entry_notional > 0 else 0.0
        self.closed_trades.append(
            {
                "symbol": sym,
                "side": str(pos.side).lower(),
                "entry_price": float(pos.entry_price),
                "exit_price": float(price),
                "qty": float(pos.qty),
                "pnl": float(pnl_after_fee),
                "pnl_pct_on_notional": float(pnl_pct_on_notional),
                "reason": reason,
                "bar_index": int(bar_index) if bar_index is not None else None,
                "entry_bar_index": int(pos.open_time) if getattr(pos, "open_time", None) is not None else None,
                "tp1_hit": bool(getattr(pos, "tp1_hit", False)),
                "be_moved": bool(getattr(pos, "be_moved", False)),
                "trail_active": bool(getattr(pos, "trail_active", False)),
            }
        )

    def _calculate_trade_stats(self) -> Dict[str, float]:
        total_trades = len(self.closed_trades)
        if total_trades == 0:
            return {
                "total_trades": 0,
                "long_trades": 0,
                "short_trades": 0,
                "wins": 0,
                "losses": 0,
                "breakeven_trades": 0,
                "win_rate": 0.0,
                "gross_profit": 0.0,
                "gross_loss": 0.0,
                "profit_factor": 0.0,
                "avg_trade": 0.0,
                "avg_win": 0.0,
                "avg_loss": 0.0,
                "expectancy": 0.0,
                "tp1_hit_trades": 0,
                "tp1_hit_rate": 0.0,
                "be_moved_trades": 0,
                "trail_active_trades": 0,
                "partial_close_count": len(self.partial_closes),
                "partial_close_pnl": float(sum(x["pnl"] for x in self.partial_closes)) if self.partial_closes else 0.0,
            }

        pnls = [float(t["pnl"]) for t in self.closed_trades]
        wins = [x for x in pnls if x > 0]
        losses = [x for x in pnls if x < 0]
        breakevens = [x for x in pnls if x == 0]

        long_trades = sum(1 for t in self.closed_trades if str(t.get("side", "")).lower() == "long")
        short_trades = sum(1 for t in self.closed_trades if str(t.get("side", "")).lower() == "short")
        tp1_hit_trades = sum(1 for t in self.closed_trades if bool(t.get("tp1_hit", False)))
        be_moved_trades = sum(1 for t in self.closed_trades if bool(t.get("be_moved", False)))
        trail_active_trades = sum(1 for t in self.closed_trades if bool(t.get("trail_active", False)))

        gross_profit = float(sum(wins))
        gross_loss = float(abs(sum(losses)))
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float("inf")
        win_rate = (len(wins) / total_trades) * 100.0
        avg_trade = float(sum(pnls) / total_trades)
        avg_win = float(sum(wins) / len(wins)) if wins else 0.0
        avg_loss = float(sum(losses) / len(losses)) if losses else 0.0
        expectancy = avg_trade
        tp1_hit_rate = (tp1_hit_trades / total_trades) * 100.0 if total_trades > 0 else 0.0
        partial_close_pnl = float(sum(x["pnl"] for x in self.partial_closes)) if self.partial_closes else 0.0

        return {
            "total_trades": total_trades,
            "long_trades": long_trades,
            "short_trades": short_trades,
            "wins": len(wins),
            "losses": len(losses),
            "breakeven_trades": len(breakevens),
            "win_rate": float(win_rate),
            "gross_profit": gross_profit,
            "gross_loss": gross_loss,
            "profit_factor": float(profit_factor),
            "avg_trade": avg_trade,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "expectancy": float(expectancy),
            "tp1_hit_trades": tp1_hit_trades,
            "tp1_hit_rate": float(tp1_hit_rate),
            "be_moved_trades": be_moved_trades,
            "trail_active_trades": trail_active_trades,
            "partial_close_count": len(self.partial_closes),
            "partial_close_pnl": partial_close_pnl,
        }

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
            prepared = compute_indicators(df)
            prepared["symbol"] = sym
            out[sym] = prepared
        return self._attach_btc_regime_columns(out)

    # ------------------------------------------------------------------
    def run(self) -> Dict[str, float]:
        self.closed_trades = []
        self.partial_closes = []
        data = self._prepare()
        if not data:
            return {"total_pnl": 0.0, "roi": 0.0, "max_drawdown": 0.0}

        symbols = sorted(data.keys())
        max_len = max(len(df) for df in data.values())
        warmup = min(200, max_len - 1)

        positions: Dict[str, Optional[Position]] = {s: None for s in symbols}
        cooldown_until_bar: Dict[str, Dict[str, int]] = {s: {"long": -1, "short": -1} for s in symbols}
        stop_loss_streaks: Dict[str, Dict[str, int]] = {s: {"long": 0, "short": 0} for s in symbols}
        balance = self.initial_balance
        equity_curve = []

        risk_per_trade = float(getattr(cfg, "RISK_PER_TRADE", 0.01))
        leverage = int(getattr(cfg, "FUTURES_LEVERAGE_DEFAULT", 5))
        max_positions = int(getattr(cfg, "MAX_OPEN_POSITIONS", 3))

        cooldown_enabled = bool(getattr(cfg, "ENTRY_COOLDOWN_AFTER_STOP_ENABLED", True))
        cooldown_bars_base = int(getattr(cfg, "ENTRY_COOLDOWN_AFTER_STOP_BARS", 0) or 0)
        cooldown_streak_threshold = int(getattr(cfg, "ENTRY_COOLDOWN_STREAK_THRESHOLD", 2) or 0)
        cooldown_extra_bars = int(getattr(cfg, "ENTRY_COOLDOWN_STREAK_EXTRA_BARS", 0) or 0)
        cooldown_reset_on_non_loss = bool(getattr(cfg, "ENTRY_COOLDOWN_RESET_ON_NON_LOSS_EXIT", True))


        def register_stop_loss(sym: str, side: str, bar_index: int, pnl_after_fee: float) -> None:
            if not cooldown_enabled:
                return
            if pnl_after_fee > 0:
                if cooldown_reset_on_non_loss:
                    stop_loss_streaks[sym][side] = 0
                    cooldown_until_bar[sym][side] = -1
                return
            stop_loss_streaks[sym][side] += 1
            bars = cooldown_bars_base
            if cooldown_streak_threshold > 0 and stop_loss_streaks[sym][side] >= cooldown_streak_threshold:
                bars += cooldown_extra_bars
            cooldown_until_bar[sym][side] = bar_index + bars

        def reset_stop_streak(sym: str, side: str) -> None:
            if cooldown_reset_on_non_loss:
                stop_loss_streaks[sym][side] = 0
                cooldown_until_bar[sym][side] = -1

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
                        balance, pnl_after_fee = self._close_position(balance, sym, pos, price, return_pnl=True, reason="stop_loss", bar_index=i)
                        register_stop_loss(sym, pos.side, i, pnl_after_fee)
                        positions[sym] = None
                        continue
                    if pos.side == "short" and price >= pos.stop_loss:
                        balance, pnl_after_fee = self._close_position(balance, sym, pos, price, return_pnl=True, reason="stop_loss", bar_index=i)
                        register_stop_loss(sym, pos.side, i, pnl_after_fee)
                        positions[sym] = None
                        continue

                update_peak_price(pos, price)
                maybe_move_to_break_even(pos, price, atr)

                # 2) Первая цель по прибыли: частично фиксируем импульс раньше
                if pos.tp1 is not None and should_take_tp1(pos, price):
                    balance = self._close_fraction(balance, sym, pos, price, fraction=tp1_fraction())
                    on_tp1_hit(pos, price, atr)
                    update_trailing_stop(pos, atr)

                # 3) Менее шумный трейлинг от лучшей достигнутой цены
                maybe_activate_trailing(pos, price, atr)
                update_trailing_stop(pos, atr)
                if pos.trailing_stop is not None and should_close_on_trailing(pos, price):
                    balance, _ = self._close_position(balance, sym, pos, price, return_pnl=True, reason="trailing_stop", bar_index=i)
                    reset_stop_streak(sym, pos.side)
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
                        balance, _ = self._close_position(balance, sym, pos, price, return_pnl=True, reason="time_stop", bar_index=i)
                        reset_stop_streak(sym, pos.side)
                        positions[sym] = None
                        continue

                # 4) Обратный сигнал стратегии полностью закрывает позицию
                sig = signal_from_indicators(df_slice)
                if pos.side == "long" and sig == "sell":
                    balance, _ = self._close_position(balance, sym, pos, price, return_pnl=True, reason="reverse_signal", bar_index=i)
                    positions[sym] = None
                    continue
                if pos.side == "short" and sig == "buy":
                    balance, _ = self._close_position(balance, sym, pos, price, return_pnl=True, reason="reverse_signal", bar_index=i)
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
                atr_sl_mult = float(cfg.get_symbol_param(sym, "ATR_SL_MULT", getattr(cfg, "ATR_SL_MULT", 4.0)))

                btc_regime_cap = int(getattr(cfg, "BTC_REGIME_MAX_SAME_SIDE_ALT_POSITIONS", 0) or 0)
                alt_symbols = set(getattr(cfg, "BTC_REGIME_ALT_SYMBOLS", ["ETHUSDT", "SOLUSDT", "BNBUSDT", "AVAXUSDT"]) or [])
                if btc_regime_cap > 0 and sym in alt_symbols:
                    same_side_alt_count = self._count_same_side_alt_positions(positions, side)
                    if same_side_alt_count >= btc_regime_cap:
                        continue

                if cooldown_enabled and i < int(cooldown_until_bar[sym].get(side, -1)):
                    continue

                # расстояние до стопа в процентах
                stop_distance_pct = atr_sl_mult * atr / price * 100.0
                if stop_distance_pct <= 0:
                    continue

                risk_multiplier = self._symbol_risk_multiplier(sym)
                eff_risk_per_trade = risk_per_trade * risk_multiplier
                notional, qty = self.risk.calc_futures_size_from_risk(
                    equity=equity,
                    price=price,
                    stop_distance_pct=stop_distance_pct,
                    risk_per_trade=eff_risk_per_trade,
                    leverage=leverage,
                )
                if notional <= 0 or qty <= 0:
                    continue

                if side == "long":
                    stop_loss = price - atr_sl_mult * atr
                else:
                    stop_loss = price + atr_sl_mult * atr
                tp1 = calc_tp1_price(price, atr, side, sym)

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
                    be_moved=False,
                    tp1_hit=False,
                    trail_active=False,
                    pyramid_level=0,
                )
                open_count += 1
                can_open_more = open_count < eff_max_positions

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
            balance, _ = self._close_position(balance, sym, pos, price, return_pnl=True, reason="end_of_backtest", bar_index=max_len - 1)

        total_pnl = balance - self.initial_balance
        roi = total_pnl / self.initial_balance * 100.0 if self.initial_balance > 0 else 0.0

        equity_arr = np.array(equity_curve, dtype=float)
        max_dd = self._max_drawdown(equity_arr) if len(equity_arr) > 1 else 0.0
        stats = self._calculate_trade_stats()

        print("\n=== BACKTEST RESULTS (MTF) ===")
        print(f"PNL: {total_pnl:.4f} USDT")
        print(f"ROI: {roi:.4f} %")
        print(f"MaxDD: {max_dd:.4f} %")
        print(f"Trades: {stats['total_trades']}")
        print(f"Long trades: {stats['long_trades']}")
        print(f"Short trades: {stats['short_trades']}")
        print(f"Wins: {stats['wins']}")
        print(f"Losses: {stats['losses']}")
        print(f"Breakeven trades: {stats['breakeven_trades']}")
        print(f"WinRate: {stats['win_rate']:.2f} %")
        print(f"ProfitFactor: {stats['profit_factor']:.4f}")
        print(f"AvgTrade: {stats['avg_trade']:.4f} USDT")
        print(f"AvgWin: {stats['avg_win']:.4f} USDT")
        print(f"AvgLoss: {stats['avg_loss']:.4f} USDT")
        print(f"Expectancy: {stats['expectancy']:.4f} USDT")
        print(f"GrossProfit: {stats['gross_profit']:.4f} USDT")
        print(f"GrossLoss: {stats['gross_loss']:.4f} USDT")
        print(f"TP1 hit trades: {stats['tp1_hit_trades']}")
        print(f"TP1 hit rate: {stats['tp1_hit_rate']:.2f} %")
        print(f"BE moved trades: {stats['be_moved_trades']}")
        print(f"Trailing active trades: {stats['trail_active_trades']}")
        print(f"Partial closes: {stats['partial_close_count']}")
        print(f"Partial close PnL: {stats['partial_close_pnl']:.4f} USDT")

        return {
            "total_pnl": float(total_pnl),
            "roi": float(roi),
            "max_drawdown": float(max_dd),
            "equity_curve": equity_curve,
            "trade_stats": stats,
        }

    # ------------------------------------------------------------------
    def _close_fraction(self, balance: float, sym: str, pos: Position, price: float, fraction: float, reason: str = "partial", bar_index: Optional[int] = None) -> float:
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
        self._record_partial_close(sym, pos, price, qty_close, pnl_after_fee, reason=reason, bar_index=bar_index)

        # уменьшаем позицию
        pos.qty -= qty_close
        if pos.qty < 0:
            pos.qty = 0
        pos.notional = pos.entry_price * pos.qty

        return new_balance

    # ------------------------------------------------------------------
    def _close_position(self, balance: float, sym: str, pos: Position, price: float, return_pnl: bool = False, reason: str = "close", bar_index: Optional[int] = None):
        """Полное закрытие позиции и возврат обновлённого баланса с учётом комиссии."""
        if pos.qty <= 0:
            return (balance, 0.0) if return_pnl else balance

        if pos.side == "long":
            pnl = (price - pos.entry_price) * pos.qty
        else:
            pnl = (pos.entry_price - price) * pos.qty

        notional_entry = pos.entry_price * pos.qty
        notional_exit = price * pos.qty
        fee = (notional_entry + notional_exit) * self.fee_rate
        pnl_after_fee = pnl - fee
        self._record_closed_trade(sym, pos, price, pnl_after_fee, reason=reason, bar_index=bar_index)
        new_balance = balance + pnl_after_fee
        return (new_balance, pnl_after_fee) if return_pnl else new_balance

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
