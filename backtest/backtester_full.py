
import os
import sys
import numpy as np
import pandas as pd
from collections import Counter
from typing import Any, Dict, List, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.append(ROOT)

import config as cfg
from indicators import compute_indicators
from strategy import signal_from_indicators
from execution_policy import compute_trade_risk_multiplier
from position_sizing_engine import compute_position_sizing_risk_pct
from strategies import get_active_strategy
from risk import RiskManager
from position import PositionState as Position
from position_management import (
    calc_initial_stop_price,
    calc_tp1_price,
    maybe_move_to_break_even,
    maybe_apply_profit_lock,
    maybe_activate_trailing,
    on_tp1_hit,
    should_take_tp1,
    should_close_on_trailing,
    should_time_stop_before_tp1,
    should_force_exit_weak_trade,
    should_cut_adverse_trade_early,
    should_time_stop_after_tp1,
    tp1_fraction,
    update_peak_price,
    update_trailing_stop,
    mark_tp1_bar,
    should_close_runner_on_stall,
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
        self.trade_realized_pnl: Dict[str, float] = {}

    def _trade_key(self, sym: str, pos: Position) -> str:
        return f"{sym}|{str(pos.side).lower()}|{int(float(getattr(pos, 'open_time', 0) or 0))}"

    def _apply_exit_slippage(self, price: float, side: str, reason: str) -> float:
        if not bool(getattr(cfg, "BACKTEST_APPLY_SLIPPAGE", True)):
            return float(price)
        bps = float(getattr(cfg, "BACKTEST_SLIPPAGE_BPS", 0.0) or 0.0)
        if bps <= 0:
            return float(price)
        slip = bps / 10000.0
        side = str(side).lower()
        reason = str(reason).lower()
        adverse_for_long = side == "long"
        if reason in {"tp1", "take_profit", "tp", "target"}:
            adverse_for_long = side == "long"
        elif reason in {"stop_loss", "trailing_stop", "time_stop_after_tp1", "time_stop", "reverse_signal", "end_of_backtest"}:
            adverse_for_long = side == "long"
        if side == "long":
            return float(price) * (1.0 - slip)
        return float(price) * (1.0 + slip)

    def _pick_intrabar_exit(self, pos: Position, bar: pd.Series) -> tuple[str | None, float | None]:
        high = float(bar.get("high", bar.get("close", 0.0)))
        low = float(bar.get("low", bar.get("close", 0.0)))
        close = float(bar.get("close", 0.0))
        order = str(getattr(cfg, "BACKTEST_INTRABAR_EXIT_ORDER", "conservative") or "conservative").lower()
        if pos.side == "long":
            sl_hit = pos.stop_loss is not None and low <= float(pos.stop_loss)
            tp_hit = pos.tp1 is not None and high >= float(pos.tp1)
            if sl_hit and tp_hit:
                return ("stop_loss", float(pos.stop_loss)) if order == "conservative" else ("tp1", float(pos.tp1))
            if sl_hit:
                return "stop_loss", float(pos.stop_loss)
            if tp_hit:
                return "tp1", float(pos.tp1)
            if pos.trailing_stop is not None and low <= float(pos.trailing_stop):
                return "trailing_stop", float(pos.trailing_stop)
        else:
            sl_hit = pos.stop_loss is not None and high >= float(pos.stop_loss)
            tp_hit = pos.tp1 is not None and low <= float(pos.tp1)
            if sl_hit and tp_hit:
                return ("stop_loss", float(pos.stop_loss)) if order == "conservative" else ("tp1", float(pos.tp1))
            if sl_hit:
                return "stop_loss", float(pos.stop_loss)
            if tp_hit:
                return "tp1", float(pos.tp1)
            if pos.trailing_stop is not None and high >= float(pos.trailing_stop):
                return "trailing_stop", float(pos.trailing_stop)
        return None, None

    def _can_pyramid_position(self, sym: str, pos: Position, price: float, atr: float, signal: str, sig_meta: Dict[str, Any]) -> bool:
        if pos is None or pos.qty <= 0 or atr <= 0 or price <= 0:
            return False
        if sym != "BTCUSDT":
            return False
        if not bool(cfg.get_symbol_param_bool(sym, "BTC_PYRAMIDING_ENABLED", bool(getattr(cfg, "BTC_PYRAMIDING_ENABLED", False)))):
            return False
        max_adds = int(cfg.get_symbol_param_int(sym, "BTC_PYRAMID_MAX_ADDS", int(getattr(cfg, "BTC_PYRAMID_MAX_ADDS", 1))))
        if int(getattr(pos, "pyramid_level", 0) or 0) >= max_adds:
            return False
        wanted_signal = "buy" if pos.side == "long" else "sell"
        if signal != wanted_signal:
            return False
        if bool(getattr(pos, "trail_active", False)):
            return False
        if bool(getattr(pos, "tp1_hit", False)) and not bool(cfg.get_symbol_param_bool(sym, "BTC_PYRAMID_ALLOW_AFTER_TP1", bool(getattr(cfg, "BTC_PYRAMID_ALLOW_AFTER_TP1", True)))):
            return False
        allowed = {str(x).lower() for x in (cfg.get_symbol_param(sym, "BTC_PYRAMID_ALLOWED_TRADE_TYPES", getattr(cfg, "BTC_PYRAMID_ALLOWED_TRADE_TYPES", ["continuation", "cont_compression", "impulse"])) or [])}
        trade_type = str(sig_meta.get("trade_type", "") or "").lower()
        if allowed and trade_type not in allowed:
            return False
        if bool(cfg.get_symbol_param_bool(sym, "BTC_PYRAMID_REQUIRE_STRONG_SETUP", bool(getattr(cfg, "BTC_PYRAMID_REQUIRE_STRONG_SETUP", True)))) and not bool(sig_meta.get("strong_setup", False)):
            return False
        adx_h = float(sig_meta.get("adx_h", 0.0) or 0.0)
        drift = abs(float(sig_meta.get("drift", 0.0) or 0.0))
        if adx_h < float(cfg.get_symbol_param_float(sym, "BTC_PYRAMID_MIN_ADX_H", float(getattr(cfg, "BTC_PYRAMID_MIN_ADX_H", 24.0)))):
            return False
        if drift < float(cfg.get_symbol_param_float(sym, "BTC_PYRAMID_MIN_DRIFT", float(getattr(cfg, "BTC_PYRAMID_MIN_DRIFT", 0.0012)))):
            return False
        min_progress_atr = float(cfg.get_symbol_param_float(sym, "BTC_PYRAMID_MIN_PROGRESS_ATR", float(getattr(cfg, "BTC_PYRAMID_MIN_PROGRESS_ATR", 0.45))))
        progress = (price - float(pos.entry_price)) / atr if pos.side == "long" else (float(pos.entry_price) - price) / atr
        return progress >= min_progress_atr

    def _apply_pyramid_addition(self, sym: str, pos: Position, price: float, atr: float, equity: float, side: str, sig_meta: Dict[str, Any]) -> Position:
        risk_fraction = float(cfg.get_symbol_param_float(sym, "BTC_PYRAMID_RISK_FRACTION", float(getattr(cfg, "BTC_PYRAMID_RISK_FRACTION", 0.55))))
        leverage = int(getattr(cfg, "FUTURES_LEVERAGE_DEFAULT", 5))
        trade_type = str(sig_meta.get("trade_type", getattr(pos, "trade_type", "continuation")) or "continuation")
        market_state = str(sig_meta.get("market_state", getattr(pos, "market_state", "unknown")) or "unknown")
        initial_stop = calc_initial_stop_price(price, atr, side, sym, pos, trade_type=trade_type, market_state=market_state)
        stop_distance_pct = abs(price - initial_stop) / price * 100.0
        if stop_distance_pct <= 0:
            return pos
        base_risk_per_trade = float(getattr(cfg, "RISK_PER_TRADE", 0.01))
        risk_multiplier = self._symbol_risk_multiplier(sym)
        trade_risk_mult = 1.0
        try:
            trade_risk_mult = compute_trade_risk_multiplier(sig_meta=sig_meta, side=side, cfg=cfg, market_state_fallback=market_state, enable_legacy_v812=True)
        except Exception:
            trade_risk_mult = 1.0
        eff_risk_per_trade = base_risk_per_trade * risk_multiplier * trade_risk_mult * max(0.05, risk_fraction)
        try:
            sized_risk_per_trade, _ = compute_position_sizing_risk_pct(cfg=cfg, sig_meta=sig_meta, symbol=sym, side=side, base_risk_per_trade=eff_risk_per_trade, equity=equity, equity_peak=equity)
        except Exception:
            sized_risk_per_trade = eff_risk_per_trade
        notional, qty = self.risk.calc_futures_size_from_risk(equity=equity, price=price, stop_distance_pct=stop_distance_pct, risk_per_trade=sized_risk_per_trade, leverage=leverage)
        if notional <= 0 or qty <= 0:
            return pos
        old_qty = float(pos.qty)
        new_qty = old_qty + float(qty)
        if new_qty <= 0:
            return pos
        pos.entry_price = ((float(pos.entry_price) * old_qty) + (float(price) * float(qty))) / new_qty
        pos.qty = new_qty
        pos.notional = float(pos.entry_price) * float(pos.qty)
        pos.stop_loss = initial_stop
        pos.tp1 = calc_tp1_price(float(pos.entry_price), atr, side, sym, pos)
        pos.peak_price = max(float(getattr(pos, "peak_price", price) or price), float(price)) if side == "long" else min(float(getattr(pos, "peak_price", price) or price), float(price))
        pos.trailing_stop = None
        pos.trail_active = False
        pos.be_moved = False
        pos.pyramid_level = int(getattr(pos, "pyramid_level", 0) or 0) + 1
        pos.trade_type = trade_type
        pos.market_state = market_state
        return pos

    # ------------------------------------------------------------------
    def _attach_btc_regime_columns(self, out: Dict[str, pd.DataFrame]) -> Dict[str, pd.DataFrame]:
        btc_symbol = str(getattr(cfg, "BTC_REGIME_FILTER_SYMBOL", "BTCUSDT"))
        btc_df = out.get(btc_symbol)
        htf_cols = ["HTF_SMA_TREND", "HTF_EMA20", "HTF_EMA50", "HTF_EMA200", "HTF_ATR", "HTF_ADX", "HTF_RSI"]
        if btc_df is None or btc_df.empty or "open_time" not in btc_df.columns:
            for sym, df in out.items():
                for col in htf_cols:
                    df[f"BTC_{col}"] = pd.NA
                df["BTC_close"] = pd.NA
            return out

        btc_sync_base = btc_df.copy()
        btc_sync_base = btc_sync_base.sort_values("open_time").drop_duplicates(subset=["open_time"], keep="last")
        btc_sync_base = btc_sync_base.set_index("open_time")

        for sym, df in out.items():
            if "open_time" not in df.columns:
                for col in htf_cols:
                    df[f"BTC_{col}"] = pd.NA
                df["BTC_close"] = pd.NA
                continue
            idx_df = df.sort_values("open_time").drop_duplicates(subset=["open_time"], keep="last").set_index("open_time")
            btc_sync = btc_sync_base.reindex(idx_df.index, method="pad")
            for col in htf_cols:
                out_col = f"BTC_{col}"
                idx_df[out_col] = btc_sync[col] if col in btc_sync.columns else pd.NA
            idx_df["BTC_close"] = btc_sync["close"] if "close" in btc_sync.columns else pd.NA
            idx_df["symbol"] = sym
            out[sym] = idx_df.reset_index()
        return out

    def _count_same_side_alt_positions(self, positions: Dict[str, Optional[Position]], side: str) -> int:
        alt_symbols = set(getattr(cfg, "BTC_REGIME_ALT_SYMBOLS", ["ETHUSDT"]) or [])
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
        trade_key = self._trade_key(sym, pos)
        partial_realized = float(self.trade_realized_pnl.get(trade_key, 0.0))
        total_trade_pnl = float(partial_realized + pnl_after_fee)
        self.closed_trades.append(
            {
                "symbol": sym,
                "side": str(pos.side).lower(),
                "entry_price": float(pos.entry_price),
                "exit_price": float(price),
                "qty": float(pos.qty),
                "pnl": float(pnl_after_fee),
                "trade_pnl_total": float(total_trade_pnl),
                "runner_pnl_after_tp1": float(pnl_after_fee),
                "partial_realized_pnl": float(partial_realized),
                "pnl_pct_on_notional": float(pnl_pct_on_notional),
                "reason": reason,
                "bar_index": int(bar_index) if bar_index is not None else None,
                "entry_bar_index": int(pos.open_time) if getattr(pos, "open_time", None) is not None else None,
                "trade_type": str(getattr(pos, "trade_type", "unknown") or "unknown"),
                "market_state": str(getattr(pos, "market_state", "unknown") or "unknown"),
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
                "trade_type_rows": [],
                "exit_reason_rows": [],
                "trade_type_exit_rows": [],
            }

        pnls = [float(t.get("trade_pnl_total", t["pnl"])) for t in self.closed_trades]
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
        diagnostics = self._build_trade_diagnostics() if bool(getattr(cfg, "BACKTEST_INCLUDE_TRADE_DIAGNOSTICS", True)) else {"trade_type_rows": [], "exit_reason_rows": [], "trade_type_exit_rows": []}

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
            "trade_type_rows": diagnostics.get("trade_type_rows", []),
            "exit_reason_rows": diagnostics.get("exit_reason_rows", []),
            "trade_type_exit_rows": diagnostics.get("trade_type_exit_rows", []),
        }

    def _build_trade_diagnostics(self) -> Dict[str, Any]:
        type_counter = Counter()
        type_pnl = Counter()
        exit_counter = Counter()
        exit_pnl = Counter()
        combo_counter = Counter()
        combo_pnl = Counter()

        for trade in self.closed_trades:
            trade_type = str(trade.get("trade_type", "unknown") or "unknown").lower()
            reason = str(trade.get("reason", "unknown") or "unknown").lower()
            pnl = float(trade.get("trade_pnl_total", trade.get("pnl", 0.0)) or 0.0)
            combo = f"{trade_type}->{reason}"
            type_counter[trade_type] += 1
            type_pnl[trade_type] += pnl
            exit_counter[reason] += 1
            exit_pnl[reason] += pnl
            combo_counter[combo] += 1
            combo_pnl[combo] += pnl

        def _fmt(counter: Counter, pnl_counter: Counter) -> list[str]:
            rows = []
            for key, count in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0])):
                rows.append(f"{key}:{count}:{pnl_counter.get(key, 0.0):.4f}")
            return rows

        return {
            "trade_type_rows": _fmt(type_counter, type_pnl),
            "exit_reason_rows": _fmt(exit_counter, exit_pnl),
            "trade_type_exit_rows": _fmt(combo_counter, combo_pnl),
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
        self.trade_realized_pnl = {}
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
        equity_peak = float(self.initial_balance)

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
            equity_peak = max(equity_peak, float(equity))

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

                pos_row = df_slice.iloc[i]
                bar_high = float(pos_row.get("high", price))
                bar_low = float(pos_row.get("low", price))
                favorable_price = bar_high if pos.side == "long" else bar_low

                # 1) Intrabar SL / TP / trailing. Если на свече задеты несколько уровней,
                # порядок определяется _pick_intrabar_exit(...).
                exit_reason, exit_price = self._pick_intrabar_exit(pos, pos_row)
                if exit_reason == "stop_loss":
                    balance, pnl_after_fee = self._close_position(balance, sym, pos, exit_price, return_pnl=True, reason="stop_loss", bar_index=i)
                    register_stop_loss(sym, pos.side, i, pnl_after_fee)
                    positions[sym] = None
                    continue
                if exit_reason == "tp1":
                    tp1_frac = tp1_fraction(pos)
                    if tp1_frac >= 1.0:
                        balance, _ = self._close_position(balance, sym, pos, exit_price, return_pnl=True, reason="tp1_full", bar_index=i)
                        reset_stop_streak(sym, pos.side)
                        positions[sym] = None
                        continue
                    balance = self._close_fraction(balance, sym, pos, exit_price, fraction=tp1_frac, reason="tp1", bar_index=i)
                    mark_tp1_bar(pos, i)
                    on_tp1_hit(pos, exit_price, atr)
                elif exit_reason == "trailing_stop":
                    balance, _ = self._close_position(balance, sym, pos, exit_price, return_pnl=True, reason="trailing_stop", bar_index=i)
                    reset_stop_streak(sym, pos.side)
                    positions[sym] = None
                    continue

                # 2) Обновляем MFE по экстремуму свечи и двигаем BE / trailing по лучшей цене внутри бара.
                update_peak_price(pos, favorable_price, i)
                maybe_move_to_break_even(pos, favorable_price, atr)
                maybe_apply_profit_lock(pos, favorable_price, atr)

                # 3) Runner включаем только после дополнительного прогресса за TP1.
                maybe_activate_trailing(pos, favorable_price, atr)
                update_trailing_stop(pos, atr)

                # 3.2) Слабую/непоехавшую идею режем раньше полного стопа.
                if should_cut_adverse_trade_early(pos, price, atr):
                    balance, _ = self._close_position(balance, sym, pos, price, return_pnl=True, reason="early_cut_loss", bar_index=i)
                    reset_stop_streak(sym, pos.side)
                    positions[sym] = None
                    continue

                if should_force_exit_weak_trade(pos, price, atr, i):
                    balance, _ = self._close_position(balance, sym, pos, price, return_pnl=True, reason="weak_trade_exit", bar_index=i)
                    reset_stop_streak(sym, pos.side)
                    positions[sym] = None
                    continue

                if should_time_stop_before_tp1(pos, i):
                    balance, _ = self._close_position(balance, sym, pos, price, return_pnl=True, reason="time_stop_before_tp1", bar_index=i)
                    reset_stop_streak(sym, pos.side)
                    positions[sym] = None
                    continue

                # 3.25) После TP1 не держим хвост вечно: если продолжения нет — закрываем остаток.
                if should_time_stop_after_tp1(pos, i):
                    balance, _ = self._close_position(balance, sym, pos, price, return_pnl=True, reason="time_stop_after_tp1", bar_index=i)
                    reset_stop_streak(sym, pos.side)
                    positions[sym] = None
                    continue

                if should_close_runner_on_stall(pos, i):
                    balance, _ = self._close_position(balance, sym, pos, price, return_pnl=True, reason="runner_stall", bar_index=i)
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

                try:
                    sig_meta = getattr(get_active_strategy(), "last_signal_meta", {}) or {}
                except Exception:
                    sig_meta = {}
                if self._can_pyramid_position(sym, pos, price, atr, sig, sig_meta):
                    positions[sym] = self._apply_pyramid_addition(sym, pos, price, atr, equity, pos.side, sig_meta)
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
                alt_symbols = set(getattr(cfg, "BTC_REGIME_ALT_SYMBOLS", ["ETHUSDT"]) or [])
                if btc_regime_cap > 0 and sym in alt_symbols:
                    same_side_alt_count = self._count_same_side_alt_positions(positions, side)
                    if same_side_alt_count >= btc_regime_cap:
                        continue

                if cooldown_enabled and i < int(cooldown_until_bar[sym].get(side, -1)):
                    continue

                sig_meta = getattr(get_active_strategy(), "last_signal_meta", {}) or {}
                trade_type = str(sig_meta.get("trade_type", "unknown") or "unknown")
                market_state = str(sig_meta.get("market_state", "unknown") or "unknown")
                initial_stop = calc_initial_stop_price(price, atr, side, sym, None, trade_type=trade_type, market_state=market_state)
                stop_distance_pct = abs(price - initial_stop) / price * 100.0
                if stop_distance_pct <= 0:
                    continue

                risk_multiplier = self._symbol_risk_multiplier(sym)
                try:
                    sig_meta = getattr(get_active_strategy(), "last_signal_meta", {}) or {}
                    trade_risk_mult = compute_trade_risk_multiplier(
                        sig_meta=sig_meta,
                        side=side,
                        cfg=cfg,
                        market_state_fallback=market_state,
                        enable_legacy_v812=True,
                    )
                except Exception:
                    trade_risk_mult = 1.0
                eff_risk_per_trade = risk_per_trade * risk_multiplier * trade_risk_mult
                try:
                    sized_risk_per_trade, _v25_flags = compute_position_sizing_risk_pct(
                        cfg=cfg,
                        sig_meta=sig_meta,
                        symbol=sym,
                        side=side,
                        base_risk_per_trade=eff_risk_per_trade,
                        equity=equity,
                        equity_peak=equity_peak,
                    )
                except Exception:
                    sized_risk_per_trade = eff_risk_per_trade
                notional, qty = self.risk.calc_futures_size_from_risk(
                    equity=equity,
                    price=price,
                    stop_distance_pct=stop_distance_pct,
                    risk_per_trade=sized_risk_per_trade,
                    leverage=leverage,
                )
                if notional <= 0 or qty <= 0:
                    continue

                stop_loss = initial_stop
                tp1 = calc_tp1_price(price, atr, side, sym, None)

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
                    trade_type=trade_type,
                    market_state=market_state,
                )
                positions[sym].tp1 = calc_tp1_price(price, atr, side, sym, positions[sym])
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
        if stats["total_trades"] > 0:
            print(f"Net AvgTrade (with partials): {stats['avg_trade']:.4f} USDT")

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

        price = self._apply_exit_slippage(price, pos.side, reason)
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
        trade_key = self._trade_key(sym, pos)
        self.trade_realized_pnl[trade_key] = float(self.trade_realized_pnl.get(trade_key, 0.0)) + float(pnl_after_fee)

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

        price = self._apply_exit_slippage(price, pos.side, reason)
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

# ------------------------------------------------------------------
# Batch MTF backtest runner for yearly folders placed in the project root.
# Expected folders: data_2022, data_2023, data_2024, data_2025
# Expected files in each folder: <SYMBOL>_1h.csv and <SYMBOL>_15m.csv

def _load_csv_for_batch(path: str) -> pd.DataFrame:
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    df = pd.read_csv(path)
    df.columns = [c.lower() for c in df.columns]
    if "open_time" in df.columns:
        df["open_time"] = pd.to_datetime(df["open_time"])
        df = df.sort_values("open_time").reset_index(drop=True)
    return df


def load_mtf_symbol_from_dir(symbol: str, data_dir: str) -> pd.DataFrame:
    path_h1 = os.path.join(data_dir, f"{symbol}_1h.csv")
    path_15m = os.path.join(data_dir, f"{symbol}_15m.csv")

    df_15m = _load_csv_for_batch(path_15m)
    df_1h = _load_csv_for_batch(path_h1)

    for need in ("open", "high", "low", "close", "volume"):
        if need not in df_15m.columns:
            raise ValueError(f"{symbol}_15m.csv missing column {need}")
        if need not in df_1h.columns:
            raise ValueError(f"{symbol}_1h.csv missing column {need}")

    df_1h_ind = compute_indicators(df_1h.copy())

    if "open_time" not in df_1h_ind.columns or "open_time" not in df_15m.columns:
        raise ValueError("Both HTF and LTF data must have open_time column for MTF mode")

    df_1h_ind = df_1h_ind.set_index("open_time")
    df_15m_idx = df_15m.set_index("open_time")
    df_1h_sync = df_1h_ind.reindex(df_15m_idx.index, method="pad")

    htf_cols = ["SMA_TREND", "EMA20", "EMA50", "EMA200", "ATR", "ADX", "RSI"]
    for col in htf_cols:
        hcol = f"HTF_{col}"
        df_15m_idx[hcol] = df_1h_sync[col] if col in df_1h_sync.columns else pd.NA

    return df_15m_idx.reset_index()


def _format_result_block(year: str, symbols: list[str], history: int, max_len: int, result: Dict[str, Any]) -> str:
    stats = result.get("trade_stats", {}) or {}
    lines = [
        str(year),
        f"Symbols (MTF): {symbols}",
        f"History: {history}",
        f"Max_len: {max_len}",
        f"Loop count: {max_len - history}",
        "",
        "=== BACKTEST RESULTS (MTF) ===",
        f"PNL: {result.get('total_pnl', 0.0):.4f} USDT",
        f"ROI: {result.get('roi', 0.0):.4f} %",
        f"MaxDD: {result.get('max_drawdown', 0.0):.4f} %",
        f"Trades: {stats.get('total_trades', 0)}",
        f"Long trades: {stats.get('long_trades', 0)}",
        f"Short trades: {stats.get('short_trades', 0)}",
        f"Wins: {stats.get('wins', 0)}",
        f"Losses: {stats.get('losses', 0)}",
        f"Breakeven trades: {stats.get('breakeven_trades', 0)}",
        f"WinRate: {stats.get('win_rate', 0.0):.2f} %",
        f"ProfitFactor: {stats.get('profit_factor', 0.0):.4f}",
        f"AvgTrade: {stats.get('avg_trade', 0.0):.4f} USDT",
        f"AvgWin: {stats.get('avg_win', 0.0):.4f} USDT",
        f"AvgLoss: {stats.get('avg_loss', 0.0):.4f} USDT",
        f"Expectancy: {stats.get('expectancy', 0.0):.4f} USDT",
        f"GrossProfit: {stats.get('gross_profit', 0.0):.4f} USDT",
        f"GrossLoss: {stats.get('gross_loss', 0.0):.4f} USDT",
        f"TP1 hit trades: {stats.get('tp1_hit_trades', 0)}",
        f"TP1 hit rate: {stats.get('tp1_hit_rate', 0.0):.2f} %",
        f"BE moved trades: {stats.get('be_moved_trades', 0)}",
        f"Trailing active trades: {stats.get('trail_active_trades', 0)}",
        f"Partial closes: {stats.get('partial_close_count', 0)}",
        f"Partial close PnL: {stats.get('partial_close_pnl', 0.0):.4f} USDT",
        f"Net AvgTrade (with partials): {stats.get('avg_trade', 0.0):.4f} USDT",
    ]
    if bool(getattr(cfg, "BACKTEST_INCLUDE_TRADE_DIAGNOSTICS", True)):
        trade_type_rows = stats.get("trade_type_rows", []) or []
        exit_reason_rows = stats.get("exit_reason_rows", []) or []
        trade_type_exit_rows = stats.get("trade_type_exit_rows", []) or []
        lines.append("TradeType stats: " + ("; ".join(trade_type_rows) if trade_type_rows else "n/a"))
        lines.append("ExitReason stats: " + ("; ".join(exit_reason_rows) if exit_reason_rows else "n/a"))
        lines.append("TradeType->Exit stats: " + ("; ".join(trade_type_exit_rows) if trade_type_exit_rows else "n/a"))
    lines.append("")
    return "\n".join(lines)



def run_yearly_batch_backtests(project_root: Optional[str] = None, out_filename: str = "test_results.txt") -> str:
    project_root = project_root or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    history = int(getattr(cfg, "BACKTEST_HISTORY", 300))
    setattr(cfg, "STRATEGY_NAME", "mtf_breakout")

    year_folders = [
        ("2022", os.path.join(project_root, "data_2022")),
        ("2023", os.path.join(project_root, "data_2023")),
        ("2024", os.path.join(project_root, "data_2024")),
        ("2025", os.path.join(project_root, "data_2025")),
    ]
    symbol_groups = [
        ["BTCUSDT"],
    ]

    output_path = os.path.join(project_root, out_filename)
    all_blocks: list[str] = []

    for year, folder in year_folders:
        if not os.path.isdir(folder):
            all_blocks.append(f"{year}\n[SKIP] Folder not found: {folder}\n")
            continue

        for symbols in symbol_groups:
            data: Dict[str, pd.DataFrame] = {}
            max_len = 0
            missing = []
            for sym in symbols:
                try:
                    df_sym = load_mtf_symbol_from_dir(sym, folder)
                except Exception as e:
                    missing.append(f"{sym}: {e}")
                    continue
                if len(df_sym) == 0:
                    missing.append(f"{sym}: empty data")
                    continue
                data[sym] = df_sym
                max_len = max(max_len, len(df_sym))

            if not data:
                block = [
                    str(year),
                    f"Symbols (MTF): {symbols}",
                    f"History: {history}",
                    "",
                    "[SKIP] No data loaded.",
                ]
                if missing:
                    block.append("Problems: " + "; ".join(missing))
                block.append("")
                all_blocks.append("\n".join(block))
                continue

            bt = Backtester(data)
            result = bt.run()
            block = _format_result_block(year, symbols, history, max_len, result)
            if missing:
                block += "Problems: " + "; ".join(missing) + "\n\n"
            all_blocks.append(block)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(all_blocks).rstrip() + "\n")

    print(f"\n[BATCH] Results saved to: {output_path}")
    return output_path


if __name__ == "__main__":
    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    run_yearly_batch_backtests(project_root=ROOT, out_filename="test_results.txt")
