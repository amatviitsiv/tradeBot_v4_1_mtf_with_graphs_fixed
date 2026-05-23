import logging
from collections import Counter
import os
from typing import Optional

import pandas as pd
import numpy as np

import config as cfg
from .base import BaseStrategy
from .mtf_market_helpers import extract_symbol, resolve_regime_from_values
from .mtf_short_helpers import build_short_suppression_reason, should_suppress_short_signal
from .mtf_mean_reversion_helpers import check_v52_mean_reversion_entry, is_mean_reversion_symbol, mr_risk_multiplier
from .mtf_regime_helpers import check_htf_overextension, check_htf_trend_vitality, classify_market_state
from .mtf_time_helpers import extract_bar_timestamp, is_allowed_trading_time
from .mtf_alt_helpers import (
    _alt_regime_filter as alt_regime_filter_helper,
    _alt_setup_tier as alt_setup_tier_helper,
    _alt_strong_setup as alt_strong_setup_helper,
    _alt_upgrade_gate as alt_upgrade_gate_helper,
    _apply_alt_risk_adjustment as apply_alt_risk_adjustment_helper,
    _apply_v80_alt_engine_upgrade as apply_v80_alt_engine_upgrade_helper,
    _is_alt_symbol as is_alt_symbol_helper,
    _relax_alt_filters as relax_alt_filters_helper,
)
from .mtf_directional_risk_helpers import (
    _apply_directional_setup_scaling as apply_directional_setup_scaling_helper,
    _apply_v7_direct_boost as apply_v7_direct_boost_helper,
    _apply_v78_selective_risk_reduction as apply_v78_selective_risk_reduction_helper,
    _apply_v21_regime_aware_adjustment as apply_v21_regime_aware_adjustment_helper,
    _apply_v24_profit_engine_adjustment as apply_v24_profit_engine_adjustment_helper,
)
from .mtf_entry_helpers import (
    check_breakout_confirmation,
    check_continuation_compression_entry,
    check_continuation_entry,
    check_impulse_breakout,
    check_pullback_trend_entry,
)
from .mtf_signal_flow import ENTRY_TRADE_TYPE_PATHS, SIGNAL_FLOW_STAGE_MAP
from .mtf_special_entries_helpers import (
    check_btc_exhaustion_short,
    check_fakeout_reversal_entry,
    range_signal,
)
from .mtf_post_entry_helpers import (
    apply_impulse_short_risk_stack,
    apply_pullback_long_risk_stack,
    apply_standard_long_risk_stack,
    apply_standard_short_risk_stack,
)
from .mtf_orchestrator_helpers import compute_drift_metrics, extract_signal_context
from .mtf_precheck_helpers import run_market_regime_precheck
from .mtf_dual_strategy_helpers import run_v22_nontrend_engine
from .mtf_range_engine import run_btc_range_engine_v1
from .mtf_eth_liquidity_engine import run_eth_liquidity_engine_v1
from .signal_meta import build_signal_meta, empty_signal_meta

logger = logging.getLogger(__name__)


class MTFBreakoutStrategy(BaseStrategy):
    """Multi-timeframe breakout-стратегия.

    HTF (H1) отвечает за направление тренда,
    LTF (M15) даёт точный вход по пробою диапазона.

    Ожидаемые колонки в df (M15-таймфрейм):
    - open, high, low, close, volume, RSI, ATR, ADX, EMA20/50/200 (LTF-индикаторы)
    - HTF_EMA20, HTF_EMA50, HTF_EMA200, HTF_ATR, HTF_ADX, HTF_RSI, HTF_SMA_TREND (добавляются раннером)
    """

    name: str = "mtf_breakout"
    active_trade_type_paths = ENTRY_TRADE_TYPE_PATHS
    signal_flow_stage_map = SIGNAL_FLOW_STAGE_MAP





    def __init__(self):
        self.last_signal_meta = empty_signal_meta()
        self.v60_1_short_debug = {"counters": Counter(), "reject_reasons": Counter(), "score_sum": 0.0, "score_count": 0, "score_max": 0.0}
        self._current_symbol = None
        self._current_regime = None
        self._trace_file_initialized = False
        self._trace_file_path = None
        self._btc_range_debug_file_initialized = False
        self._btc_range_debug_file_path = None
        self._btc_range_debug_no_signal_logs = 0
        self._last_atr_pct_h = 0.0
        self._current_market_state = "unknown"
        self._current_adx_h = 0.0
        self._current_drift = 0.0
        self._last_btc_liquidity_reversal_bar_index = -10**9
        self._last_btc_range_engine_bar_index = -10**9
        self._maybe_reset_alt_trace_file()

    def reset_v60_1_short_debug(self) -> None:
        self.v60_1_short_debug = {"counters": Counter(), "reject_reasons": Counter(), "score_sum": 0.0, "score_count": 0, "score_max": 0.0}

    def _v60_1_short_debug_enabled(self) -> bool:
        return bool(getattr(cfg, "V60_1_SHORT_DEBUG_ENABLED", False))

    def _v60_1_short_hit(self, stage: str, meta: dict | None = None) -> None:
        if not self._v60_1_short_debug_enabled():
            return
        try:
            dbg = getattr(self, "v60_1_short_debug", None)
            if not isinstance(dbg, dict):
                self.reset_v60_1_short_debug()
                dbg = self.v60_1_short_debug
            dbg["counters"][str(stage)] += 1
            if isinstance(meta, dict):
                reason = str(meta.get("reason") or "")
                if reason:
                    dbg["reject_reasons"][f"{stage}:{reason}"] += 1
                for key in ("v60_short_score", "v52_score"):
                    if key in meta:
                        val = float(meta.get(key) or 0.0)
                        dbg["score_sum"] += val
                        dbg["score_count"] += 1
                        dbg["score_max"] = max(float(dbg.get("score_max", 0.0) or 0.0), val)
                        break
                reasons = meta.get("v60_reasons") or meta.get("v52_reasons") or []
                if isinstance(reasons, (list, tuple)):
                    for r in reasons[:5]:
                        dbg["reject_reasons"][f"{stage}:{r}"] += 1
        except Exception:
            pass

    def v60_1_short_debug_summary_rows(self) -> list[str]:
        dbg = getattr(self, "v60_1_short_debug", None)
        if not isinstance(dbg, dict):
            return []
        counters = dbg.get("counters") or Counter()
        reasons = dbg.get("reject_reasons") or Counter()
        rows = []
        main_keys = [
            "bear_state", "bear_pullback_path", "pullback_checked", "pullback_ok", "btc_ok", "btc_short_ok", "v43_ok", "v60_checked", "v60_ok", "regime_gate_ok", "trend_quality_ok", "short_stack_ok", "signal_returned",
        ]
        for k in main_keys:
            rows.append(f"{k}={int(counters.get(k, 0))}")
        score_count = int(dbg.get("score_count", 0) or 0)
        if score_count:
            rows.append(f"avg_v60_score={float(dbg.get('score_sum',0.0))/score_count:.4f}")
            rows.append(f"max_v60_score={float(dbg.get('score_max',0.0)):.4f}")
        top_n = int(getattr(cfg, "V60_1_SHORT_DEBUG_TOP_REASONS", 12))
        if reasons:
            top = reasons.most_common(top_n)
            rows.append("top_rejects=" + ",".join(f"{k}:{v}" for k, v in top))
        return rows

    def _eth_debug_enabled(self) -> bool:
        return bool(getattr(cfg, "V14_ETH_DEBUG_ENABLED", False)) and str(self._current_symbol or "") in set(getattr(cfg, "V14_ETH_ENGINE_SYMBOLS", ["ETHUSDT", "SOLUSDT", "AVAXUSDT", "BNBUSDT"]) or ["ETHUSDT", "SOLUSDT", "AVAXUSDT", "BNBUSDT"])

    def _eth_debug(self, event: str, **payload) -> None:
        if not self._eth_debug_enabled():
            return
        msg = "[ETH_ENGINE_DEBUG] " + event
        if payload:
            msg += " | " + ", ".join(f"{k}={v}" for k, v in payload.items())
        logger.debug(msg)
        if bool(getattr(cfg, "V14_ETH_DEBUG_STDOUT_ENABLED", False)):
            print(msg)
        if bool(getattr(cfg, "V14_ETH_DEBUG_FILE_ENABLED", True)):
            path = os.path.abspath(str(getattr(cfg, "V14_ETH_DEBUG_FILE_PATH", "eth_liquidity_debug_trace.txt")))
            if not getattr(self, "_eth_debug_file_initialized", False):
                if bool(getattr(cfg, "V14_ETH_DEBUG_RESET_FILE_ON_START", True)):
                    try:
                        open(path, "w", encoding="utf-8").close()
                    except Exception:
                        pass
                self._eth_debug_file_initialized = True
            try:
                with open(path, "a", encoding="utf-8") as fh:
                    fh.write(msg + "\n")
            except Exception:
                pass

    def _apply_directional_setup_scaling(self, symbol: str, base_risk_multiplier: float, adx_h: float, drift: float, volume_meta: dict | None = None, trade_type: str = "", side: str = "", market_state: str = "", trend_quality_meta: dict | None = None) -> tuple[float, dict]:
        return apply_directional_setup_scaling_helper(self, symbol=symbol, base_risk_multiplier=base_risk_multiplier, adx_h=adx_h, drift=drift, volume_meta=volume_meta, trade_type=trade_type, side=side, market_state=market_state, trend_quality_meta=trend_quality_meta)

    def _apply_v7_direct_boost(self, symbol: str, side: str, trade_type: str, base_risk_multiplier: float, adx_h: float, drift: float, volume_meta: dict | None = None, strong_setup: bool = False, regime_gate_meta: dict | None = None) -> tuple[float, dict]:
        return apply_v7_direct_boost_helper(self, symbol=symbol, side=side, trade_type=trade_type, base_risk_multiplier=base_risk_multiplier, adx_h=adx_h, drift=drift, volume_meta=volume_meta, strong_setup=strong_setup, regime_gate_meta=regime_gate_meta)

    def _apply_v78_selective_risk_reduction(self, symbol: str, side: str, trade_type: str, base_risk_multiplier: float, market_state: str = "", regime: str = "", regime_gate_meta: dict | None = None, trend_quality_meta: dict | None = None, volume_meta: dict | None = None, strong_setup: bool = False, v7_flags: dict | None = None) -> tuple[float, dict]:
        return apply_v78_selective_risk_reduction_helper(self, symbol=symbol, side=side, trade_type=trade_type, base_risk_multiplier=base_risk_multiplier, market_state=market_state, regime=regime, regime_gate_meta=regime_gate_meta, trend_quality_meta=trend_quality_meta, volume_meta=volume_meta, strong_setup=strong_setup, v7_flags=v7_flags)

    def _apply_v21_regime_aware_adjustment(self, symbol: str, side: str, trade_type: str, base_risk_multiplier: float, market_state: str = "", regime: str = "", adx_h: float = 0.0, drift: float = 0.0, volume_meta: dict | None = None, strong_setup: bool = False) -> tuple[float, dict]:
        return apply_v21_regime_aware_adjustment_helper(self, symbol=symbol, side=side, trade_type=trade_type, base_risk_multiplier=base_risk_multiplier, market_state=market_state, regime=regime, adx_h=adx_h, drift=drift, volume_meta=volume_meta, strong_setup=strong_setup)

    def _apply_v24_profit_engine_adjustment(self, symbol: str, side: str, trade_type: str, base_risk_multiplier: float, market_state: str = "", regime: str = "", adx_h: float = 0.0, drift: float = 0.0, volume_meta: dict | None = None, strong_setup: bool = False) -> tuple[float, dict]:
        return apply_v24_profit_engine_adjustment_helper(self, symbol=symbol, side=side, trade_type=trade_type, base_risk_multiplier=base_risk_multiplier, market_state=market_state, regime=regime, adx_h=adx_h, drift=drift, volume_meta=volume_meta, strong_setup=strong_setup)

    def _apply_v80_alt_engine_upgrade(self, symbol: str, side: str, trade_type: str, risk_multiplier: float, alt_meta: dict | None = None, btc_meta: dict | None = None, rs_meta: dict | None = None, adx_h: float = 0.0, drift: float = 0.0, volume_meta: dict | None = None, strong_setup: bool = False, regime_gate_meta: dict | None = None) -> tuple[float, dict]:
        return apply_v80_alt_engine_upgrade_helper(self, symbol=symbol, side=side, trade_type=trade_type, risk_multiplier=risk_multiplier, alt_meta=alt_meta, btc_meta=btc_meta, rs_meta=rs_meta, adx_h=adx_h, drift=drift, volume_meta=volume_meta, strong_setup=strong_setup, regime_gate_meta=regime_gate_meta)

    def _calc_recent_wickiness(self, recent: pd.DataFrame) -> float:
        from .mtf_market_helpers import calc_recent_wickiness
        return calc_recent_wickiness(recent)

    def _calc_false_breakout_ratio(self, recent: pd.DataFrame, lookback: int = 12) -> float:
        from .mtf_market_helpers import calc_false_breakout_ratio
        return calc_false_breakout_ratio(recent, lookback=lookback)

    def _alt_trace_enabled(self) -> bool:
        return bool(getattr(cfg, "ALT_TRACE_BUILD_ENABLED", False) or getattr(cfg, "ALT_TRACE_FILE_ENABLED", False))

    def _alt_trace_stdout_enabled(self) -> bool:
        return bool(getattr(cfg, "ALT_TRACE_STDOUT_ENABLED", False))

    def _alt_trace_file_enabled(self) -> bool:
        return bool(getattr(cfg, "ALT_TRACE_FILE_ENABLED", False))

    def _resolve_alt_trace_path(self) -> str:
        configured = str(getattr(cfg, "ALT_TRACE_FILE_PATH", "alt_trace_only.txt") or "alt_trace_only.txt")
        if os.path.isabs(configured):
            return configured
        return os.path.abspath(os.path.join(os.getcwd(), configured))

    def _maybe_reset_alt_trace_file(self) -> None:
        if not self._alt_trace_file_enabled() or self._trace_file_initialized:
            return
        path = self._resolve_alt_trace_path()
        self._trace_file_path = path
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        if bool(getattr(cfg, "ALT_TRACE_RESET_FILE_ON_START", True)):
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("")
        self._trace_file_initialized = True

    def _alt_trace(self, event: str, symbol: str = "", **fields) -> None:
        if not self._alt_trace_enabled():
            return
        symbol = str(symbol or self._current_symbol or "")
        allowed_symbols = set(getattr(cfg, "ALT_TRACE_SYMBOLS", ["ETHUSDT"]) or [])
        if symbol and allowed_symbols and symbol not in allowed_symbols:
            return
        merged = {}
        if symbol:
            merged["symbol"] = symbol
        merged.update(fields)
        parts = [f"{k}={v}" for k, v in merged.items()]
        msg = f"[ALT_TRACE] {event}"
        if parts:
            msg += " | " + ", ".join(parts)
        if self._alt_trace_stdout_enabled() or not self._alt_trace_file_enabled():
            print(msg)
        if self._alt_trace_file_enabled():
            self._maybe_reset_alt_trace_file()
            path = self._trace_file_path or self._resolve_alt_trace_path()
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(msg + "\n")

    def _btc_range_debug_enabled(self) -> bool:
        return bool(getattr(cfg, "BTC_RANGE_DEBUG_ENABLED", False) or getattr(cfg, "BTC_RANGE_DEBUG_FILE_ENABLED", False))

    def _btc_range_debug_stdout_enabled(self) -> bool:
        return bool(getattr(cfg, "BTC_RANGE_DEBUG_STDOUT_ENABLED", False))

    def _btc_range_debug_file_enabled(self) -> bool:
        return bool(getattr(cfg, "BTC_RANGE_DEBUG_FILE_ENABLED", False))

    def _resolve_btc_range_debug_path(self) -> str:
        configured = str(getattr(cfg, "BTC_RANGE_DEBUG_FILE_PATH", "btc_range_debug_trace.txt") or "btc_range_debug_trace.txt")
        if os.path.isabs(configured):
            return configured
        return os.path.abspath(os.path.join(os.getcwd(), configured))

    def _maybe_reset_btc_range_debug_file(self) -> None:
        if not self._btc_range_debug_file_enabled() or self._btc_range_debug_file_initialized:
            return
        path = self._resolve_btc_range_debug_path()
        self._btc_range_debug_file_path = path
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        if bool(getattr(cfg, "BTC_RANGE_DEBUG_RESET_FILE_ON_START", True)):
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("")
        self._btc_range_debug_file_initialized = True

    def _btc_range_debug(self, event: str, symbol: str = "", **fields) -> None:
        if not self._btc_range_debug_enabled():
            return
        symbol = str(symbol or self._current_symbol or "")
        allowed_symbols = set(getattr(cfg, "BTC_RANGE_DEBUG_SYMBOLS", ["BTCUSDT"]) or ["BTCUSDT"])
        if symbol and allowed_symbols and symbol not in allowed_symbols:
            return
        merged = {}
        if symbol:
            merged["symbol"] = symbol
        merged.update(fields)
        parts = [f"{k}={v}" for k, v in merged.items()]
        msg = f"[BTC_RANGE_DEBUG] {event}"
        if parts:
            msg += " | " + ", ".join(parts)
        if self._btc_range_debug_stdout_enabled() or not self._btc_range_debug_file_enabled():
            print(msg)
        if self._btc_range_debug_file_enabled():
            self._maybe_reset_btc_range_debug_file()
            path = self._btc_range_debug_file_path or self._resolve_btc_range_debug_path()
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(msg + "\n")

    def _should_block_btc_profit_mode_signal(self, signal: Optional[str], trade_type: str | None, meta: dict) -> tuple[bool, str]:
        symbol = str(meta.get("symbol") or self._current_symbol or "")
        if signal != "buy" or symbol != "BTCUSDT":
            return False, ""
        tt = str(trade_type or "").lower()
        market_state = str(meta.get("market_state") or getattr(self, "_current_market_state", "unknown") or "unknown").lower()
        adx_h = float(meta.get("adx_h") or getattr(self, "_current_adx_h", 0.0) or 0.0)
        drift = float(meta.get("drift") or getattr(self, "_current_drift", 0.0) or 0.0)

        range_engine_enabled = bool(cfg.get_symbol_param_bool(symbol, "BTC_RANGE_ENGINE_ENABLED", bool(getattr(cfg, "BTC_RANGE_ENGINE_ENABLED", False))))
        range_types = cfg.get_symbol_param(symbol, "BTC_RANGE_ALLOWED_TYPES", getattr(cfg, "BTC_RANGE_ALLOWED_TYPES", [])) or []
        range_types = {str(x).lower() for x in range_types}
        if range_engine_enabled and tt in range_types:
            allowed_states = cfg.get_symbol_param(symbol, "BTC_RANGE_ALLOWED_MARKET_STATES", getattr(cfg, "BTC_RANGE_ALLOWED_MARKET_STATES", [])) or []
            allowed_states = {str(x).lower() for x in allowed_states}
            max_adx = float(cfg.get_symbol_param_float(symbol, "BTC_RANGE_MAX_ADX_H", float(getattr(cfg, "BTC_RANGE_MAX_ADX_H", 999.0))))
            max_drift = float(cfg.get_symbol_param_float(symbol, "BTC_RANGE_MAX_DRIFT_PCT", float(getattr(cfg, "BTC_RANGE_MAX_DRIFT_PCT", 999.0))))
            if allowed_states and market_state not in allowed_states:
                return True, f"btc_range_bad_state:{market_state}"
            if adx_h > max_adx or drift > max_drift:
                return True, f"btc_range_too_trendy:adx={adx_h:.2f},drift={drift:.5f}"
            return False, ""

        if not bool(cfg.get_symbol_param_bool(symbol, "BTC_NO_TRADE_FILTER_ENABLED", bool(getattr(cfg, "BTC_NO_TRADE_FILTER_ENABLED", False)))):
            return False, ""
        allowed_types = cfg.get_symbol_param(symbol, "BTC_NO_TRADE_ALLOWED_TYPES", getattr(cfg, "BTC_NO_TRADE_ALLOWED_TYPES", [])) or []
        allowed_types = {str(x).lower() for x in allowed_types}
        if allowed_types and tt and tt not in allowed_types:
            return True, f"btc_trade_type_blocked:{tt}"
        blocked_states = cfg.get_symbol_param(symbol, "BTC_NO_TRADE_BLOCKED_MARKET_STATES", getattr(cfg, "BTC_NO_TRADE_BLOCKED_MARKET_STATES", [])) or []
        blocked_states = {str(x).lower() for x in blocked_states}
        if market_state in blocked_states:
            return True, f"btc_bad_market_state:{market_state}"
        min_adx = float(cfg.get_symbol_param_float(symbol, "BTC_NO_TRADE_MIN_ADX_H", float(getattr(cfg, "BTC_NO_TRADE_MIN_ADX_H", 0.0))))
        min_drift = float(cfg.get_symbol_param_float(symbol, "BTC_NO_TRADE_MIN_DRIFT_PCT", float(getattr(cfg, "BTC_NO_TRADE_MIN_DRIFT_PCT", 0.0))))
        if tt == "continuation":
            min_adx = float(cfg.get_symbol_param_float(symbol, "BTC_CONTINUATION_NO_TRADE_MIN_ADX_H", float(getattr(cfg, "BTC_CONTINUATION_NO_TRADE_MIN_ADX_H", min_adx))))
            min_drift = float(cfg.get_symbol_param_float(symbol, "BTC_CONTINUATION_NO_TRADE_MIN_DRIFT_PCT", float(getattr(cfg, "BTC_CONTINUATION_NO_TRADE_MIN_DRIFT_PCT", min_drift))))
        elif tt == "impulse":
            min_adx = float(cfg.get_symbol_param_float(symbol, "BTC_IMPULSE_NO_TRADE_MIN_ADX_H", min_adx))
            min_drift = float(cfg.get_symbol_param_float(symbol, "BTC_IMPULSE_NO_TRADE_MIN_DRIFT_PCT", min_drift))
            allowed_states = cfg.get_symbol_param(symbol, "BTC_IMPULSE_ALLOWED_MARKET_STATES", getattr(cfg, "BTC_IMPULSE_ALLOWED_MARKET_STATES", ["trend"])) or ["trend"]
            allowed_states = {str(x).lower() for x in allowed_states}
            if allowed_states and market_state not in allowed_states:
                return True, f"btc_impulse_bad_state:{market_state}"
            if bool(cfg.get_symbol_param_bool(symbol, "BTC_IMPULSE_REQUIRE_STRONG_SETUP", bool(getattr(cfg, "BTC_IMPULSE_REQUIRE_STRONG_SETUP", False)))) and not bool(meta.get("strong_setup", False)):
                return True, "btc_impulse_requires_strong_setup"
            impulse_meta = meta.get("impulse_meta") or {}
            try:
                imp_atr = max(float(impulse_meta.get("atr", 0.0) or 0.0), 1e-9)
                body_atr = float(impulse_meta.get("body", 0.0) or 0.0) / imp_atr
                range_atr = float(impulse_meta.get("range", 0.0) or 0.0) / imp_atr
                close_pos = float(impulse_meta.get("close_pos", 0.0) or 0.0)
            except Exception:
                body_atr = 0.0
                range_atr = 0.0
                close_pos = 0.0
            max_body_atr = float(cfg.get_symbol_param_float(symbol, "BTC_IMPULSE_ANTI_SPIKE_MAX_BODY_ATR", float(getattr(cfg, "BTC_IMPULSE_ANTI_SPIKE_MAX_BODY_ATR", 999.0))))
            max_range_atr = float(cfg.get_symbol_param_float(symbol, "BTC_IMPULSE_ANTI_SPIKE_MAX_RANGE_ATR", float(getattr(cfg, "BTC_IMPULSE_ANTI_SPIKE_MAX_RANGE_ATR", 999.0))))
            min_close_pos_imp = float(cfg.get_symbol_param_float(symbol, "BTC_IMPULSE_ANTI_SPIKE_MIN_CLOSE_POS", float(getattr(cfg, "BTC_IMPULSE_ANTI_SPIKE_MIN_CLOSE_POS", 0.0))))
            if body_atr > max_body_atr or range_atr > max_range_atr or close_pos < min_close_pos_imp:
                return True, f"btc_impulse_spike:block body_atr={body_atr:.2f},range_atr={range_atr:.2f},close_pos={close_pos:.2f}"
        elif tt == "pullback":
            min_adx = float(cfg.get_symbol_param_float(symbol, "BTC_PULLBACK_NO_TRADE_MIN_ADX_H", min_adx))
            min_drift = float(cfg.get_symbol_param_float(symbol, "BTC_PULLBACK_NO_TRADE_MIN_DRIFT_PCT", min_drift))
        if adx_h < min_adx or drift < min_drift:
            return True, f"btc_weak_{tt or 'market'}:adx={adx_h:.2f},drift={drift:.5f}"
        return False, ""

    def _tune_btc_profit_mode_risk(self, signal: Optional[str], trade_type: str | None, risk_multiplier: float, meta: dict) -> tuple[float, dict]:
        symbol = str(meta.get("symbol") or self._current_symbol or "")
        tuned = float(risk_multiplier)
        flags: dict = {}
        if signal != "buy" or symbol != "BTCUSDT":
            return tuned, flags
        tt = str(trade_type or "").lower()
        adx_h = float(meta.get("adx_h") or getattr(self, "_current_adx_h", 0.0) or 0.0)
        drift = float(meta.get("drift") or getattr(self, "_current_drift", 0.0) or 0.0)
        strong_setup = bool(meta.get("strong_setup", False))
        strong_types = cfg.get_symbol_param(symbol, "BTC_STAGE7_STRONG_TRADE_TYPES", getattr(cfg, "BTC_STAGE7_STRONG_TRADE_TYPES", [])) or []
        strong_types = {str(x).lower() for x in strong_types}
        strong_min_adx = float(cfg.get_symbol_param_float(symbol, "BTC_STAGE7_STRONG_MIN_ADX_H", float(getattr(cfg, "BTC_STAGE7_STRONG_MIN_ADX_H", 0.0))))
        strong_min_drift = float(cfg.get_symbol_param_float(symbol, "BTC_STAGE7_STRONG_MIN_DRIFT_PCT", float(getattr(cfg, "BTC_STAGE7_STRONG_MIN_DRIFT_PCT", 0.0))))
        strong_risk_mult = float(cfg.get_symbol_param_float(symbol, "BTC_STAGE7_STRONG_RISK_MULT", float(getattr(cfg, "BTC_STAGE7_STRONG_RISK_MULT", 1.0))))
        weak_cont_mult = float(cfg.get_symbol_param_float(symbol, "BTC_STAGE7_WEAK_CONTINUATION_RISK_MULT", float(getattr(cfg, "BTC_STAGE7_WEAK_CONTINUATION_RISK_MULT", 1.0))))
        weak_cont_min_adx = float(cfg.get_symbol_param_float(symbol, "BTC_STAGE7_WEAK_CONT_MIN_ADX_H", float(getattr(cfg, "BTC_STAGE7_WEAK_CONT_MIN_ADX_H", strong_min_adx))))
        weak_cont_min_drift = float(cfg.get_symbol_param_float(symbol, "BTC_STAGE7_WEAK_CONT_MIN_DRIFT_PCT", float(getattr(cfg, "BTC_STAGE7_WEAK_CONT_MIN_DRIFT_PCT", strong_min_drift))))
        range_engine_enabled = bool(cfg.get_symbol_param_bool(symbol, "BTC_RANGE_ENGINE_ENABLED", bool(getattr(cfg, "BTC_RANGE_ENGINE_ENABLED", False))))
        range_types = cfg.get_symbol_param(symbol, "BTC_RANGE_ALLOWED_TYPES", getattr(cfg, "BTC_RANGE_ALLOWED_TYPES", [])) or []
        range_types = {str(x).lower() for x in range_types}
        range_risk_mult = float(cfg.get_symbol_param_float(symbol, "BTC_RANGE_RISK_MULT", float(getattr(cfg, "BTC_RANGE_RISK_MULT", 1.0))))
        if range_engine_enabled and tt in range_types:
            tuned *= range_risk_mult
            flags.update({"btc_stage8_range_engine": True, "btc_stage8_range_risk_mult": range_risk_mult, "btc_stage7_tier": "range_engine"})
        elif tt in strong_types and strong_setup and adx_h >= strong_min_adx and drift >= strong_min_drift and strong_risk_mult > 1.0:
            tuned *= strong_risk_mult
            flags.update({"btc_stage7_risk_tuned": True, "btc_stage7_tier": "strong_trend", "btc_stage7_risk_mult": strong_risk_mult})
        elif tt == "continuation" and ((not strong_setup) or adx_h < weak_cont_min_adx or drift < weak_cont_min_drift) and weak_cont_mult < 1.0:
            tuned *= weak_cont_mult
            flags.update({"btc_stage7_risk_tuned": True, "btc_stage7_tier": "weak_continuation", "btc_stage7_risk_mult": weak_cont_mult})
        return tuned, flags


    def _check_btc_liquidity_reversal(self, *, symbol: str, market_state: str, df: pd.DataFrame, recent: pd.DataFrame, range_high: float, range_low: float, atr_ltf: float, adx_h: float, drift: float, bar_index: int) -> tuple[str | None, dict]:
        if symbol != "BTCUSDT" or not bool(cfg.get_symbol_param_bool(symbol, "BTC_LIQUIDITY_REVERSAL_ENABLED", bool(getattr(cfg, "BTC_LIQUIDITY_REVERSAL_ENABLED", False)))):
            return None, {"reason": "disabled"}
        allowed_states = set(cfg.get_symbol_param(symbol, "BTC_LIQUIDITY_REVERSAL_ALLOWED_STATES", getattr(cfg, "BTC_LIQUIDITY_REVERSAL_ALLOWED_STATES", ["range", "flat", "transition"])) or [])
        if market_state not in allowed_states:
            return None, {"reason": "market_state_not_allowed", "market_state": market_state}
        if adx_h > float(cfg.get_symbol_param_float(symbol, "BTC_LIQUIDITY_REVERSAL_MAX_ADX_H", float(getattr(cfg, "BTC_LIQUIDITY_REVERSAL_MAX_ADX_H", 18.5)))):
            return None, {"reason": "adx_too_high", "adx_h": adx_h}
        if abs(drift) > float(cfg.get_symbol_param_float(symbol, "BTC_LIQUIDITY_REVERSAL_MAX_DRIFT_PCT", float(getattr(cfg, "BTC_LIQUIDITY_REVERSAL_MAX_DRIFT_PCT", 0.0038)))):
            return None, {"reason": "drift_too_high", "drift": drift}
        cooldown_bars = int(cfg.get_symbol_param_int(symbol, "BTC_LIQUIDITY_REVERSAL_COOLDOWN_BARS", int(getattr(cfg, "BTC_LIQUIDITY_REVERSAL_COOLDOWN_BARS", 72))))
        if bar_index - int(getattr(self, "_last_btc_liquidity_reversal_bar_index", -10**9)) < cooldown_bars:
            return None, {"reason": "cooldown_active"}
        max_signals_per_day = int(cfg.get_symbol_param_int(symbol, "BTC_LIQUIDITY_MAX_SIGNALS_PER_DAY", int(getattr(cfg, "BTC_LIQUIDITY_MAX_SIGNALS_PER_DAY", 2))))
        last_ts = recent.index[-1] if hasattr(recent, "index") and len(recent.index) else None
        if hasattr(last_ts, "date"):
            day_key = str(last_ts.date())
        else:
            day_key = f"bucket_{bar_index // 96}"
        daily_counts = getattr(self, "_btc_liquidity_daily_counts", None)
        if not isinstance(daily_counts, dict):
            daily_counts = {}
            self._btc_liquidity_daily_counts = daily_counts
        if int(daily_counts.get(day_key, 0)) >= max_signals_per_day:
            return None, {"reason": "daily_limit_reached", "day_key": day_key}
        ok, meta = check_fakeout_reversal_entry(symbol=symbol, df=df, recent=recent, side="long", range_high=range_high, range_low=range_low, atr_ltf=atr_ltf, adx_h=adx_h)
        if not ok:
            return None, meta
        meta = dict(meta or {})
        meta["reason"] = "btc_liquidity_reversal"
        meta["drift"] = drift
        meta["strong_setup"] = True
        meta["adx_h"] = adx_h
        return "buy", meta

    def _check_stage10v2_basic_btc_mr(self, *, symbol: str, market_state: str, recent: pd.DataFrame, candle: pd.Series, atr_ltf: float, adx_h: float, drift: float, bar_index: int) -> tuple[str | None, dict]:
        if symbol != "BTCUSDT" or not bool(cfg.get_symbol_param_bool(symbol, "BTC_STAGE10V2_BASIC_MR_ENABLED", bool(getattr(cfg, "BTC_STAGE10V2_BASIC_MR_ENABLED", False)))):
            return None, {"reason": "disabled"}
        cooldown_bars = int(cfg.get_symbol_param_int(symbol, "BTC_STAGE10V2_BASIC_MR_COOLDOWN_BARS", int(getattr(cfg, "BTC_STAGE10V2_BASIC_MR_COOLDOWN_BARS", 96))))
        if bar_index - int(getattr(self, "_last_btc_stage10v2_mr_bar_index", -10**9)) < cooldown_bars:
            return None, {"reason": "cooldown_active"}
        allowed_states = set(cfg.get_symbol_param(symbol, "BTC_STAGE10V2_BASIC_MR_ALLOWED_STATES", getattr(cfg, "BTC_STAGE10V2_BASIC_MR_ALLOWED_STATES", ["range", "flat", "chop"])) or [])
        if market_state not in allowed_states:
            return None, {"reason": "market_state_not_allowed", "market_state": market_state}
        if atr_ltf <= 0 or recent is None or len(recent) < 20:
            return None, {"reason": "not_enough_data"}
        if adx_h > float(cfg.get_symbol_param_float(symbol, "BTC_STAGE10V2_BASIC_MR_MAX_ADX_H", float(getattr(cfg, "BTC_STAGE10V2_BASIC_MR_MAX_ADX_H", 16.5)))):
            return None, {"reason": "adx_too_high", "adx_h": adx_h}
        if abs(drift) > float(cfg.get_symbol_param_float(symbol, "BTC_STAGE10V2_BASIC_MR_MAX_DRIFT_PCT", float(getattr(cfg, "BTC_STAGE10V2_BASIC_MR_MAX_DRIFT_PCT", 0.0032)))):
            return None, {"reason": "drift_too_high", "drift": drift}
        open_ = float(candle.get("open", float("nan")))
        high = float(candle.get("high", float("nan")))
        low = float(candle.get("low", float("nan")))
        close = float(candle.get("close", float("nan")))
        ema20 = float(candle.get("EMA20", float("nan")))
        rsi = float(candle.get("RSI", float("nan")))
        volume = float(candle.get("volume", float("nan")))
        if any(pd.isna(v) for v in [open_, high, low, close, ema20, rsi, volume]) or close <= 0:
            return None, {"reason": "nan_values"}
        candle_range = max(high - low, 1e-9)
        close_pos = (close - low) / candle_range
        lower_wick_ratio = max(0.0, min(open_, close) - low) / candle_range
        body_atr = abs(close - open_) / max(atr_ltf, 1e-9)
        neg_progress_atr = max(open_ - close, 0.0) / max(atr_ltf, 1e-9)
        dev_atr = (ema20 - close) / max(atr_ltf, 1e-9)
        vols = recent["volume"].astype(float).tail(12) if "volume" in recent.columns else pd.Series(dtype=float)
        vol_ma = float(vols.mean()) if len(vols) else volume
        vol_ratio = (volume / vol_ma) if vol_ma > 0 else 1.0
        require_green = bool(cfg.get_symbol_param_bool(symbol, "BTC_STAGE10V2_BASIC_MR_REQUIRE_GREEN_CANDLE", bool(getattr(cfg, "BTC_STAGE10V2_BASIC_MR_REQUIRE_GREEN_CANDLE", True))))
        if require_green and close < open_:
            return None, {"reason": "not_green"}
        if rsi > float(cfg.get_symbol_param_float(symbol, "BTC_STAGE10V2_BASIC_MR_RSI_LONG_MAX", float(getattr(cfg, "BTC_STAGE10V2_BASIC_MR_RSI_LONG_MAX", 31.0)))):
            return None, {"reason": "rsi_not_oversold", "rsi": rsi}
        if dev_atr < float(cfg.get_symbol_param_float(symbol, "BTC_STAGE10V2_BASIC_MR_MIN_DEV_ATR", float(getattr(cfg, "BTC_STAGE10V2_BASIC_MR_MIN_DEV_ATR", 1.10)))):
            return None, {"reason": "not_far_from_mean", "dev_atr": dev_atr}
        if close_pos < float(cfg.get_symbol_param_float(symbol, "BTC_STAGE10V2_BASIC_MR_MIN_CLOSE_POS", float(getattr(cfg, "BTC_STAGE10V2_BASIC_MR_MIN_CLOSE_POS", 0.62)))):
            return None, {"reason": "close_pos_too_low", "close_pos": close_pos}
        if lower_wick_ratio < float(cfg.get_symbol_param_float(symbol, "BTC_STAGE10V2_BASIC_MR_MIN_REJECT_WICK", float(getattr(cfg, "BTC_STAGE10V2_BASIC_MR_MIN_REJECT_WICK", 0.16)))):
            return None, {"reason": "wick_too_small", "lower_wick_ratio": lower_wick_ratio}
        if body_atr > float(cfg.get_symbol_param_float(symbol, "BTC_STAGE10V2_BASIC_MR_MAX_BODY_ATR", float(getattr(cfg, "BTC_STAGE10V2_BASIC_MR_MAX_BODY_ATR", 0.42)))):
            return None, {"reason": "body_too_large", "body_atr": body_atr}
        if neg_progress_atr > float(cfg.get_symbol_param_float(symbol, "BTC_STAGE10V2_BASIC_MR_MAX_NEG_PROGRESS_ATR", float(getattr(cfg, "BTC_STAGE10V2_BASIC_MR_MAX_NEG_PROGRESS_ATR", 0.28)))):
            return None, {"reason": "negative_progress_too_large", "neg_progress_atr": neg_progress_atr}
        if vol_ratio < float(cfg.get_symbol_param_float(symbol, "BTC_STAGE10V2_BASIC_MR_MIN_VOL_RATIO", float(getattr(cfg, "BTC_STAGE10V2_BASIC_MR_MIN_VOL_RATIO", 0.92)))):
            return None, {"reason": "vol_ratio_too_low", "vol_ratio": vol_ratio}
        return "buy", {"reason": "stage10v2_basic_btc_mr", "rsi": rsi, "dev_atr": dev_atr, "close_pos": close_pos, "lower_wick_ratio": lower_wick_ratio, "body_atr": body_atr, "neg_progress_atr": neg_progress_atr, "vol_ratio": vol_ratio}

    def _set_signal(self, signal: Optional[str], trade_type: str | None = None, risk_multiplier: float = 1.0, **meta):
        exec_risk = float(risk_multiplier)
        symbol = str(meta.get("symbol") or self._current_symbol or "")
        side = str(meta.get("side") or ("short" if signal == "sell" else "long" if signal == "buy" else "")).lower()
        regime = str(meta.get("regime") or self._current_regime or "")
        self._alt_trace("set_signal_call", symbol=symbol, signal=signal, trade_type=trade_type, risk_multiplier=exec_risk, regime=regime, side=side)
        if signal == "sell" and side == "short":
            bypass_range_short_block = bool(meta.get("allow_btc_range_short_bypass", False))
            disable_all_btc_shorts = bool(cfg.get_symbol_param_bool(symbol, "BTC_DISABLE_ALL_SHORTS", bool(getattr(cfg, "BTC_DISABLE_ALL_SHORTS", False))))
            if symbol == "BTCUSDT" and disable_all_btc_shorts and not bypass_range_short_block:
                self._btc_range_debug("short_blocked_global", symbol=symbol, trade_type=trade_type, side=side, bypass=bypass_range_short_block)
                self.last_signal_meta = build_signal_meta(
                    signal=None,
                    trade_type=trade_type,
                    risk_multiplier=1.0,
                    execution_risk_multiplier=1.0,
                    v84_short_suppressed=True,
                    v84_short_suppression_reason="btc_disable_all_shorts",
                    **meta,
                )
                self._alt_trace("set_signal_return", symbol=symbol, signal=None, trade_type=trade_type, risk_multiplier=1.0, regime=regime, side=side, suppressed=True)
                return None
            if (not bypass_range_short_block) and self._should_suppress_short_signal(symbol=symbol, trade_type=trade_type, regime=regime, meta=meta):
                self._btc_range_debug("short_blocked_pipeline", symbol=symbol, trade_type=trade_type, side=side, regime=regime, reason=self._build_short_suppression_reason(symbol=symbol, trade_type=trade_type, regime=regime, meta=meta))
                self.last_signal_meta = build_signal_meta(
                    signal=None,
                    trade_type=trade_type,
                    risk_multiplier=1.0,
                    execution_risk_multiplier=1.0,
                    v84_short_suppressed=True,
                    v84_short_suppression_reason=self._build_short_suppression_reason(symbol=symbol, trade_type=trade_type, regime=regime, meta=meta),
                    **meta,
                )
                self._alt_trace("set_signal_return", symbol=symbol, signal=None, trade_type=trade_type, risk_multiplier=1.0, regime=regime, side=side, suppressed=True)
                return None
        block_btc_profit_mode, block_reason = self._should_block_btc_profit_mode_signal(signal=signal, trade_type=trade_type, meta=meta)
        if block_btc_profit_mode:
            self.last_signal_meta = build_signal_meta(
                signal=None,
                trade_type=trade_type,
                risk_multiplier=1.0,
                execution_risk_multiplier=1.0,
                btc_no_trade_filtered=True,
                btc_no_trade_reason=block_reason,
                **meta,
            )
            self._alt_trace("set_signal_return", symbol=symbol, signal=None, trade_type=trade_type, risk_multiplier=1.0, regime=regime, side=side, suppressed=True, reason=block_reason)
            return None
        exec_risk, btc_stage7_flags = self._tune_btc_profit_mode_risk(signal=signal, trade_type=trade_type, risk_multiplier=exec_risk, meta=meta)
        if signal == "sell" and side == "short":
            self._btc_range_debug("short_signal_accepted", symbol=symbol, trade_type=trade_type, side=side, regime=regime, risk_multiplier=exec_risk)
        self.last_signal_meta = build_signal_meta(
            signal=signal,
            trade_type=trade_type,
            risk_multiplier=exec_risk,
            execution_risk_multiplier=exec_risk,
            **meta,
            **btc_stage7_flags,
        )
        self._alt_trace("set_signal_return", symbol=symbol, signal=signal, trade_type=trade_type, risk_multiplier=exec_risk, regime=regime, side=side, suppressed=False)
        return signal

    def _build_short_suppression_reason(self, symbol: str, trade_type: str | None, regime: str, meta: dict) -> str:
        return build_short_suppression_reason(cfg=cfg, symbol=symbol, trade_type=trade_type, regime=regime, meta=meta)

    def _should_suppress_short_signal(self, symbol: str, trade_type: str | None, regime: str, meta: dict) -> bool:
        return should_suppress_short_signal(
            cfg=cfg,
            symbol=symbol,
            trade_type=trade_type,
            regime=regime,
            meta=meta,
            reason_builder=self._build_short_suppression_reason,
        )
    def _apply_v85_inline_short_suppression(self, symbol: str, trade_type: str | None, market_state: str, regime: str,
                                            btc_meta: dict | None = None, rs_meta: dict | None = None,
                                            trend_quality_meta: dict | None = None, regime_gate_meta: dict | None = None,
                                            strong_setup: bool = False) -> tuple[bool, dict]:
        if not bool(getattr(cfg, "V85_INLINE_SHORT_SUPPRESSION_ENABLED", True)):
            return True, {"v85_short_suppressed": False, "v85_short_suppression_reason": "disabled"}
        allowed_symbols = set(getattr(cfg, "V85_INLINE_SHORT_SUPPRESSION_SYMBOLS", ["BTCUSDT", "ETHUSDT"]) or [])
        if symbol and allowed_symbols and symbol not in allowed_symbols:
            return True, {"v85_short_suppressed": False, "v85_short_suppression_reason": "symbol_not_enabled"}
        allowed_types = {str(x).lower() for x in (getattr(cfg, "V85_INLINE_SHORT_SUPPRESSION_ALLOWED_TYPES", ["impulse", "continuation", "cont_compression", "pullback", "fakeout", "btc_exhaustion"]) or [])}
        tt = str(trade_type or "").lower()
        if tt and tt not in allowed_types:
            return True, {"v85_short_suppressed": False, "v85_short_suppression_reason": "type_not_enabled"}

        btc_meta = btc_meta or {}
        rs_meta = rs_meta or {}
        trend_quality_meta = trend_quality_meta or {}
        regime_gate_meta = regime_gate_meta or {}
        reasons = []
        bad_states = set(getattr(cfg, "V85_SHORT_BAD_MARKET_STATES", ["chop", "flat", "range", "transition"]) or [])
        if str(market_state or "") in bad_states:
            reasons.append(f"market_state={market_state}")
        if bool(getattr(cfg, "V85_SHORT_REQUIRE_BEAR_REGIME", True)) and str(regime or "") != "bear":
            reasons.append(f"regime={regime or 'none'}")
        btc_score = float((btc_meta.get("score", 0.0) or 0.0))
        if btc_score < float(getattr(cfg, "V85_SHORT_MIN_BTC_SCORE", 1.12)):
            reasons.append(f"btc_score={btc_score:.3f}")
        rs_ratio = float((rs_meta.get("ratio", 1.0) or 1.0))
        if rs_ratio > float(getattr(cfg, "V85_SHORT_MAX_RS_RATIO", 0.975)):
            reasons.append(f"rs_ratio={rs_ratio:.3f}")
        ema20_crosses = int(trend_quality_meta.get("ema20_crosses", 0) or 0)
        if ema20_crosses > int(getattr(cfg, "V85_SHORT_MAX_EMA20_CROSSES", 2)):
            reasons.append(f"ema20_crosses={ema20_crosses}")
        wick = float(trend_quality_meta.get("mean_wickiness", 0.0) or 0.0)
        if wick > float(getattr(cfg, "V85_SHORT_MAX_WICKINESS", 0.52)):
            reasons.append(f"wickiness={wick:.3f}")
        body = float(trend_quality_meta.get("mean_body_ratio", 1.0) or 1.0)
        if body < float(getattr(cfg, "V85_SHORT_MIN_BODY_RATIO", 0.34)):
            reasons.append(f"body_ratio={body:.3f}")
        gate_reason = str(regime_gate_meta.get("reason") or "")
        bad_gate_parts = [str(x).lower() for x in (getattr(cfg, "V85_SHORT_BAD_GATE_FRAGMENTS", ["transition", "regime_mismatch", "non_directional"]) or [])]
        if gate_reason and any(part in gate_reason.lower() for part in bad_gate_parts):
            reasons.append(f"gate={gate_reason}")
        req_strong = bool(getattr(cfg, "V85_SHORT_REQUIRE_STRONG_SETUP", True))
        req_types = {str(x).lower() for x in (getattr(cfg, "V85_SHORT_REQUIRE_STRONG_SETUP_TYPES", ["impulse", "continuation", "cont_compression", "pullback"]) or [])}
        if req_strong and tt in req_types and not strong_setup:
            reasons.append("no_strong_setup")
        min_reason_count = int(getattr(cfg, "V85_SHORT_MIN_REASON_COUNT", 1))
        suppressed = len(reasons) >= min_reason_count
        return (not suppressed), {"v85_short_suppressed": suppressed, "v85_short_suppression_reason": ", ".join(reasons) or "passed"}


    def _apply_v86_inline_long_suppression(self, symbol: str, trade_type: str | None, market_state: str, regime: str,
                                           btc_meta: dict | None = None, rs_meta: dict | None = None,
                                           trend_quality_meta: dict | None = None, regime_gate_meta: dict | None = None,
                                           volume_meta: dict | None = None, adx_h: float = 0.0, drift: float = 0.0,
                                           strong_setup: bool = False) -> tuple[bool, dict]:
        if not bool(getattr(cfg, "V86_INLINE_LONG_SUPPRESSION_ENABLED", True)):
            return True, {"v86_long_suppressed": False, "v86_long_suppression_reason": "disabled"}
        allowed_symbols = set(getattr(cfg, "V86_INLINE_LONG_SUPPRESSION_SYMBOLS", ["BTCUSDT", "ETHUSDT"]) or [])
        if symbol and allowed_symbols and symbol not in allowed_symbols:
            return True, {"v86_long_suppressed": False, "v86_long_suppression_reason": "symbol_not_enabled"}
        allowed_types = {str(x).lower() for x in (getattr(cfg, "V86_INLINE_LONG_SUPPRESSION_ALLOWED_TYPES", ["impulse", "continuation", "cont_compression", "pullback", "fakeout"]) or [])}
        tt = str(trade_type or "").lower()
        if tt and tt not in allowed_types:
            return True, {"v86_long_suppressed": False, "v86_long_suppression_reason": "type_not_enabled"}

        btc_meta = btc_meta or {}
        rs_meta = rs_meta or {}
        trend_quality_meta = trend_quality_meta or {}
        regime_gate_meta = regime_gate_meta or {}
        volume_meta = volume_meta or {}
        reasons = []
        bad_states = set(getattr(cfg, "V86_LONG_BAD_MARKET_STATES", ["chop", "flat", "range"]) or [])
        if str(market_state or "") in bad_states:
            reasons.append(f"market_state={market_state}")
        blocked_regimes = {str(x).lower() for x in (getattr(cfg, "V86_LONG_BAD_REGIMES", ["bear"]) or [])}
        if str(regime or "").lower() in blocked_regimes:
            reasons.append(f"regime={regime or 'none'}")
        btc_score = float((btc_meta.get("score", 0.0) or 0.0))
        if btc_score < float(getattr(cfg, "V86_LONG_MIN_BTC_SCORE", 1.04)):
            reasons.append(f"btc_score={btc_score:.3f}")
        rs_ratio = float((rs_meta.get("ratio", 1.0) or 1.0))
        if rs_ratio < float(getattr(cfg, "V86_LONG_MIN_RS_RATIO", 0.985)):
            reasons.append(f"rs_ratio={rs_ratio:.3f}")
        ema20_crosses = int(trend_quality_meta.get("ema20_crosses", 0) or 0)
        if ema20_crosses > int(getattr(cfg, "V86_LONG_MAX_EMA20_CROSSES", 3)):
            reasons.append(f"ema20_crosses={ema20_crosses}")
        wick = float(trend_quality_meta.get("mean_wickiness", 0.0) or 0.0)
        if wick > float(getattr(cfg, "V86_LONG_MAX_WICKINESS", 0.58)):
            reasons.append(f"wickiness={wick:.3f}")
        body = float(trend_quality_meta.get("mean_body_ratio", 1.0) or 1.0)
        if body < float(getattr(cfg, "V86_LONG_MIN_BODY_RATIO", 0.30)):
            reasons.append(f"body_ratio={body:.3f}")
        if float(adx_h or 0.0) < float(getattr(cfg, "V86_LONG_MIN_ADX", 18.0)):
            reasons.append(f"adx_h={float(adx_h or 0.0):.2f}")
        if float(drift or 0.0) < float(getattr(cfg, "V86_LONG_MIN_DRIFT_PCT", 0.0030)):
            reasons.append(f"drift={float(drift or 0.0):.4f}")
        impulse_score = float((volume_meta.get("impulse_score", 0.0) or 0.0))
        if impulse_score < float(getattr(cfg, "V86_LONG_MIN_IMPULSE_SCORE", 0.74)):
            reasons.append(f"impulse_score={impulse_score:.3f}")
        gate_reason = str(regime_gate_meta.get("reason") or "")
        bad_gate_parts = [str(x).lower() for x in (getattr(cfg, "V86_LONG_BAD_GATE_FRAGMENTS", ["non_directional", "regime_mismatch"]) or [])]
        if gate_reason and any(part in gate_reason.lower() for part in bad_gate_parts):
            reasons.append(f"gate={gate_reason}")
        req_strong = bool(getattr(cfg, "V86_LONG_REQUIRE_STRONG_SETUP", False))
        req_types = {str(x).lower() for x in (getattr(cfg, "V86_LONG_REQUIRE_STRONG_SETUP_TYPES", ["continuation", "cont_compression"]) or [])}
        if req_strong and tt in req_types and not strong_setup:
            reasons.append("no_strong_setup")
        min_reason_count = int(getattr(cfg, "V86_LONG_MIN_REASON_COUNT", 3))
        suppressed = len(reasons) >= min_reason_count
        return (not suppressed), {"v86_long_suppressed": suppressed, "v86_long_suppression_reason": ", ".join(reasons) or "passed"}

    def _symbol_flag(self, symbol: str, param_name: str, default: bool = False) -> bool:
        value = cfg.get_symbol_param(symbol, param_name, default)
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        try:
            return bool(int(value))
        except Exception:
            return bool(value)

    def _is_alt_symbol(self, symbol: str) -> bool:
        return is_alt_symbol_helper(self, symbol)


    def _alt_strong_setup(self, symbol: str, adx_h: float, drift: float, volume_meta: dict | None = None, rs_meta: dict | None = None, side: str = "long") -> bool:
        return alt_strong_setup_helper(self, symbol, adx_h, drift, volume_meta, rs_meta, side)


    def _alt_setup_tier(self, symbol: str, side: str, trade_type: str, adx_h: float, drift: float, volume_meta: dict | None = None, rs_meta: dict | None = None, alt_meta: dict | None = None) -> str:
        return alt_setup_tier_helper(self, symbol, side, trade_type, adx_h, drift, volume_meta, rs_meta, alt_meta)


    def _relax_alt_filters(self, symbol: str, side: str, alt_ok: bool, alt_meta: dict, rs_ok: bool, rs_meta: dict) -> tuple[bool, bool, dict, dict]:
        return relax_alt_filters_helper(self, symbol, side, alt_ok, alt_meta, rs_ok, rs_meta)


    def _alt_upgrade_gate(self, symbol: str, side: str, trade_type: str, alt_meta: dict | None = None, rs_meta: dict | None = None, btc_meta: dict | None = None, adx_h: float = 0.0, drift: float = 0.0, volume_meta: dict | None = None) -> tuple[bool, dict]:
        return alt_upgrade_gate_helper(self, symbol, side, trade_type, alt_meta, rs_meta, btc_meta, adx_h, drift, volume_meta)


    def _apply_alt_risk_adjustment(self, symbol: str, side: str, trade_type: str, risk_multiplier: float, strong_setup: bool = False, regime_gate_meta: dict | None = None, alt_meta: dict | None = None, rs_meta: dict | None = None, volume_meta: dict | None = None, adx_h: float = 0.0, drift: float = 0.0) -> tuple[float, dict]:
        return apply_alt_risk_adjustment_helper(self, symbol, side, trade_type, risk_multiplier, strong_setup, regime_gate_meta, alt_meta, rs_meta, volume_meta, adx_h, drift)


    def _apply_v80_short_control(self, symbol: str, side: str, trade_type: str, risk_multiplier: float, market_state: str = "", regime: str = "", btc_meta: dict | None = None, rs_meta: dict | None = None, trend_quality_meta: dict | None = None, strong_setup: bool = False, regime_gate_meta: dict | None = None) -> tuple[float, dict]:
        flags = {"v80_short_control_applied": False}
        risk_mult = float(risk_multiplier)
        if not bool(getattr(cfg, "V80_SHORT_CONTROL_ENABLED", True)):
            return risk_mult, flags
        if str(side or "").lower() != "short":
            return risk_mult, flags
        allowed_symbols = set(getattr(cfg, "V80_SHORT_CONTROL_SYMBOLS", ["BTCUSDT"]) or ["BTCUSDT"])
        if symbol not in allowed_symbols:
            return risk_mult, flags
        allowed_types = {str(v).lower() for v in (getattr(cfg, "V80_SHORT_CONTROL_ALLOWED_TYPES", ["impulse", "continuation", "cont_compression", "pullback"]) or ["impulse", "continuation", "cont_compression", "pullback"])}
        trade_type = str(trade_type or "").lower()
        if trade_type not in allowed_types:
            return risk_mult, flags
        btc_meta = btc_meta or {}
        rs_meta = rs_meta or {}
        trend_quality_meta = trend_quality_meta or {}
        btc_score = float(btc_meta.get("score", 0.0) or 0.0)
        rs_ratio = float(rs_meta.get("ratio", 1.0) or 1.0)
        ema20_crosses = int(trend_quality_meta.get("ema20_crosses", 0) or 0)
        mean_wickiness = float(trend_quality_meta.get("mean_wickiness", 0.0) or 0.0)
        mean_body_ratio = float(trend_quality_meta.get("mean_body_ratio", 1.0) or 1.0)

        mild_hits = []
        severe_hits = []
        if str(market_state or "") in set(getattr(cfg, "V80_SHORT_SEVERE_MARKET_STATES", ["chop", "range", "flat"]) or ["chop", "range", "flat"]):
            severe_hits.append(f"market_state:{market_state}")
        elif str(market_state or "") in set(getattr(cfg, "V80_SHORT_MILD_MARKET_STATES", ["transition"]) or ["transition"]):
            mild_hits.append(f"market_state:{market_state}")
        if str(regime or "") != "bear" and bool(getattr(cfg, "V80_SHORT_REQUIRE_BEAR_REGIME", True)):
            severe_hits.append(f"regime:{regime}")
        min_btc_score = float(cfg.get_symbol_param_float(symbol, "V80_SHORT_MIN_BTC_SCORE", float(getattr(cfg, "V80_SHORT_MIN_BTC_SCORE", 1.02))))
        mild_btc_score = float(cfg.get_symbol_param_float(symbol, "V80_SHORT_MILD_MIN_BTC_SCORE", float(getattr(cfg, "V80_SHORT_MILD_MIN_BTC_SCORE", 1.08))))
        if btc_score < min_btc_score:
            severe_hits.append(f"btc_score:{btc_score:.3f}")
        elif btc_score < mild_btc_score:
            mild_hits.append(f"btc_score:{btc_score:.3f}")
        max_rs_ratio = float(cfg.get_symbol_param_float(symbol, "V80_SHORT_MAX_RS_RATIO", float(getattr(cfg, "V80_SHORT_MAX_RS_RATIO", 0.98))))
        if rs_ratio > max_rs_ratio:
            mild_hits.append(f"rs_ratio:{rs_ratio:.3f}")
        if ema20_crosses >= int(getattr(cfg, "V80_SHORT_SEVERE_MIN_EMA20_CROSSES", 3)):
            severe_hits.append(f"ema20_crosses:{ema20_crosses}")
        elif ema20_crosses >= int(getattr(cfg, "V80_SHORT_MILD_MIN_EMA20_CROSSES", 2)):
            mild_hits.append(f"ema20_crosses:{ema20_crosses}")
        if mean_wickiness >= float(getattr(cfg, "V80_SHORT_SEVERE_MIN_WICKINESS", 0.58)):
            severe_hits.append(f"wickiness:{mean_wickiness:.3f}")
        elif mean_wickiness >= float(getattr(cfg, "V80_SHORT_MILD_MIN_WICKINESS", 0.50)):
            mild_hits.append(f"wickiness:{mean_wickiness:.3f}")
        if mean_body_ratio <= float(getattr(cfg, "V80_SHORT_SEVERE_MAX_BODY_RATIO", 0.30)):
            severe_hits.append(f"body_ratio:{mean_body_ratio:.3f}")
        elif mean_body_ratio <= float(getattr(cfg, "V80_SHORT_MILD_MAX_BODY_RATIO", 0.38)):
            mild_hits.append(f"body_ratio:{mean_body_ratio:.3f}")

        mild_mult = float(cfg.get_symbol_param_float(symbol, "V80_SHORT_RISK_MILD_MULT", float(getattr(cfg, "V80_SHORT_RISK_MILD_MULT", 0.92))))
        severe_mult = float(cfg.get_symbol_param_float(symbol, "V80_SHORT_RISK_SEVERE_MULT", float(getattr(cfg, "V80_SHORT_RISK_SEVERE_MULT", 0.82))))
        strong_mild_mult = float(cfg.get_symbol_param_float(symbol, "V80_SHORT_STRONG_SETUP_MILD_MULT", float(getattr(cfg, "V80_SHORT_STRONG_SETUP_MILD_MULT", 0.96))))
        strong_severe_mult = float(cfg.get_symbol_param_float(symbol, "V80_SHORT_STRONG_SETUP_SEVERE_MULT", float(getattr(cfg, "V80_SHORT_STRONG_SETUP_SEVERE_MULT", 0.90))))

        if severe_hits:
            mult = strong_severe_mult if bool(strong_setup) else severe_mult
            risk_mult *= mult
            flags.update({"v80_short_control_applied": True, "v80_short_control_level": "severe_strong_setup" if bool(strong_setup) else "severe", "v80_short_control_mult": mult, "v80_short_control_reason": severe_hits})
        elif mild_hits:
            mult = strong_mild_mult if bool(strong_setup) else mild_mult
            risk_mult *= mult
            flags.update({"v80_short_control_applied": True, "v80_short_control_level": "mild_strong_setup" if bool(strong_setup) else "mild", "v80_short_control_mult": mult, "v80_short_control_reason": mild_hits})
        return risk_mult, flags

    def _apply_v83_short_suppression(self, symbol: str, side: str, trade_type: str, market_state: str = "", regime: str = "", btc_meta: dict | None = None, rs_meta: dict | None = None, trend_quality_meta: dict | None = None, strong_setup: bool = False, regime_gate_meta: dict | None = None) -> tuple[bool, dict]:
        flags = {"v83_short_suppressed": False}
        if not bool(getattr(cfg, "V83_SHORT_SUPPRESSION_ENABLED", True)):
            return True, flags
        if str(side or "").lower() != "short":
            return True, flags
        allowed_symbols = set(getattr(cfg, "V83_SHORT_SUPPRESSION_SYMBOLS", ["BTCUSDT", "ETHUSDT"]) or ["BTCUSDT", "ETHUSDT"])
        if symbol not in allowed_symbols:
            return True, flags
        trade_type = str(trade_type or "").lower()
        allowed_types = {str(v).lower() for v in (getattr(cfg, "V83_SHORT_SUPPRESSION_ALLOWED_TYPES", ["impulse", "continuation", "cont_compression", "pullback"]) or ["impulse", "continuation", "cont_compression", "pullback"])}
        if trade_type not in allowed_types:
            return True, flags

        btc_meta = btc_meta or {}
        rs_meta = rs_meta or {}
        trend_quality_meta = trend_quality_meta or {}
        regime_gate_meta = regime_gate_meta or {}
        reasons = []

        bad_states = set(getattr(cfg, "V83_SHORT_BAD_MARKET_STATES", ["chop", "flat", "range", "transition"]) or ["chop", "flat", "range", "transition"])
        if str(market_state or "") in bad_states:
            reasons.append(f"market_state:{market_state}")
        if bool(getattr(cfg, "V83_SHORT_REQUIRE_BEAR_REGIME", True)) and str(regime or "") != "bear":
            reasons.append(f"regime:{regime}")

        gate_reason = str(regime_gate_meta.get("reason", "") or "")
        bad_gate_fragments = {str(v).lower() for v in (getattr(cfg, "V831_SHORT_BAD_GATE_FRAGMENTS", ["transition", "regime_mismatch", "non_directional", "blocked"]) or ["transition", "regime_mismatch", "non_directional", "blocked"])}
        if gate_reason and any(frag in gate_reason.lower() for frag in bad_gate_fragments):
            reasons.append(f"gate:{gate_reason}")

        btc_score = float(btc_meta.get("score", 0.0) or 0.0)
        min_btc_score = float(cfg.get_symbol_param_float(symbol, "V83_SHORT_MIN_BTC_SCORE", float(getattr(cfg, "V83_SHORT_MIN_BTC_SCORE", 1.12))))
        if btc_score < min_btc_score:
            reasons.append(f"btc_score:{btc_score:.3f}")

        rs_ratio = float(rs_meta.get("ratio", 1.0) or 1.0)
        max_rs_ratio = float(cfg.get_symbol_param_float(symbol, "V83_SHORT_MAX_RS_RATIO", float(getattr(cfg, "V83_SHORT_MAX_RS_RATIO", 0.975))))
        if rs_ratio > max_rs_ratio:
            reasons.append(f"rs_ratio:{rs_ratio:.3f}")

        ema20_crosses = int(trend_quality_meta.get("ema20_crosses", 0) or 0)
        if ema20_crosses >= int(getattr(cfg, "V83_SHORT_MAX_EMA20_CROSSES", 2)):
            reasons.append(f"ema20_crosses:{ema20_crosses}")
        mean_wickiness = float(trend_quality_meta.get("mean_wickiness", 0.0) or 0.0)
        if mean_wickiness >= float(getattr(cfg, "V83_SHORT_MAX_WICKINESS", 0.52)):
            reasons.append(f"wickiness:{mean_wickiness:.3f}")
        mean_body_ratio = float(trend_quality_meta.get("mean_body_ratio", 1.0) or 1.0)
        if mean_body_ratio <= float(getattr(cfg, "V83_SHORT_MIN_BODY_RATIO", 0.34)):
            reasons.append(f"body_ratio:{mean_body_ratio:.3f}")

        require_strong_types = {str(v).lower() for v in (getattr(cfg, "V83_SHORT_REQUIRE_STRONG_SETUP_TYPES", ["impulse", "continuation", "cont_compression", "pullback"]) or ["impulse", "continuation", "cont_compression", "pullback"])}
        if trade_type in require_strong_types and bool(getattr(cfg, "V83_SHORT_REQUIRE_STRONG_SETUP", True)) and not bool(strong_setup):
            reasons.append("strong_setup_required")

        min_reason_count = int(getattr(cfg, "V831_SHORT_MIN_REASON_COUNT", 1))
        if len(reasons) >= min_reason_count:
            flags.update({"v83_short_suppressed": True, "v83_short_suppression_reason": reasons})
            return False, flags
        return True, flags

    def _apply_v81_aggressive_short_risk(self, symbol: str, side: str, trade_type: str, risk_multiplier: float, market_state: str = "", regime: str = "", volume_meta: dict | None = None, strong_setup: bool = False, regime_gate_meta: dict | None = None) -> tuple[float, dict]:
        flags = {"v81_short_adjustment_applied": False}
        risk_mult = float(risk_multiplier)
        if not bool(getattr(cfg, "V81_SHORT_RISK_ENABLED", True)):
            return risk_mult, flags
        if str(side or "").lower() != "short":
            return risk_mult, flags
        allowed_symbols = set(getattr(cfg, "V81_SHORT_RISK_SYMBOLS", ["BTCUSDT", "ETHUSDT"]) or ["BTCUSDT", "ETHUSDT"])
        if symbol not in allowed_symbols:
            return risk_mult, flags
        allowed_types = {str(v).lower() for v in (getattr(cfg, "V81_SHORT_RISK_ALLOWED_TYPES", ["impulse", "continuation", "cont_compression", "pullback"]) or ["impulse", "continuation", "cont_compression", "pullback"])}
        trade_type = str(trade_type or "").lower()
        if trade_type not in allowed_types:
            return risk_mult, flags

        volume_meta = volume_meta or {}
        impulse_score = float(volume_meta.get("impulse_score", 1.0) or 1.0)
        reasons = []
        total_mult = float(cfg.get_symbol_param_float(symbol, "V81_SHORT_BASE_MULT", float(getattr(cfg, "V81_SHORT_BASE_MULT", 0.88))))
        reasons.append(f"base:{total_mult:.3f}")

        bad_states = set(getattr(cfg, "V81_SHORT_BAD_MARKET_STATES", ["chop", "flat", "range"]) or ["chop", "flat", "range"])
        if str(market_state or "") in bad_states:
            mult = float(cfg.get_symbol_param_float(symbol, "V81_SHORT_BAD_MARKET_MULT", float(getattr(cfg, "V81_SHORT_BAD_MARKET_MULT", 0.74))))
            total_mult *= mult
            reasons.append(f"bad_market:{market_state}:{mult:.3f}")
        elif bool(getattr(cfg, "V81_SHORT_REQUIRE_BEAR_REGIME", True)) and str(regime or "") != "bear":
            mult = float(cfg.get_symbol_param_float(symbol, "V81_SHORT_BAD_MARKET_MULT", float(getattr(cfg, "V81_SHORT_BAD_MARKET_MULT", 0.74))))
            total_mult *= mult
            reasons.append(f"non_bear_regime:{regime}:{mult:.3f}")

        if not bool(strong_setup):
            mult = float(cfg.get_symbol_param_float(symbol, "V81_SHORT_WEAK_SETUP_MULT", float(getattr(cfg, "V81_SHORT_WEAK_SETUP_MULT", 0.82))))
            total_mult *= mult
            reasons.append(f"weak_setup:{mult:.3f}")

        weak_impulse_threshold = float(cfg.get_symbol_param_float(symbol, "V81_SHORT_WEAK_IMPULSE_MAX", float(getattr(cfg, "V81_SHORT_WEAK_IMPULSE_MAX", 0.82))))
        if trade_type == "impulse" and impulse_score <= weak_impulse_threshold:
            mult = float(cfg.get_symbol_param_float(symbol, "V81_SHORT_WEAK_IMPULSE_MULT", float(getattr(cfg, "V81_SHORT_WEAK_IMPULSE_MULT", 0.88))))
            total_mult *= mult
            reasons.append(f"weak_impulse:{impulse_score:.3f}:{mult:.3f}")

        if total_mult >= 0.999:
            return risk_mult, flags
        risk_mult *= total_mult
        flags.update({
            "v81_short_adjustment_applied": True,
            "v81_short_adjustment_mult": total_mult,
            "v81_short_adjustment_reason": reasons,
        })
        return risk_mult, flags

    def _mr_risk_multiplier(self, symbol: str) -> float:
        return mr_risk_multiplier(cfg=cfg, symbol=symbol)


    def _extract_bar_timestamp(self, df: pd.DataFrame):
        return extract_bar_timestamp(df)

    def _is_allowed_trading_time(self, df: pd.DataFrame) -> tuple[bool, dict]:
        return is_allowed_trading_time(cfg=cfg, df=df, timestamp_extractor=self._extract_bar_timestamp)


    def _calc_breakout_candle_quality(self, candle: pd.Series, atr_ltf: float, side: str) -> tuple[bool, dict]:
        """Проверка качества пробойной свечи.

        Идея:
        - тело должно быть достаточно большим относительно ATR;
        - закрытие должно быть возле экстремума свечи;
        - не входим по свече, где сигнал сформирован одним длинным фитилём.
        """
        try:
            open_ = float(candle.get("open"))
            high = float(candle.get("high"))
            low = float(candle.get("low"))
            close = float(candle.get("close"))
        except (TypeError, ValueError):
            return False, {"reason": "bad_ohlc"}

        candle_range = max(high - low, 0.0)
        body = abs(close - open_)
        if candle_range <= 0.0 or atr_ltf <= 0.0:
            return False, {"reason": "bad_range"}

        upper_wick = max(0.0, high - max(open_, close))
        lower_wick = max(0.0, min(open_, close) - low)

        min_body_atr = float(getattr(cfg, "BREAKOUT_MIN_BODY_ATR", 0.35))
        max_close_from_extreme = float(getattr(cfg, "BREAKOUT_MAX_CLOSE_FROM_EXTREME_PCT", 0.25))
        max_breakout_wick_body_ratio = float(getattr(cfg, "BREAKOUT_MAX_WICK_BODY_RATIO", 0.8))
        max_breakout_wick_range_ratio = float(getattr(cfg, "BREAKOUT_MAX_WICK_RANGE_RATIO", 0.35))

        if body < atr_ltf * min_body_atr:
            return False, {
                "reason": "small_body_vs_atr",
                "body": body,
                "atr": atr_ltf,
                "need": atr_ltf * min_body_atr,
            }

        if side == "long":
            if close <= open_:
                return False, {"reason": "no_bull_body"}
            distance_to_extreme = high - close
            breakout_wick = upper_wick
        else:
            if close >= open_:
                return False, {"reason": "no_bear_body"}
            distance_to_extreme = close - low
            breakout_wick = lower_wick

        if (distance_to_extreme / candle_range) > max_close_from_extreme:
            return False, {
                "reason": "close_not_near_extreme",
                "distance": distance_to_extreme,
                "range": candle_range,
            }

        if body <= 0.0:
            return False, {"reason": "zero_body"}

        if (breakout_wick / body) > max_breakout_wick_body_ratio:
            return False, {
                "reason": "wick_too_big_vs_body",
                "wick": breakout_wick,
                "body": body,
            }

        if (breakout_wick / candle_range) > max_breakout_wick_range_ratio:
            return False, {
                "reason": "wick_too_big_vs_range",
                "wick": breakout_wick,
                "range": candle_range,
            }

        return True, {
            "body": body,
            "range": candle_range,
            "upper_wick": upper_wick,
            "lower_wick": lower_wick,
        }



    def _calc_breakout_volume_momentum(self, recent: pd.DataFrame, candle: pd.Series, atr_ltf: float, side: str) -> tuple[bool, dict]:
        """Более устойчивый фильтр объёма/импульса для breakout.

        Вместо грубого сравнения с простым средним используем комбинацию:
        - volume EMA по окну recent;
        - медиану объёма как более устойчивую базу;
        - score, который учитывает и объём, и качество/импульс свечи.
        """
        try:
            vol_series = recent["volume"].astype(float).replace([np.inf, -np.inf], np.nan).dropna()
            if len(vol_series) < 5:
                return False, {"reason": "not_enough_volume_history", "count": int(len(vol_series))}

            volume = float(candle.get("volume"))
            open_ = float(candle.get("open"))
            high = float(candle.get("high"))
            low = float(candle.get("low"))
            close = float(candle.get("close"))
        except (TypeError, ValueError, KeyError):
            return False, {"reason": "bad_volume_or_ohlc"}

        if atr_ltf <= 0.0:
            return False, {"reason": "bad_atr", "atr_ltf": atr_ltf}

        vol_ema_span = int(getattr(cfg, "BREAKOUT_VOLUME_EMA_SPAN", 20))
        symbol = self._extract_symbol(recent) or self._extract_symbol(pd.DataFrame([candle]))
        min_vs_ema = cfg.get_symbol_param_float(symbol, "BREAKOUT_VOLUME_MIN_RATIO_TO_EMA", float(getattr(cfg, "BREAKOUT_VOLUME_MIN_RATIO_TO_EMA", 1.10)))
        min_vs_median = cfg.get_symbol_param_float(symbol, "BREAKOUT_VOLUME_MIN_RATIO_TO_MEDIAN", float(getattr(cfg, "BREAKOUT_VOLUME_MIN_RATIO_TO_MEDIAN", 1.20)))
        min_impulse_score = float(getattr(cfg, "BREAKOUT_MIN_VOLUME_IMPULSE_SCORE", 0.55))
        strong_impulse_score = float(getattr(cfg, "BREAKOUT_STRONG_VOLUME_IMPULSE_SCORE", 0.95))

        vol_ema = float(vol_series.ewm(span=max(2, vol_ema_span), adjust=False).mean().iloc[-1])
        vol_median = float(vol_series.median())
        vol_p75 = float(vol_series.quantile(0.75))

        if vol_ema <= 0.0 or vol_median <= 0.0:
            return False, {"reason": "bad_volume_baseline", "vol_ema": vol_ema, "vol_median": vol_median}

        range_ = max(high - low, 0.0)
        body = abs(close - open_)
        body_atr = body / atr_ltf if atr_ltf > 0 else 0.0
        close_pos = 0.5
        if range_ > 0:
            close_pos = (close - low) / range_

        if side == "long":
            close_extreme_score = close_pos
        else:
            close_extreme_score = 1.0 - close_pos

        vol_ratio_ema = volume / vol_ema
        vol_ratio_median = volume / vol_median
        robust_vol_ratio = min(vol_ratio_ema, vol_ratio_median)
        impulse_score = robust_vol_ratio * body_atr * close_extreme_score

        if vol_ratio_ema < min_vs_ema and vol_ratio_median < min_vs_median:
            return False, {
                "reason": "weak_volume",
                "volume": volume,
                "vol_ema": vol_ema,
                "vol_median": vol_median,
                "vol_p75": vol_p75,
                "vol_ratio_ema": vol_ratio_ema,
                "vol_ratio_median": vol_ratio_median,
                "impulse_score": impulse_score,
            }

        if impulse_score < min_impulse_score:
            return False, {
                "reason": "weak_volume_impulse",
                "volume": volume,
                "vol_ema": vol_ema,
                "vol_median": vol_median,
                "vol_ratio_ema": vol_ratio_ema,
                "vol_ratio_median": vol_ratio_median,
                "body_atr": body_atr,
                "close_extreme_score": close_extreme_score,
                "impulse_score": impulse_score,
            }

        return True, {
            "volume": volume,
            "vol_ema": vol_ema,
            "vol_median": vol_median,
            "vol_p75": vol_p75,
            "vol_ratio_ema": vol_ratio_ema,
            "vol_ratio_median": vol_ratio_median,
            "body_atr": body_atr,
            "close_extreme_score": close_extreme_score,
            "impulse_score": impulse_score,
            "is_strong_impulse": impulse_score >= strong_impulse_score,
        }

    def _extract_symbol(self, df: pd.DataFrame) -> str:
        return extract_symbol(df)

    def _resolve_regime_from_values(self, ema20: float, ema50: float, ema200: float) -> str:
        return resolve_regime_from_values(ema20=ema20, ema50=ema50, ema200=ema200)

    def _classify_market_state(self, symbol: str, recent: pd.DataFrame, close: float, atr_ltf: float, atr_h: float, adx_h: float, drift: float, regime: str) -> tuple[str, dict]:
        return classify_market_state(cfg=cfg, symbol=symbol, recent=recent, close=close, atr_ltf=atr_ltf, atr_h=atr_h, adx_h=adx_h, drift=drift, regime=regime)

    def _check_relative_strength_filter(self, df: pd.DataFrame, symbol: str, side: str) -> tuple[bool, dict]:
        btc_symbol = str(getattr(cfg, "BTC_REGIME_FILTER_SYMBOL", "BTCUSDT"))
        if not symbol or symbol == btc_symbol:
            return True, {"skipped": True, "score": 1.0}
        if "BTC_close" not in df.columns:
            return True, {"skipped": True, "reason": "missing_btc_close"}
        try:
            lookback = int(cfg.get_symbol_param_int(symbol, "REL_STRENGTH_LOOKBACK", int(getattr(cfg, "REL_STRENGTH_LOOKBACK", 48))))
            ema_span = int(cfg.get_symbol_param_int(symbol, "REL_STRENGTH_EMA", int(getattr(cfg, "REL_STRENGTH_EMA", 34))))
            min_ratio = float(cfg.get_symbol_param_float(symbol, "REL_STRENGTH_MIN_RATIO", float(getattr(cfg, "REL_STRENGTH_MIN_RATIO", 1.002))))
            min_slope = float(cfg.get_symbol_param_float(symbol, "REL_STRENGTH_MIN_SLOPE", float(getattr(cfg, "REL_STRENGTH_MIN_SLOPE", 0.0))))
            short_max_ratio = float(cfg.get_symbol_param_float(symbol, "REL_STRENGTH_SHORT_MAX_RATIO", float(getattr(cfg, "REL_STRENGTH_SHORT_MAX_RATIO", 0.998))))
            short_min_slope = float(cfg.get_symbol_param_float(symbol, "REL_STRENGTH_SHORT_MIN_SLOPE", float(getattr(cfg, "REL_STRENGTH_SHORT_MIN_SLOPE", 0.0))))
            recent = df.tail(max(lookback + 5, ema_span + 5)).copy()
            alt_close = recent["close"].astype(float)
            btc_close = recent["BTC_close"].astype(float)
            rs = (alt_close / btc_close.replace(0.0, np.nan)).replace([np.inf, -np.inf], np.nan).dropna()
            if len(rs) < max(lookback // 2, 12):
                return True, {"skipped": True, "reason": "short_rs_history"}
            rs_now = float(rs.iloc[-1])
            rs_ema = float(rs.ewm(span=max(5, ema_span), adjust=False).mean().iloc[-1])
            rs_prev = float(rs.iloc[-min(len(rs), lookback)])
            slope = (rs_now - rs_prev) / abs(rs_prev) if rs_prev != 0 else 0.0
        except Exception as exc:
            return True, {"skipped": True, "reason": "rs_exception", "error": str(exc)}

        ratio = rs_now / rs_ema if rs_ema != 0 else 1.0
        if side == "long":
            ok = ratio >= min_ratio and slope >= min_slope
        else:
            ok = ratio <= short_max_ratio and slope <= short_min_slope
        return ok, {
            "rs_now": rs_now,
            "rs_ema": rs_ema,
            "ratio": ratio,
            "slope": slope,
            "side": side,
        }



    def _calc_alt_quality_score(self, symbol: str, recent: pd.DataFrame, atr_ltf: float, side: str) -> tuple[bool, dict]:
        btc_symbol = str(getattr(cfg, "BTC_REGIME_FILTER_SYMBOL", "BTCUSDT"))
        if not symbol or symbol == btc_symbol:
            return True, {"score": 1.0, "skipped": True}

        wickiness = self._calc_recent_wickiness(recent)
        false_breakout_ratio = self._calc_false_breakout_ratio(recent)
        try:
            closes = recent["close"].astype(float)
            directional_eff = abs(float(closes.iloc[-1]) - float(closes.iloc[0])) / max(float((closes.diff().abs()).sum()), 1e-9)
        except Exception:
            directional_eff = 0.0
        try:
            ranges = (recent["high"].astype(float) - recent["low"].astype(float)).replace(0.0, np.nan)
            body_share = ((recent["close"].astype(float) - recent["open"].astype(float)).abs() / ranges).replace([np.inf, -np.inf], np.nan)
            body_share = float(body_share.tail(min(20, len(body_share))).mean())
        except Exception:
            body_share = 0.0
        price_ref = float(recent["close"].astype(float).iloc[-1]) if len(recent) > 0 else 0.0
        atr_pct = (atr_ltf / price_ref) if price_ref > 0 else 0.0
        atr_low = float(getattr(cfg, "ALT_QUALITY_ATR_LOW_PCT", 0.004))
        atr_high = float(getattr(cfg, "ALT_QUALITY_ATR_HIGH_PCT", 0.03))
        if atr_pct <= atr_low:
            atr_score = max(0.0, atr_pct / max(atr_low, 1e-9))
        elif atr_pct >= atr_high:
            atr_score = max(0.0, 1.0 - min(1.0, (atr_pct - atr_high) / max(atr_high, 1e-9)))
        else:
            atr_score = 1.0
        score = (
            0.34 * max(0.0, 1.0 - wickiness) +
            0.30 * max(0.0, 1.0 - false_breakout_ratio) +
            0.18 * max(0.0, min(1.0, directional_eff)) +
            0.10 * max(0.0, min(1.0, body_share * 1.8)) +
            0.08 * atr_score
        )
        threshold = cfg.get_symbol_param_float(symbol, "ALT_QUALITY_MIN_SCORE", float(getattr(cfg, "ALT_QUALITY_MIN_SCORE", 0.48)))
        return score >= threshold, {
            "score": score,
            "threshold": threshold,
            "wickiness": wickiness,
            "false_breakout_ratio": false_breakout_ratio,
            "directional_eff": directional_eff,
            "body_share": body_share,
            "atr_pct": atr_pct,
            "side": side,
        }



    def _check_btc_regime_filter(self, df: pd.DataFrame, symbol: str, side: str) -> tuple[bool, dict]:
        enabled = bool(getattr(cfg, "BTC_REGIME_FILTER_ENABLED", True))
        if not enabled:
            return True, {"enabled": False}

        btc_symbol = str(getattr(cfg, "BTC_REGIME_FILTER_SYMBOL", "BTCUSDT"))
        alt_symbols = set(getattr(cfg, "BTC_REGIME_ALT_SYMBOLS", ["ETHUSDT"]) or [])
        if not symbol or symbol == btc_symbol or symbol not in alt_symbols:
            return True, {"enabled": True, "skipped": True}

        needed = ["BTC_HTF_EMA20", "BTC_HTF_EMA50", "BTC_HTF_EMA200", "BTC_HTF_ADX"]
        if not all(c in df.columns for c in needed):
            return False, {"reason": "missing_btc_htf_cols"}
        try:
            ema20 = float(df["BTC_HTF_EMA20"].iloc[-1])
            ema50 = float(df["BTC_HTF_EMA50"].iloc[-1])
            ema200 = float(df["BTC_HTF_EMA200"].iloc[-1])
            adx = float(df["BTC_HTF_ADX"].iloc[-1])
            btc_close = float(df["close"].iloc[-1]) if symbol == btc_symbol else float(df.get("BTC_close", pd.Series([np.nan])).iloc[-1])
        except Exception:
            btc_close = np.nan
            try:
                ema20 = float(df["BTC_HTF_EMA20"].iloc[-1])
                ema50 = float(df["BTC_HTF_EMA50"].iloc[-1])
                ema200 = float(df["BTC_HTF_EMA200"].iloc[-1])
                adx = float(df["BTC_HTF_ADX"].iloc[-1])
            except Exception:
                return False, {"reason": "bad_btc_htf_values"}

        if any(np.isnan(x) for x in [ema20, ema50, ema200, adx]):
            return False, {"reason": "nan_btc_htf_values"}

        btc_regime = self._resolve_regime_from_values(ema20, ema50, ema200)
        soft_adx_min = float(getattr(cfg, "BTC_REGIME_SOFT_ADX_MIN", 14.0))
        hard_adx_min = float(getattr(cfg, "BTC_REGIME_HARD_ADX_MIN", 20.0))
        allow_neutral = bool(getattr(cfg, "BTC_REGIME_ALLOW_NEUTRAL_IF_ADX_OK", True))
        score = 0.0
        expected = "bull" if side == "long" else "bear"

        if btc_regime == expected:
            score += 1.0
        elif btc_regime == "none" and allow_neutral:
            score += 0.45

        if side == "long":
            if ema20 > ema50:
                score += 0.35
            if ema50 > ema200:
                score += 0.35
        else:
            if ema20 < ema50:
                score += 0.35
            if ema50 < ema200:
                score += 0.35

        if adx >= hard_adx_min:
            score += 0.45
        elif adx >= soft_adx_min:
            score += 0.20

        threshold = float(getattr(cfg, "BTC_REGIME_MIN_SCORE_LONG", getattr(cfg, "BTC_REGIME_MIN_SCORE", 0.80))) if side == "long" else float(getattr(cfg, "BTC_REGIME_MIN_SCORE_SHORT", max(float(getattr(cfg, "BTC_REGIME_MIN_SCORE", 0.80)), 1.05)))
        ok = score >= threshold
        return ok, {
            "btc_regime": btc_regime,
            "expected": expected,
            "btc_ema20": ema20,
            "btc_ema50": ema50,
            "btc_ema200": ema200,
            "btc_adx": adx,
            "score": score,
            "threshold": threshold,
            "btc_close": None if np.isnan(btc_close) else btc_close,
        }



    def _check_v51_free_liquidity_filter(self, *, symbol: str, side: str, df: pd.DataFrame, pullback_meta: dict | None = None) -> tuple[bool, dict]:
        """V51: backtestable free liquidity/proxy gate for BTC pullback.

        Uses only features that can exist historically without paid data:
        candle/volume proxies + funding. If feature columns are missing, it does
        not block live trading; backtest loader attaches them when data exists.
        """
        if not bool(getattr(cfg, "V51_FREE_LIQUIDITY_FILTER_ENABLED", False)):
            return True, {"v51_enabled": False}
        allowed_symbols = {str(x).upper() for x in (getattr(cfg, "V51_FREE_LIQUIDITY_FILTER_SYMBOLS", ["BTCUSDT"]) or ["BTCUSDT"])}
        allowed_types = {str(x).lower() for x in (getattr(cfg, "V51_FREE_LIQUIDITY_FILTER_TRADE_TYPES", ["pullback"]) or ["pullback"])}
        if str(symbol).upper() not in allowed_symbols or "pullback" not in allowed_types:
            return True, {"v51_skip": "symbol_or_type"}
        if str(side).lower() != "long":
            return True, {"v51_skip": "only_long_v51"}
        if df is None or len(df) < 80:
            return True, {"v51_skip": "not_enough_history"}
        last = df.iloc[-1]
        def f(name: str, default: float = float("nan")) -> float:
            try:
                return float(last.get(name, default))
            except Exception:
                return default

        # If the feature builder was not attached, avoid breaking live/backtests.
        feature_cols = {"free_trend_up", "free_ema20_slope_12", "free_volume_ratio48", "free_body_atr"}
        if not feature_cols.intersection(set(df.columns)):
            return True, {"v51_enabled": True, "v51_missing_features": True}

        funding = f("liq_funding_rate", 0.0)
        trend_up = int(f("free_trend_up", 0.0) or 0)
        sweep_reclaim = int(f("free_sweep_low_reclaim", 0.0) or 0)
        ema_slope = f("free_ema20_slope_12", 0.0)
        vol_ratio = f("free_volume_ratio48", 1.0)
        body_atr = f("free_body_atr", 0.0)
        lower_wick = f("free_lower_wick_range", 0.0)
        atr_pct = f("free_atr_pct", 0.0)

        min_slope = float(getattr(cfg, "V51_MIN_EMA20_SLOPE_12", -0.0015))
        min_vol = float(getattr(cfg, "V51_MIN_VOLUME_RATIO48", 0.35))
        max_vol = float(getattr(cfg, "V51_MAX_VOLUME_RATIO48", 4.50))
        max_body = float(getattr(cfg, "V51_MAX_BODY_ATR", 2.80))
        max_funding = float(getattr(cfg, "V51_BLOCK_LONG_IF_FUNDING_ABOVE", 0.00035))
        min_score = float(getattr(cfg, "V51_MIN_PROXY_SCORE", 0.45))

        reasons = []
        score = 0.0
        if trend_up >= int(getattr(cfg, "V51_MIN_FREE_TREND_UP", 1)):
            score += 0.25
        else:
            reasons.append("no_free_trend_up")
        if ema_slope >= min_slope:
            score += 0.20
        else:
            reasons.append("weak_ema20_slope")
        if min_vol <= vol_ratio <= max_vol:
            score += 0.15
        else:
            reasons.append("bad_volume_ratio")
        if body_atr <= max_body:
            score += 0.15
        else:
            reasons.append("body_too_large")
        if sweep_reclaim and bool(getattr(cfg, "V51_ALLOW_IF_SWEEP_LOW_RECLAIM", True)):
            score += 0.20
        elif lower_wick >= 0.22:
            score += 0.10
        else:
            reasons.append("no_reclaim_or_lower_wick")
        if funding <= float(getattr(cfg, "V51_ALLOW_LONG_IF_FUNDING_BELOW", 0.00010)):
            score += 0.10

        if funding > max_funding and not sweep_reclaim:
            return False, {"reason": "v51_hot_positive_funding_no_reclaim", "v51_score": score, "funding": funding, "trend_up": trend_up, "ema_slope": ema_slope, "vol_ratio": vol_ratio, "body_atr": body_atr, "atr_pct": atr_pct}
        if bool(getattr(cfg, "V51_REQUIRE_RECLAIM_OR_TREND", True)) and not (trend_up or sweep_reclaim):
            return False, {"reason": "v51_no_trend_or_reclaim", "v51_score": score, "reasons": reasons}
        if score < min_score:
            return False, {"reason": "v51_proxy_score_low", "v51_score": score, "v51_min_score": min_score, "reasons": reasons, "funding": funding, "trend_up": trend_up, "sweep_reclaim": sweep_reclaim, "ema_slope": ema_slope, "vol_ratio": vol_ratio, "body_atr": body_atr}
        return True, {"v51_enabled": True, "v51_score": score, "funding": funding, "trend_up": trend_up, "sweep_reclaim": sweep_reclaim, "ema_slope": ema_slope, "vol_ratio": vol_ratio, "body_atr": body_atr, "lower_wick": lower_wick, "atr_pct": atr_pct}

    def _check_v45_structural_rr(self, *, symbol: str, side: str, df: pd.DataFrame, close: float, atr_ltf: float, pullback_meta: dict | None = None) -> tuple[bool, dict]:
        """V45: accept BTC pullback only if trade geometry is good.

        This is not another trend/regime filter. It checks whether the entry is
        close enough to structural invalidation and whether the expected move
        offers enough reward/risk. The resulting structural stop is passed in
        signal meta and used by backtest/live sizing.
        """
        if not bool(getattr(cfg, "V45_STRUCTURAL_RR_ENABLED", False)):
            return True, {"v45_enabled": False}
        allowed_symbols = {str(x).upper() for x in (getattr(cfg, "V45_STRUCTURAL_RR_SYMBOLS", ["BTCUSDT"]) or ["BTCUSDT"])}
        allowed_types = {str(x).lower() for x in (getattr(cfg, "V45_STRUCTURAL_RR_TRADE_TYPES", ["pullback"]) or ["pullback"])}
        if str(symbol).upper() not in allowed_symbols or "pullback" not in allowed_types:
            return True, {"v45_skip": "symbol_or_type"}
        if atr_ltf <= 0 or len(df) < 20:
            return False, {"reason": "v45_no_atr_or_history"}
        lookback = max(3, int(getattr(cfg, "V45_STRUCT_LOOKBACK_BARS", 8)))
        buf_atr = float(getattr(cfg, "V45_STRUCT_STOP_BUFFER_ATR", 0.18))
        recent = df.tail(min(len(df), lookback + 1)).copy()
        try:
            if side == "long":
                swing = float(recent["low"].astype(float).iloc[:-1].min())
                struct_stop = swing - buf_atr * float(atr_ltf)
                stop_atr = (float(close) - struct_stop) / float(atr_ltf)
            else:
                swing = float(recent["high"].astype(float).iloc[:-1].max())
                struct_stop = swing + buf_atr * float(atr_ltf)
                stop_atr = (struct_stop - float(close)) / float(atr_ltf)
        except Exception:
            return False, {"reason": "v45_bad_struct_values"}
        min_stop = float(getattr(cfg, "V45_STRUCT_MIN_STOP_ATR", 0.65))
        max_stop = float(getattr(cfg, "V45_STRUCT_MAX_STOP_ATR", 2.20))
        if stop_atr <= 0:
            return False, {"reason": "v45_invalid_stop", "v45_stop_atr": stop_atr}
        if stop_atr < min_stop:
            # Too tight: likely noise/intrabar stop. Use min stop for RR math, but keep structural stop.
            rr_stop_atr = min_stop
        else:
            rr_stop_atr = stop_atr
        if stop_atr > max_stop:
            return False, {"reason": "v45_stop_too_wide", "v45_stop_atr": stop_atr, "v45_max_stop_atr": max_stop}

        pb = pullback_meta or {}
        pre_imp = float(pb.get("pre_impulse_atr", 0.0) or 0.0)
        target_floor = float(getattr(cfg, "V45_STRUCT_TARGET_ATR_FLOOR", 3.20))
        target_mult = float(getattr(cfg, "V45_STRUCT_TARGET_PRE_IMPULSE_MULT", 0.95))
        expected_target_atr = max(target_floor, pre_imp * target_mult)
        rr = expected_target_atr / max(rr_stop_atr, 1e-9)
        min_rr = float(getattr(cfg, "V45_STRUCT_MIN_RR", 2.20))
        if rr < min_rr:
            return False, {"reason": "v45_rr_too_low", "v45_rr": rr, "v45_min_rr": min_rr, "v45_stop_atr": stop_atr, "v45_target_atr": expected_target_atr}

        risk_mult = 1.0
        if bool(getattr(cfg, "V45_STRUCT_REDUCE_RISK_IF_WIDE_STOP", True)) and stop_atr >= float(getattr(cfg, "V45_STRUCT_WIDE_STOP_ATR", 1.65)):
            risk_mult = float(getattr(cfg, "V45_STRUCT_WIDE_STOP_RISK_MULT", 0.72))
        return True, {
            "v45_enabled": True,
            "v45_struct_stop_price": float(struct_stop),
            "v45_struct_stop_atr": float(stop_atr),
            "v45_expected_target_atr": float(expected_target_atr),
            "v45_rr": float(rr),
            "v45_risk_mult": float(risk_mult),
            "v45_swing": float(swing),
        }

    def _check_v43_btc_pullback_regime(self, *, symbol: str, side: str, df: pd.DataFrame, close: float, market_state: str, adx_h: float, atr_pct_h: float, drift: float, pullback_meta: dict | None = None, is_addon: bool = False) -> tuple[bool, dict]:
        """V43: allow BTC pullback only in healthy HTF trend regimes.

        This is intentionally a gate, not a new signal. It protects the v39/v42
        BTC pullback edge from 2025-like false-pullback regimes.
        """
        if not bool(getattr(cfg, "V43_REGIME_FILTER_ENABLED", False)):
            return True, {"enabled": False}

        allowed_symbols = {str(x).upper() for x in (getattr(cfg, "V43_REGIME_FILTER_SYMBOLS", ["BTCUSDT"]) or ["BTCUSDT"])}
        allowed_types = {str(x).lower() for x in (getattr(cfg, "V43_REGIME_FILTER_TRADE_TYPES", ["pullback"]) or ["pullback"])}
        if str(symbol).upper() not in allowed_symbols or "pullback" not in allowed_types:
            return True, {"enabled": True, "skipped": True, "symbol": symbol}

        try:
            lookback = 9
            if len(df) < lookback + 1:
                return True, {"enabled": True, "skipped": "not_enough_history"}
            htf = df.iloc[-(lookback + 1):]
            ema20_now = float(htf["HTF_EMA20"].iloc[-1])
            ema20_prev = float(htf["HTF_EMA20"].iloc[0])
            ema50_now = float(htf["HTF_EMA50"].iloc[-1])
            ema50_prev = float(htf["HTF_EMA50"].iloc[0])
            ema200_now = float(htf["HTF_EMA200"].iloc[-1]) if "HTF_EMA200" in htf.columns else float("nan")
        except Exception as exc:
            return False, {"reason": "v43_missing_htf_regime_cols", "error": str(exc)}

        if close <= 0:
            return False, {"reason": "v43_bad_close", "close": close}

        ema20_slope = (ema20_now - ema20_prev) / close
        ema50_slope = (ema50_now - ema50_prev) / close

        min_adx = float(getattr(cfg, "V43_MIN_HTF_ADX", 20.0))
        min_atr_pct = float(getattr(cfg, "V43_MIN_HTF_ATR_PCT", 0.0018))
        min_drift = float(getattr(cfg, "V43_MIN_DRIFT_PCT", 0.0035))
        min_ema20_slope = float(getattr(cfg, "V43_MIN_EMA20_SLOPE_PCT", 0.00055))
        min_ema50_slope = float(getattr(cfg, "V43_MIN_EMA50_SLOPE_PCT", 0.00018))

        if is_addon and bool(getattr(cfg, "V43_STRICT_ADDON_FILTER", True)):
            min_adx = max(min_adx, float(getattr(cfg, "V43_ADDON_MIN_HTF_ADX", 24.0)))
            min_drift = max(min_drift, float(getattr(cfg, "V43_ADDON_MIN_DRIFT_PCT", 0.0050)))
            min_ema20_slope = max(min_ema20_slope, float(getattr(cfg, "V43_ADDON_MIN_EMA20_SLOPE_PCT", 0.00075)))

        reasons: list[str] = []
        if float(adx_h or 0.0) < min_adx:
            reasons.append(f"adx_h={float(adx_h or 0.0):.2f}<{min_adx:.2f}")
        if float(atr_pct_h or 0.0) < min_atr_pct:
            reasons.append(f"atr_pct_h={float(atr_pct_h or 0.0):.5f}<{min_atr_pct:.5f}")
        if float(drift or 0.0) < min_drift:
            reasons.append(f"drift={float(drift or 0.0):.5f}<{min_drift:.5f}")

        if side == "long":
            if bool(getattr(cfg, "V43_REQUIRE_HTF_EMA_ALIGNMENT", True)) and not (ema20_now >= ema50_now and (pd.isna(ema200_now) or ema50_now >= ema200_now)):
                reasons.append("htf_ema_alignment_not_bullish")
            if bool(getattr(cfg, "V43_REQUIRE_CLOSE_ABOVE_HTF_EMA50_LONG", True)) and close < ema50_now:
                reasons.append("close_below_htf_ema50")
            if ema20_slope < min_ema20_slope:
                reasons.append(f"ema20_slope={ema20_slope:.5f}<{min_ema20_slope:.5f}")
            if ema50_slope < min_ema50_slope:
                reasons.append(f"ema50_slope={ema50_slope:.5f}<{min_ema50_slope:.5f}")
        else:
            if bool(getattr(cfg, "V43_REQUIRE_HTF_EMA_ALIGNMENT", True)) and not (ema20_now <= ema50_now and (pd.isna(ema200_now) or ema50_now <= ema200_now)):
                reasons.append("htf_ema_alignment_not_bearish")
            if ema20_slope > -min_ema20_slope:
                reasons.append(f"ema20_slope={ema20_slope:.5f}>-{min_ema20_slope:.5f}")
            if ema50_slope > -min_ema50_slope:
                reasons.append(f"ema50_slope={ema50_slope:.5f}>-{min_ema50_slope:.5f}")

        if market_state == "transition" and bool(getattr(cfg, "V43_BLOCK_TRANSITION_IF_WEAK", True)):
            t_adx = float(getattr(cfg, "V43_TRANSITION_MIN_ADX", 24.0))
            t_drift = float(getattr(cfg, "V43_TRANSITION_MIN_DRIFT_PCT", 0.0050))
            if float(adx_h or 0.0) < t_adx or float(drift or 0.0) < t_drift:
                reasons.append("weak_transition_regime")

        meta = {
            "enabled": True,
            "side": side,
            "market_state": market_state,
            "adx_h": float(adx_h or 0.0),
            "atr_pct_h": float(atr_pct_h or 0.0),
            "drift": float(drift or 0.0),
            "ema20_slope_pct": ema20_slope,
            "ema50_slope_pct": ema50_slope,
            "ema20": ema20_now,
            "ema50": ema50_now,
            "ema200": None if pd.isna(ema200_now) else ema200_now,
            "is_addon": bool(is_addon),
        }
        if reasons:
            return False, {**meta, "reason": "v43_bad_btc_pullback_regime", "reasons": reasons}
        return True, {**meta, "reason": "v43_regime_ok"}


    def _check_v52_candle_microstructure(self, *, symbol: str, side: str, df: pd.DataFrame, close: float, atr_ltf: float, pullback_meta: dict | None = None) -> tuple[bool, dict]:
        """V52: OHLCV-only candle structure gate for BTC pullback.

        Goal: do not add another trend filter. Accept pullbacks only when the
        recent candles show clean continuation behavior: controlled retrace,
        limited wick pressure, no repeated failed highs, and enough EMA hold.
        """
        if not bool(getattr(cfg, "V52_CANDLE_MICROSTRUCTURE_ENABLED", False)):
            return True, {"reason": "v52_disabled"}
        allowed_symbols = {str(x).upper() for x in (getattr(cfg, "V52_CANDLE_MICROSTRUCTURE_SYMBOLS", ["BTCUSDT"]) or ["BTCUSDT"])}
        allowed_types = {str(x).lower() for x in (getattr(cfg, "V52_CANDLE_MICROSTRUCTURE_TRADE_TYPES", ["pullback"]) or ["pullback"])}
        if str(symbol).upper() not in allowed_symbols or "pullback" not in allowed_types:
            return True, {"reason": "v52_not_applicable"}
        if side != "long":
            return True, {"reason": "v52_only_long_for_now"}
        if df is None or len(df) < 60:
            return False, {"reason": "v52_not_enough_data"}

        recent = df.tail(20).copy()
        last = recent.iloc[-1]
        prev = recent.iloc[:-1]
        eps = 1e-12
        atr = float(atr_ltf or last.get("atr", 0.0) or 0.0)
        if atr <= 0:
            atr = float((recent["high"] - recent["low"]).tail(14).mean() or 0.0)
        if atr <= 0:
            return False, {"reason": "v52_bad_atr"}

        o = float(last.get("open", close))
        h = float(last.get("high", close))
        l = float(last.get("low", close))
        c = float(last.get("close", close))
        rng = max(h - l, eps)
        body = c - o
        body_atr = body / atr
        abs_body_atr = abs(body) / atr
        upper_wick_atr = (h - max(o, c)) / atr
        lower_wick_atr = (min(o, c) - l) / atr
        close_pos = (c - l) / rng

        ema20 = float(last.get("ema20", c) or c)
        ema50 = float(last.get("ema50", ema20) or ema20)
        ema20_series = recent["ema20"] if "ema20" in recent.columns else recent["close"].ewm(span=20, adjust=False).mean()
        ema50_series = recent["ema50"] if "ema50" in recent.columns else recent["close"].ewm(span=50, adjust=False).mean()
        close_series = recent["close"].astype(float)
        high_series = recent["high"].astype(float)
        low_series = recent["low"].astype(float)
        open_series = recent["open"].astype(float)

        hold_ratio8 = float((close_series.tail(8) >= ema20_series.tail(8)).mean())
        ema_stack_ok = bool(c >= ema20 >= ema50)
        ema20_slope_8 = float((ema20_series.iloc[-1] - ema20_series.iloc[-8]) / max(abs(ema20_series.iloc[-8]), eps)) if len(ema20_series) >= 8 else 0.0

        # Failed breakout: candle pushes above previous local high but closes weak.
        failed_breakouts = 0
        for i in range(max(3, len(recent) - 12), len(recent)):
            window_hi = float(high_series.iloc[max(0, i-6):i].max()) if i > 0 else float(high_series.iloc[i])
            row_open = float(open_series.iloc[i]); row_close = float(close_series.iloc[i])
            row_high = float(high_series.iloc[i]); row_low = float(low_series.iloc[i])
            row_rng = max(row_high - row_low, eps)
            row_close_pos = (row_close - row_low) / row_rng
            if row_high > window_hi and row_close_pos < 0.45 and row_close <= row_open:
                failed_breakouts += 1

        # Distribution proxy: large bearish bodies on elevated volume.
        vol_ratio = 1.0
        if "volume" in recent.columns:
            vol_ma = float(recent["volume"].astype(float).tail(20).mean() or 0.0)
            if vol_ma > 0:
                vol_ratio = float(last.get("volume", 0.0) or 0.0) / vol_ma
        bearish_body_atr = max(0.0, -body_atr)
        heavy_distribution = bool(
            bearish_body_atr > float(getattr(cfg, "V52_MAX_ADVERSE_BODY_ATR", 1.15))
            and vol_ratio > float(getattr(cfg, "V52_VOLUME_SPIKE_MAX", 4.20)) * 0.55
        )

        # Compression before continuation: controlled local range is positive.
        compression_bonus = 0.0
        if bool(getattr(cfg, "V52_COMPRESSION_BONUS_ENABLED", True)) and len(prev) >= 8:
            range6 = float((prev["high"].tail(6).max() - prev["low"].tail(6).min()) / atr)
            range14 = float((prev["high"].tail(14).max() - prev["low"].tail(14).min()) / atr) if len(prev) >= 14 else range6
            if range6 <= max(1.0, range14 * 0.62):
                compression_bonus = 0.12

        v61_on = bool(getattr(cfg, "V61_FREQUENCY_EXPANSION_ENABLED", False)) and str(symbol).upper() in {str(x).upper() for x in (getattr(cfg, "V61_SYMBOLS", ["BTCUSDT"]) or ["BTCUSDT"])}
        min_hold_ratio = float(getattr(cfg, "V61_LONG_MIN_EMA20_HOLD_RATIO_8", 0.45)) if v61_on else float(getattr(cfg, "V52_MIN_EMA20_HOLD_RATIO_8", 0.50))
        min_close_pos = float(getattr(cfg, "V61_LONG_MIN_CLOSE_POS", 0.38)) if v61_on else float(getattr(cfg, "V52_MIN_CLOSE_POS", 0.42))
        max_upper_wick = float(getattr(cfg, "V61_LONG_MAX_UPPER_WICK_ATR", 1.28)) if v61_on else float(getattr(cfg, "V52_MAX_UPPER_WICK_ATR", 1.10))
        max_failed_breakouts = int(getattr(cfg, "V61_LONG_MAX_FAILED_BREAKOUTS_12", 4)) if v61_on else int(getattr(cfg, "V52_MAX_FAILED_BREAKOUTS_12", 3))
        min_body_confirm = float(getattr(cfg, "V61_LONG_MIN_BODY_ATR_CONFIRM", -0.38)) if v61_on else float(getattr(cfg, "V52_MIN_BODY_ATR_CONFIRM", -0.25))
        min_score = float(getattr(cfg, "V61_LONG_MIN_SCORE", 0.48)) if v61_on else float(getattr(cfg, "V52_MIN_SCORE", 0.52))

        score = 0.0
        score += 0.18 if ema_stack_ok else 0.0
        score += 0.18 if hold_ratio8 >= min_hold_ratio else 0.0
        score += 0.16 if close_pos >= min_close_pos else 0.0
        score += 0.14 if upper_wick_atr <= max_upper_wick else 0.0
        score += 0.14 if failed_breakouts <= max_failed_breakouts else 0.0
        score += 0.10 if body_atr >= min_body_confirm else 0.0
        score += 0.10 if ema20_slope_8 >= -0.0010 else 0.0
        score += compression_bonus
        score = min(1.0, score)

        reasons = []
        if close_pos < min_close_pos:
            reasons.append("weak_close_position")
        if upper_wick_atr > max_upper_wick:
            reasons.append("upper_wick_pressure")
        if failed_breakouts > max_failed_breakouts:
            reasons.append("repeated_failed_breakouts")
        if hold_ratio8 < min_hold_ratio:
            reasons.append("poor_ema20_hold")
        if body_atr < min_body_confirm:
            reasons.append("adverse_confirmation_body")
        if bool(getattr(cfg, "V52_REQUIRE_NOT_HEAVY_DISTRIBUTION", True)) and heavy_distribution:
            reasons.append("heavy_distribution")
        if score < min_score:
            reasons.append("low_microstructure_score")

        # V62: ranking layer. V61 widens discovery gates; V62 keeps only the
        # cleaner ranked subset. This is intentionally after the normal V52/V61
        # checks, so it never creates a new signal; it can only reject a weaker
        # approved candidate.
        v62_symbols = {str(x).upper() for x in (getattr(cfg, "V62_SYMBOLS", ["BTCUSDT"]) or ["BTCUSDT"])}
        v62_on = bool(getattr(cfg, "V62_SIGNAL_RANKING_ENABLED", False)) and str(symbol).upper() in v62_symbols
        v62_rank_score = 0.0
        if v62_on:
            close_rank = max(0.0, min(1.0, (close_pos - 0.35) / 0.45))
            hold_rank = max(0.0, min(1.0, hold_ratio8))
            wick_rank = max(0.0, min(1.0, 1.0 - (upper_wick_atr / max(float(getattr(cfg, "V62_LONG_MAX_UPPER_WICK_ATR", 1.15)), 1e-9))))
            fail_rank = max(0.0, min(1.0, 1.0 - (failed_breakouts / max(float(getattr(cfg, "V62_LONG_MAX_FAILED_BREAKOUTS_12", 3)), 1.0))))
            slope_rank = 1.0 if ema20_slope_8 >= -0.0005 else 0.35
            body_rank = 1.0 if body_atr >= float(getattr(cfg, "V62_LONG_MIN_BODY_ATR_CONFIRM", -0.30)) else 0.25
            v62_rank_score = min(1.0, 0.24*close_rank + 0.22*hold_rank + 0.18*wick_rank + 0.16*fail_rank + 0.12*slope_rank + 0.08*body_rank)

            if score < float(getattr(cfg, "V62_LONG_MIN_SCORE", 0.54)):
                reasons.append("v62_low_base_score")
            if v62_rank_score < float(getattr(cfg, "V62_LONG_MIN_RANK_SCORE", 0.60)):
                reasons.append("v62_low_rank_score")
            if close_pos < float(getattr(cfg, "V62_LONG_MIN_CLOSE_POS", 0.42)):
                reasons.append("v62_close_rank_weak")
            if upper_wick_atr > float(getattr(cfg, "V62_LONG_MAX_UPPER_WICK_ATR", 1.15)):
                reasons.append("v62_wick_rank_weak")
            if failed_breakouts > int(getattr(cfg, "V62_LONG_MAX_FAILED_BREAKOUTS_12", 3)):
                reasons.append("v62_failed_breakout_rank_weak")
            if hold_ratio8 < float(getattr(cfg, "V62_LONG_MIN_EMA20_HOLD_RATIO_8", 0.50)):
                reasons.append("v62_hold_rank_weak")

        meta = {
            "reason": "v52_microstructure_ok" if not reasons else "v52_bad_microstructure",
            "v52_score": round(score, 4),
            "v52_close_pos": round(close_pos, 4),
            "v52_upper_wick_atr": round(upper_wick_atr, 4),
            "v52_lower_wick_atr": round(lower_wick_atr, 4),
            "v52_body_atr": round(body_atr, 4),
            "v52_hold_ratio8": round(hold_ratio8, 4),
            "v52_failed_breakouts": int(failed_breakouts),
            "v52_ema_stack_ok": bool(ema_stack_ok),
            "v52_ema20_slope_8": round(ema20_slope_8, 6),
            "v52_vol_ratio": round(vol_ratio, 4),
            "v52_heavy_distribution": bool(heavy_distribution),
            "v52_reasons": reasons,
            "v62_rank_score": round(v62_rank_score, 4),
            "v62_enabled": bool(v62_on),
        }
        return len(reasons) == 0, meta




    def _check_v60_short_microstructure(self, *, symbol: str, side: str, df: pd.DataFrame, close: float, atr_ltf: float, pullback_meta: dict | None = None) -> tuple[bool, dict]:
        """V60: OHLCV-only bearish microstructure gate for BTC pullback shorts.

        This is intentionally isolated from legacy short systems. It mirrors the
        working V52 long idea, but checks bearish continuation quality: failed
        reclaim, upper-wick rejection, weak close position, EMA20 rejection and
        downside persistence.
        """
        if not bool(getattr(cfg, "V60_SHORT_ENGINE_ENABLED", False)):
            meta = {"reason": "v60_disabled"}
            self._v60_1_short_hit("v60_checked", meta)
            return True, meta
        allowed_symbols = {str(x).upper() for x in (getattr(cfg, "V60_SHORT_ENGINE_SYMBOLS", ["BTCUSDT"]) or ["BTCUSDT"])}
        if str(symbol).upper() not in allowed_symbols:
            meta = {"reason": "v60_not_applicable"}
            self._v60_1_short_hit("v60_checked", meta)
            return True, meta
        if str(side).lower() != "short":
            meta = {"reason": "v60_only_short"}
            self._v60_1_short_hit("v60_checked", meta)
            return True, meta
        if df is None or len(df) < 60:
            meta = {"reason": "v60_not_enough_data"}
            self._v60_1_short_hit("v60_checked", meta)
            return False, meta

        recent = df.tail(20).copy()
        last = recent.iloc[-1]
        prev = recent.iloc[:-1]
        eps = 1e-12
        atr = float(atr_ltf or last.get("atr", 0.0) or 0.0)
        if atr <= 0:
            atr = float((recent["high"] - recent["low"]).tail(14).mean() or 0.0)
        if atr <= 0:
            meta = {"reason": "v60_bad_atr"}
            self._v60_1_short_hit("v60_checked", meta)
            return False, meta

        o = float(last.get("open", close)); h = float(last.get("high", close)); l = float(last.get("low", close)); c = float(last.get("close", close))
        rng = max(h - l, eps)
        body = c - o
        body_atr = body / atr
        upper_wick_atr = (h - max(o, c)) / atr
        lower_wick_atr = (min(o, c) - l) / atr
        close_pos = (c - l) / rng

        ema20_series = recent["ema20"] if "ema20" in recent.columns else recent["close"].ewm(span=20, adjust=False).mean()
        ema50_series = recent["ema50"] if "ema50" in recent.columns else recent["close"].ewm(span=50, adjust=False).mean()
        close_series = recent["close"].astype(float)
        high_series = recent["high"].astype(float)
        low_series = recent["low"].astype(float)
        open_series = recent["open"].astype(float)
        ema20 = float(ema20_series.iloc[-1]); ema50 = float(ema50_series.iloc[-1])

        reject_ratio8 = float((close_series.tail(8) <= ema20_series.tail(8)).mean())
        bear_ema_stack = bool(c <= ema20 <= ema50)
        ema20_slope_8 = float((ema20_series.iloc[-1] - ema20_series.iloc[-8]) / max(abs(ema20_series.iloc[-8]), eps)) if len(ema20_series) >= 8 else 0.0

        failed_reclaims = 0
        for i in range(max(3, len(recent) - 12), len(recent)):
            window_lo = float(low_series.iloc[max(0, i-6):i].min()) if i > 0 else float(low_series.iloc[i])
            row_open = float(open_series.iloc[i]); row_close = float(close_series.iloc[i])
            row_high = float(high_series.iloc[i]); row_low = float(low_series.iloc[i])
            row_rng = max(row_high - row_low, eps)
            row_close_pos = (row_close - row_low) / row_rng
            # Pushes below local low, but reclaims/finishes strong -> bad for shorts.
            if row_low < window_lo and row_close_pos > 0.55 and row_close >= row_open:
                failed_reclaims += 1

        vol_ratio = 1.0
        if "volume" in recent.columns:
            vol_ma = float(recent["volume"].astype(float).tail(20).mean() or 0.0)
            if vol_ma > 0:
                vol_ratio = float(last.get("volume", 0.0) or 0.0) / vol_ma

        compression_bonus = 0.0
        if bool(getattr(cfg, "V60_COMPRESSION_BONUS_ENABLED", True)) and len(prev) >= 8:
            range6 = float((prev["high"].tail(6).max() - prev["low"].tail(6).min()) / atr)
            range14 = float((prev["high"].tail(14).max() - prev["low"].tail(14).min()) / atr) if len(prev) >= 14 else range6
            if range6 <= max(1.0, range14 * 0.64):
                compression_bonus = 0.12

        v61_on = bool(getattr(cfg, "V61_FREQUENCY_EXPANSION_ENABLED", False)) and str(symbol).upper() in {str(x).upper() for x in (getattr(cfg, "V61_SYMBOLS", ["BTCUSDT"]) or ["BTCUSDT"])}
        min_reject_ratio = float(getattr(cfg, "V61_SHORT_MIN_EMA20_REJECT_RATIO_8", 0.38)) if v61_on else float(getattr(cfg, "V60_MIN_EMA20_REJECT_RATIO_8", 0.45))
        max_close_pos = float(getattr(cfg, "V61_SHORT_MAX_CLOSE_POS", 0.64)) if v61_on else float(getattr(cfg, "V60_MAX_CLOSE_POS", 0.58))
        min_upper_wick = float(getattr(cfg, "V61_SHORT_MIN_UPPER_WICK_ATR", 0.06)) if v61_on else float(getattr(cfg, "V60_MIN_UPPER_WICK_ATR", 0.10))
        max_lower_wick = float(getattr(cfg, "V61_SHORT_MAX_LOWER_WICK_ATR", 1.38)) if v61_on else float(getattr(cfg, "V60_MAX_LOWER_WICK_ATR", 1.25))
        max_failed_reclaims = int(getattr(cfg, "V61_SHORT_MAX_FAILED_RECLAIMS_12", 4)) if v61_on else int(getattr(cfg, "V60_MAX_FAILED_RECLAIMS_12", 3))
        min_body_confirm = float(getattr(cfg, "V61_SHORT_MIN_BODY_ATR_CONFIRM", -0.18)) if v61_on else float(getattr(cfg, "V60_MIN_BODY_ATR_CONFIRM", -0.35))
        max_ema20_slope = float(getattr(cfg, "V61_SHORT_MIN_EMA20_DOWNSLOPE_8", 0.0004)) if v61_on else float(getattr(cfg, "V60_MIN_EMA20_DOWNSLOPE_8", -0.0002))
        min_score = float(getattr(cfg, "V61_SHORT_MIN_SCORE", 0.50)) if v61_on else float(getattr(cfg, "V60_MIN_SCORE", 0.56))

        score = 0.0
        score += 0.16 if (bear_ema_stack or not bool(getattr(cfg, "V60_REQUIRE_BEAR_EMA_STACK", False))) else 0.0
        score += 0.18 if reject_ratio8 >= min_reject_ratio else 0.0
        score += 0.16 if close_pos <= max_close_pos else 0.0
        score += 0.14 if upper_wick_atr >= min_upper_wick else 0.0
        score += 0.12 if lower_wick_atr <= max_lower_wick else 0.0
        score += 0.14 if failed_reclaims <= max_failed_reclaims else 0.0
        score += 0.10 if body_atr <= min_body_confirm else 0.0
        score += 0.10 if ema20_slope_8 <= max_ema20_slope else 0.0
        score += compression_bonus
        score = min(1.0, score)

        reasons = []
        if close_pos > max_close_pos: reasons.append("close_too_high")
        if upper_wick_atr < min_upper_wick: reasons.append("no_upper_rejection")
        if lower_wick_atr > max_lower_wick: reasons.append("lower_wick_reclaim_pressure")
        if failed_reclaims > max_failed_reclaims: reasons.append("too_many_failed_reclaims")
        if reject_ratio8 < min_reject_ratio: reasons.append("poor_ema20_rejection")
        if body_atr > min_body_confirm: reasons.append("confirmation_not_bearish")
        if ema20_slope_8 > max_ema20_slope: reasons.append("ema20_not_down")
        if score < min_score: reasons.append("low_v60_score")

        # V62: rank short candidates by bearish structure quality. V61 widened
        # the pool; this keeps only the cleaner failed-reclaim / rejection setups.
        v62_symbols = {str(x).upper() for x in (getattr(cfg, "V62_SYMBOLS", ["BTCUSDT"]) or ["BTCUSDT"])}
        v62_on = bool(getattr(cfg, "V62_SIGNAL_RANKING_ENABLED", False)) and str(symbol).upper() in v62_symbols
        v62_rank_score = 0.0
        if v62_on:
            close_rank = max(0.0, min(1.0, (0.72 - close_pos) / 0.52))
            reject_rank = max(0.0, min(1.0, reject_ratio8))
            upper_rank = max(0.0, min(1.0, upper_wick_atr / max(float(getattr(cfg, "V62_SHORT_MIN_UPPER_WICK_ATR", 0.10)) * 3.0, 1e-9)))
            lower_rank = max(0.0, min(1.0, 1.0 - (lower_wick_atr / max(float(getattr(cfg, "V62_SHORT_MAX_LOWER_WICK_ATR", 1.25)), 1e-9))))
            reclaim_rank = max(0.0, min(1.0, 1.0 - (failed_reclaims / max(float(getattr(cfg, "V62_SHORT_MAX_FAILED_RECLAIMS_12", 3)), 1.0))))
            slope_rank = 1.0 if ema20_slope_8 <= float(getattr(cfg, "V62_SHORT_MAX_EMA20_SLOPE_8", 0.0)) else 0.25
            body_rank = 1.0 if body_atr <= float(getattr(cfg, "V61_SHORT_MIN_BODY_ATR_CONFIRM", -0.18)) else 0.35
            v62_rank_score = min(1.0, 0.22*close_rank + 0.20*reject_rank + 0.16*upper_rank + 0.14*lower_rank + 0.14*reclaim_rank + 0.08*slope_rank + 0.06*body_rank)

            if score < float(getattr(cfg, "V62_SHORT_MIN_SCORE", 0.58)):
                reasons.append("v62_low_base_score")
            if v62_rank_score < float(getattr(cfg, "V62_SHORT_MIN_RANK_SCORE", 0.64)):
                reasons.append("v62_low_rank_score")
            if close_pos > float(getattr(cfg, "V62_SHORT_MAX_CLOSE_POS", 0.58)):
                reasons.append("v62_close_rank_weak")
            if upper_wick_atr < float(getattr(cfg, "V62_SHORT_MIN_UPPER_WICK_ATR", 0.10)):
                reasons.append("v62_upper_rejection_weak")
            if reject_ratio8 < float(getattr(cfg, "V62_SHORT_MIN_EMA20_REJECT_RATIO_8", 0.45)):
                reasons.append("v62_ema20_rejection_weak")
            if failed_reclaims > int(getattr(cfg, "V62_SHORT_MAX_FAILED_RECLAIMS_12", 3)):
                reasons.append("v62_failed_reclaim_rank_weak")
            if lower_wick_atr > float(getattr(cfg, "V62_SHORT_MAX_LOWER_WICK_ATR", 1.25)):
                reasons.append("v62_lower_wick_reclaim_weak")

        meta = {
            "reason": "v60_short_microstructure_ok" if not reasons else "v60_bad_short_microstructure",
            "v60_short_score": round(score, 4),
            "v60_close_pos": round(close_pos, 4),
            "v60_upper_wick_atr": round(upper_wick_atr, 4),
            "v60_lower_wick_atr": round(lower_wick_atr, 4),
            "v60_body_atr": round(body_atr, 4),
            "v60_reject_ratio8": round(reject_ratio8, 4),
            "v60_failed_reclaims": int(failed_reclaims),
            "v60_bear_ema_stack": bool(bear_ema_stack),
            "v60_ema20_slope_8": round(ema20_slope_8, 6),
            "v60_vol_ratio": round(vol_ratio, 4),
            "v60_reasons": reasons,
            "v62_short_rank_score": round(v62_rank_score, 4),
            "v62_enabled": bool(v62_on),
        }
        ok = len(reasons) == 0
        self._v60_1_short_hit("v60_checked", meta)
        if ok:
            self._v60_1_short_hit("v60_ok", meta)
        return ok, meta

    def _apply_v54_performance_scaling(self, *, symbol: str, side: str, trade_type: str, risk_mult: float, meta: dict | None = None, adx_h: float = 0.0, drift: float = 0.0) -> tuple[float, dict]:
        """V54: scale only proven BTC pullback signals.

        Uses V52 candle microstructure meta. This is intentionally a sizing layer,
        not a signal/filter layer: it never creates trades and never blocks trades.
        """
        flags = {"v54_scaled": False}
        try:
            if not bool(getattr(cfg, "V54_PERFORMANCE_SCALING_ENABLED", False)):
                return float(risk_mult), flags
            allowed_symbols = {str(x).upper() for x in (getattr(cfg, "V54_PERFORMANCE_SCALING_SYMBOLS", ["BTCUSDT"]) or ["BTCUSDT"])}
            allowed_types = {str(x).lower() for x in (getattr(cfg, "V54_PERFORMANCE_SCALING_TRADE_TYPES", ["pullback"]) or ["pullback"])}
            if str(symbol).upper() not in allowed_symbols or str(trade_type or "").lower() not in allowed_types or str(side).lower() != "long":
                return float(risk_mult), flags

            m = dict(meta or {})
            score = float(m.get("v52_score", 0.0) or 0.0)
            hold_ratio = float(m.get("v52_hold_ratio8", 0.0) or 0.0)
            failed = int(m.get("v52_failed_breakouts", 99) or 99)
            upper_wick = float(m.get("v52_upper_wick_atr", 99.0) or 99.0)
            close_pos = float(m.get("v52_close_pos", 0.0) or 0.0)
            body_atr = abs(float(m.get("v52_body_atr", 0.0) or 0.0))
            vol_ratio = float(m.get("v52_vol_ratio", 1.0) or 1.0)
            ema_stack_ok = bool(m.get("v52_ema_stack_ok", False))

            if bool(getattr(cfg, "V54_REQUIRE_EMA_STACK", True)) and not ema_stack_ok:
                flags.update({"v54_reason": "ema_stack_not_ok", "v54_score": score})
                return float(risk_mult), flags
            if hold_ratio < float(getattr(cfg, "V54_MIN_HOLD_RATIO8_FOR_SCALE", 0.62)):
                flags.update({"v54_reason": "hold_ratio_too_low", "v54_score": score})
                return float(risk_mult), flags
            if failed > int(getattr(cfg, "V54_MAX_FAILED_BREAKOUTS_FOR_SCALE", 1)):
                flags.update({"v54_reason": "too_many_failed_breakouts", "v54_score": score})
                return float(risk_mult), flags
            if upper_wick > float(getattr(cfg, "V54_MAX_UPPER_WICK_ATR_FOR_SCALE", 0.85)):
                flags.update({"v54_reason": "upper_wick_too_high", "v54_score": score})
                return float(risk_mult), flags
            if close_pos < float(getattr(cfg, "V54_MIN_CLOSE_POS_FOR_SCALE", 0.52)):
                flags.update({"v54_reason": "close_pos_too_low", "v54_score": score})
                return float(risk_mult), flags
            if body_atr > float(getattr(cfg, "V54_MAX_BODY_ATR_FOR_SCALE", 1.65)):
                flags.update({"v54_reason": "body_too_wide", "v54_score": score})
                return float(risk_mult), flags
            if vol_ratio > float(getattr(cfg, "V54_MAX_VOL_RATIO_FOR_SCALE", 3.20)):
                flags.update({"v54_reason": "volume_spike_too_high", "v54_score": score})
                return float(risk_mult), flags

            strong_score = float(getattr(cfg, "V54_SCORE_STRONG", 0.72))
            elite_score = float(getattr(cfg, "V54_SCORE_ELITE", 0.86))
            mult = 1.0
            tier = "base"
            if score >= elite_score:
                mult = float(getattr(cfg, "V54_ELITE_MULT", 1.38))
                tier = "elite"
            elif score >= strong_score:
                mult = float(getattr(cfg, "V54_STRONG_MULT", 1.18))
                tier = "strong"

            max_total = float(getattr(cfg, "V54_MAX_TOTAL_RISK_MULT", 4.10))
            tuned = min(max_total, float(risk_mult) * float(mult))
            flags.update({
                "v54_scaled": tuned > float(risk_mult) + 1e-12,
                "v54_tier": tier,
                "v54_score": round(score, 4),
                "v54_mult": round(mult, 4),
                "v54_risk_mult_before": round(float(risk_mult), 4),
                "v54_risk_mult_after": round(float(tuned), 4),
            })
            return tuned, flags
        except Exception as exc:
            flags.update({"v54_scaled": False, "v54_error": str(exc)})
            return float(risk_mult), flags


    def _apply_v55_global_risk_scale(self, *, symbol: str, side: str, trade_type: str, risk_mult: float, meta: dict | None = None) -> tuple[float, dict]:
        """V55: global sizing layer for the proven BTC pullback core.

        V54 was too selective and often did not activate. V55 deliberately scales
        every already-approved BTC pullback signal, while refusing only obviously
        dirty microstructure cases. It never creates or blocks signals.
        """
        flags = {"v55_scaled": False}
        try:
            if not bool(getattr(cfg, "V55_GLOBAL_RISK_SCALE_ENABLED", False)):
                return float(risk_mult), flags
            allowed_symbols = {str(x).upper() for x in (getattr(cfg, "V55_GLOBAL_RISK_SCALE_SYMBOLS", ["BTCUSDT"]) or ["BTCUSDT"])}
            allowed_types = {str(x).lower() for x in (getattr(cfg, "V55_GLOBAL_RISK_SCALE_TRADE_TYPES", ["pullback"]) or ["pullback"])}
            if str(symbol).upper() not in allowed_symbols or str(trade_type or "").lower() not in allowed_types or str(side).lower() != "long":
                return float(risk_mult), flags

            m = dict(meta or {})
            score = float(m.get("v52_score", 0.0) or 0.0)
            failed = int(m.get("v52_failed_breakouts", 0) or 0)
            upper_wick = float(m.get("v52_upper_wick_atr", 0.0) or 0.0)
            vol_ratio = float(m.get("v52_vol_ratio", 1.0) or 1.0)

            # Do not scale the dirtiest allowed entries. They still may trade,
            # but without the aggressive v55 multiplier.
            if failed > int(getattr(cfg, "V55_MAX_FAILED_BREAKOUTS", 2)):
                flags.update({"v55_reason": "too_many_failed_breakouts", "v55_score": round(score, 4)})
                return float(risk_mult), flags
            if upper_wick > float(getattr(cfg, "V55_MAX_UPPER_WICK_ATR", 1.05)):
                flags.update({"v55_reason": "upper_wick_too_high", "v55_score": round(score, 4)})
                return float(risk_mult), flags
            if vol_ratio > float(getattr(cfg, "V55_MAX_VOL_RATIO", 4.00)):
                flags.update({"v55_reason": "volume_spike_too_high", "v55_score": round(score, 4)})
                return float(risk_mult), flags

            mult = float(getattr(cfg, "V55_BASE_RISK_MULT", 2.20))
            tier = "base"
            if score >= float(getattr(cfg, "V55_ELITE_SCORE", 0.82)):
                mult *= float(getattr(cfg, "V55_ELITE_EXTRA_MULT", 1.22))
                tier = "elite"
            elif score >= float(getattr(cfg, "V55_STRONG_SCORE", 0.68)):
                mult *= float(getattr(cfg, "V55_STRONG_EXTRA_MULT", 1.10))
                tier = "strong"

            max_total = float(getattr(cfg, "V55_MAX_TOTAL_RISK_MULT", 7.50))
            tuned = min(max_total, float(risk_mult) * mult)
            flags.update({
                "v55_scaled": tuned > float(risk_mult) + 1e-12,
                "v55_tier": tier,
                "v55_score": round(score, 4),
                "v55_mult": round(mult, 4),
                "v55_risk_mult_before": round(float(risk_mult), 4),
                "v55_risk_mult_after": round(float(tuned), 4),
            })
            return tuned, flags
        except Exception as exc:
            flags.update({"v55_scaled": False, "v55_error": str(exc)})
            return float(risk_mult), flags



    def _btc_short_context_ok(self, symbol: str, regime: str, market_state: str, adx_h: float, rsi_h: float, drift: float, btc_score: float | None = None) -> tuple[bool, dict]:
        btc_symbol = str(getattr(cfg, "BTC_REGIME_FILTER_SYMBOL", "BTCUSDT"))
        if symbol != btc_symbol:
            return True, {"reason": "not_btc_symbol"}
        if not self._symbol_flag(symbol, "BTC_SHORTS_ONLY_STRONG_BEAR", bool(getattr(cfg, "BTC_SHORTS_ONLY_STRONG_BEAR", True))):
            return True, {"reason": "btc_short_gate_disabled"}
        min_adx = cfg.get_symbol_param_float(symbol, "BTC_SHORT_MIN_HTF_ADX", float(getattr(cfg, "BTC_SHORT_MIN_HTF_ADX", 24.0)))
        min_drift = cfg.get_symbol_param_float(symbol, "BTC_SHORT_MIN_DRIFT_PCT", float(getattr(cfg, "BTC_SHORT_MIN_DRIFT_PCT", 0.010)))
        max_rsi = cfg.get_symbol_param_float(symbol, "BTC_SHORT_MAX_HTF_RSI", float(getattr(cfg, "BTC_SHORT_MAX_HTF_RSI", 48.0)))
        min_score = cfg.get_symbol_param_float(symbol, "BTC_SHORT_MIN_BTC_SCORE", float(getattr(cfg, "BTC_SHORT_MIN_BTC_SCORE", 1.05)))
        score = float(btc_score if btc_score is not None else 999.0)
        ok = bool(regime == "bear" and market_state == "trend" and adx_h >= min_adx and drift >= min_drift and rsi_h <= max_rsi and score >= min_score)
        return ok, {"regime": regime, "market_state": market_state, "adx_h": adx_h, "drift": drift, "rsi_h": rsi_h, "btc_score": score, "min_adx": min_adx, "min_drift": min_drift, "max_rsi": max_rsi, "min_score": min_score}

    def _btc_short_trade_ok(self, symbol: str, trade_type: str, regime: str, market_state: str, adx_h: float, rsi_h: float, drift: float, btc_score: float | None = None) -> tuple[bool, dict]:
        btc_symbol = str(getattr(cfg, "BTC_REGIME_FILTER_SYMBOL", "BTCUSDT"))
        if symbol != btc_symbol:
            return True, {"reason": "not_btc_symbol", "trade_type": trade_type}

        if trade_type == "impulse" and self._symbol_flag(symbol, "BTC_DISABLE_IMPULSE_SHORT", bool(getattr(cfg, "BTC_DISABLE_IMPULSE_SHORT", True))):
            return False, {"reason": "btc_impulse_short_disabled", "trade_type": trade_type}
        if trade_type == "fakeout" and self._symbol_flag(symbol, "BTC_DISABLE_FAKEOUT_SHORT", bool(getattr(cfg, "BTC_DISABLE_FAKEOUT_SHORT", True))):
            return False, {"reason": "btc_fakeout_short_disabled", "trade_type": trade_type}
        if trade_type == "cont_compression" and self._symbol_flag(symbol, "BTC_DISABLE_CONT_COMP_SHORT", bool(getattr(cfg, "BTC_DISABLE_CONT_COMP_SHORT", True))):
            return False, {"reason": "btc_cont_comp_short_disabled", "trade_type": trade_type}

        if trade_type == "pullback" and bool(getattr(cfg, "V60_2_REAL_SHORT_ENABLE", False)) and bool(getattr(cfg, "V60_2_BYPASS_LEGACY_BTC_SHORT_GATE", True)):
            return True, {"reason": "v60_2_pullback_short_gate_bypass", "trade_type": trade_type, "regime": regime, "market_state": market_state, "v60_2_bypass": True}

        if trade_type == "continuation":
            min_adx = cfg.get_symbol_param_float(symbol, "BTC_SHORT_CONT_MIN_HTF_ADX", float(getattr(cfg, "BTC_SHORT_CONT_MIN_HTF_ADX", 17.0)))
            min_drift = cfg.get_symbol_param_float(symbol, "BTC_SHORT_CONT_MIN_DRIFT_PCT", float(getattr(cfg, "BTC_SHORT_CONT_MIN_DRIFT_PCT", 0.004)))
            max_rsi = cfg.get_symbol_param_float(symbol, "BTC_SHORT_CONT_MAX_HTF_RSI", float(getattr(cfg, "BTC_SHORT_CONT_MAX_HTF_RSI", 58.0)))
            min_score = cfg.get_symbol_param_float(symbol, "BTC_SHORT_CONT_MIN_BTC_SCORE", float(getattr(cfg, "BTC_SHORT_CONT_MIN_BTC_SCORE", 0.95)))
            score = float(btc_score if btc_score is not None else 999.0)
            ok = bool(regime == "bear" and market_state in {"trend", "transition"} and adx_h >= min_adx and drift >= min_drift and rsi_h <= max_rsi and score >= min_score)
            return ok, {"reason": "btc_continuation_short_gate", "trade_type": trade_type, "regime": regime, "market_state": market_state, "adx_h": adx_h, "drift": drift, "rsi_h": rsi_h, "btc_score": score, "min_adx": min_adx, "min_drift": min_drift, "max_rsi": max_rsi, "min_score": min_score}

        return self._btc_short_context_ok(symbol=symbol, regime=regime, market_state=market_state, adx_h=adx_h, rsi_h=rsi_h, drift=drift, btc_score=btc_score)

    def _check_directional_regime_gate(self, symbol: str, side: str, trade_type: str, regime: str, market_state: str, adx_h: float, atr_pct_h: float, drift: float, rsi_h: float) -> tuple[bool, dict]:
        if not bool(cfg.get_symbol_param(symbol, "MARKET_REGIME_DIRECTIONAL_GATE_ENABLED", getattr(cfg, "MARKET_REGIME_DIRECTIONAL_GATE_ENABLED", True))):
            return True, {"enabled": False}

        expected_regime = "bull" if side == "long" else "bear"
        min_adx = float(cfg.get_symbol_param_float(symbol, "MARKET_REGIME_DIRECTIONAL_MIN_HTF_ADX", float(getattr(cfg, "MARKET_REGIME_DIRECTIONAL_MIN_HTF_ADX", 23.0))))
        min_atr_pct = float(cfg.get_symbol_param_float(symbol, "MARKET_REGIME_DIRECTIONAL_MIN_HTF_ATR_PCT", float(getattr(cfg, "MARKET_REGIME_DIRECTIONAL_MIN_HTF_ATR_PCT", 0.0014))))
        min_drift = float(cfg.get_symbol_param_float(symbol, "MARKET_REGIME_DIRECTIONAL_MIN_DRIFT_PCT", float(getattr(cfg, "MARKET_REGIME_DIRECTIONAL_MIN_DRIFT_PCT", 0.0050))))
        min_rsi_long = float(cfg.get_symbol_param_float(symbol, "MARKET_REGIME_DIRECTIONAL_MIN_HTF_RSI_LONG", float(getattr(cfg, "MARKET_REGIME_DIRECTIONAL_MIN_HTF_RSI_LONG", 54.0))))
        max_rsi_short = float(cfg.get_symbol_param_float(symbol, "MARKET_REGIME_DIRECTIONAL_MAX_HTF_RSI_SHORT", float(getattr(cfg, "MARKET_REGIME_DIRECTIONAL_MAX_HTF_RSI_SHORT", 46.0))))
        transition_min_adx = float(cfg.get_symbol_param_float(symbol, "MARKET_REGIME_DIRECTIONAL_TRANSITION_MIN_HTF_ADX", float(getattr(cfg, "MARKET_REGIME_DIRECTIONAL_TRANSITION_MIN_HTF_ADX", 26.0))))
        transition_min_drift = float(cfg.get_symbol_param_float(symbol, "MARKET_REGIME_DIRECTIONAL_TRANSITION_MIN_DRIFT_PCT", float(getattr(cfg, "MARKET_REGIME_DIRECTIONAL_TRANSITION_MIN_DRIFT_PCT", 0.0065))))
        block_impulse_transition = bool(cfg.get_symbol_param(symbol, "MARKET_REGIME_DIRECTIONAL_BLOCK_IMPULSE_IN_TRANSITION", getattr(cfg, "MARKET_REGIME_DIRECTIONAL_BLOCK_IMPULSE_IN_TRANSITION", True)))
        allow_cont_transition = bool(cfg.get_symbol_param(symbol, "MARKET_REGIME_DIRECTIONAL_ALLOW_CONTINUATION_IN_TRANSITION", getattr(cfg, "MARKET_REGIME_DIRECTIONAL_ALLOW_CONTINUATION_IN_TRANSITION", True)))

        if regime != expected_regime:
            return False, {"reason": "regime_mismatch", "regime": regime, "expected_regime": expected_regime, "trade_type": trade_type, "side": side}

        if market_state == "transition":
            if trade_type == "impulse" and block_impulse_transition:
                return False, {"reason": "transition_blocked_for_impulse", "trade_type": trade_type, "side": side, "adx_h": adx_h, "drift": drift}
            if trade_type in {"continuation", "cont_compression"} and allow_cont_transition:
                if adx_h < transition_min_adx or drift < transition_min_drift:
                    return False, {
                        "reason": "transition_too_weak",
                        "trade_type": trade_type,
                        "side": side,
                        "adx_h": adx_h,
                        "drift": drift,
                        "min_adx": transition_min_adx,
                        "min_drift": transition_min_drift,
                    }
            else:
                return False, {"reason": "transition_blocked", "trade_type": trade_type, "side": side}
        elif market_state != "trend":
            return False, {"reason": "non_directional_market_state", "trade_type": trade_type, "side": side, "market_state": market_state}

        if adx_h < min_adx or atr_pct_h < min_atr_pct or drift < min_drift:
            return False, {
                "reason": "weak_directional_regime",
                "trade_type": trade_type,
                "side": side,
                "adx_h": adx_h,
                "atr_pct_h": atr_pct_h,
                "drift": drift,
                "min_adx": min_adx,
                "min_atr_pct": min_atr_pct,
                "min_drift": min_drift,
            }

        if side == "long" and rsi_h < min_rsi_long:
            return False, {"reason": "htf_rsi_not_bullish_enough", "trade_type": trade_type, "side": side, "rsi_h": rsi_h, "min_rsi_long": min_rsi_long}
        if side == "short" and rsi_h > max_rsi_short:
            return False, {"reason": "htf_rsi_not_bearish_enough", "trade_type": trade_type, "side": side, "rsi_h": rsi_h, "max_rsi_short": max_rsi_short}

        return True, {
            "trade_type": trade_type,
            "side": side,
            "regime": regime,
            "market_state": market_state,
            "adx_h": adx_h,
            "atr_pct_h": atr_pct_h,
            "drift": drift,
            "rsi_h": rsi_h,
            "min_adx": min_adx,
            "min_atr_pct": min_atr_pct,
            "min_drift": min_drift,
        }

    def _check_trend_strength_and_chop(self, symbol: str, df: pd.DataFrame, recent: pd.DataFrame, side: str, trade_type: str, close: float, atr_ltf: float, adx_h: float, atr_pct_h: float, drift: float) -> tuple[bool, dict]:
        if not bool(cfg.get_symbol_param(symbol, "TREND_QUALITY_FILTER_ENABLED", getattr(cfg, "TREND_QUALITY_FILTER_ENABLED", True))):
            return True, {"enabled": False}

        try:
            htf_slope_lookback = int(cfg.get_symbol_param_float(symbol, "TREND_QUALITY_HTF_SLOPE_LOOKBACK", int(getattr(cfg, "TREND_QUALITY_HTF_SLOPE_LOOKBACK", 8))))
            chop_lookback = int(cfg.get_symbol_param_float(symbol, "CHOP_FILTER_LOOKBACK", int(getattr(cfg, "CHOP_FILTER_LOOKBACK", 12))))
            max_crosses = int(cfg.get_symbol_param_float(symbol, "CHOP_FILTER_MAX_EMA20_CROSSES", int(getattr(cfg, "CHOP_FILTER_MAX_EMA20_CROSSES", 3))))
            max_wickiness = float(cfg.get_symbol_param_float(symbol, "CHOP_FILTER_MAX_WICKINESS", float(getattr(cfg, "CHOP_FILTER_MAX_WICKINESS", 0.62))))
            min_body_ratio = float(cfg.get_symbol_param_float(symbol, "CHOP_FILTER_MIN_BODY_RATIO", float(getattr(cfg, "CHOP_FILTER_MIN_BODY_RATIO", 0.33))))
            min_htf_ema20_slope = float(cfg.get_symbol_param_float(symbol, "TREND_QUALITY_MIN_HTF_EMA20_SLOPE_PCT", float(getattr(cfg, "TREND_QUALITY_MIN_HTF_EMA20_SLOPE_PCT", 0.0032))))
            min_htf_ema50_slope = float(cfg.get_symbol_param_float(symbol, "TREND_QUALITY_MIN_HTF_EMA50_SLOPE_PCT", float(getattr(cfg, "TREND_QUALITY_MIN_HTF_EMA50_SLOPE_PCT", 0.0018))))
            min_combo_adx = float(cfg.get_symbol_param_float(symbol, "TREND_QUALITY_COMBO_MIN_HTF_ADX", float(getattr(cfg, "TREND_QUALITY_COMBO_MIN_HTF_ADX", 26.0))))
            min_combo_drift = float(cfg.get_symbol_param_float(symbol, "TREND_QUALITY_COMBO_MIN_DRIFT_PCT", float(getattr(cfg, "TREND_QUALITY_COMBO_MIN_DRIFT_PCT", 0.0062))))
            min_combo_atr_pct = float(cfg.get_symbol_param_float(symbol, "TREND_QUALITY_COMBO_MIN_ATR_PCT", float(getattr(cfg, "TREND_QUALITY_COMBO_MIN_ATR_PCT", 0.0015))))
            impulse_max_wickiness = float(cfg.get_symbol_param_float(symbol, "IMPULSE_QUALITY_MAX_WICKINESS", float(getattr(cfg, "IMPULSE_QUALITY_MAX_WICKINESS", 0.58))))
            impulse_min_body_ratio = float(cfg.get_symbol_param_float(symbol, "IMPULSE_QUALITY_MIN_BODY_RATIO", float(getattr(cfg, "IMPULSE_QUALITY_MIN_BODY_RATIO", 0.37))))
        except Exception as exc:
            return False, {"reason": "trend_quality_cfg_error", "error": str(exc)}

        if len(df) < htf_slope_lookback + 1 or len(recent) < max(chop_lookback, 3):
            return True, {"skipped": "not_enough_history"}

        try:
            htf_recent = df.iloc[-(htf_slope_lookback + 1):]
            ema20_now = float(htf_recent["HTF_EMA20"].iloc[-1])
            ema20_prev = float(htf_recent["HTF_EMA20"].iloc[0])
            ema50_now = float(htf_recent["HTF_EMA50"].iloc[-1])
            ema50_prev = float(htf_recent["HTF_EMA50"].iloc[0])
        except Exception as exc:
            return False, {"reason": "trend_quality_missing_htf_ema", "error": str(exc)}

        ema20_slope_pct = abs(ema20_now - ema20_prev) / close if close > 0 else 0.0
        ema50_slope_pct = abs(ema50_now - ema50_prev) / close if close > 0 else 0.0

        aligned = (ema20_now >= ema50_now) if side == "long" else (ema20_now <= ema50_now)
        if not aligned:
            return False, {"reason": "htf_ema_alignment_failed", "side": side, "ema20": ema20_now, "ema50": ema50_now}

        slope_ok = ema20_slope_pct >= min_htf_ema20_slope and ema50_slope_pct >= min_htf_ema50_slope
        combo_ok = adx_h >= min_combo_adx and drift >= min_combo_drift and atr_pct_h >= min_combo_atr_pct
        if not (slope_ok or combo_ok):
            return False, {
                "reason": "weak_trend_quality",
                "side": side,
                "trade_type": trade_type,
                "ema20_slope_pct": ema20_slope_pct,
                "ema50_slope_pct": ema50_slope_pct,
                "adx_h": adx_h,
                "drift": drift,
                "atr_pct_h": atr_pct_h,
                "min_htf_ema20_slope": min_htf_ema20_slope,
                "min_htf_ema50_slope": min_htf_ema50_slope,
                "min_combo_adx": min_combo_adx,
                "min_combo_drift": min_combo_drift,
                "min_combo_atr_pct": min_combo_atr_pct,
            }

        recent_slice = recent.tail(chop_lookback).copy()
        try:
            close_s = recent_slice["close"].astype(float)
            open_s = recent_slice["open"].astype(float)
            high_s = recent_slice["high"].astype(float)
            low_s = recent_slice["low"].astype(float)
            ema20_ltf = recent_slice["EMA20"].astype(float)
        except Exception as exc:
            return False, {"reason": "trend_quality_missing_ltf_cols", "error": str(exc)}

        candle_range = (high_s - low_s).replace(0.0, np.nan)
        body_ratio = ((close_s - open_s).abs() / candle_range).replace([np.inf, -np.inf], np.nan).fillna(0.0)
        wickiness = (((high_s - np.maximum(open_s, close_s)) + (np.minimum(open_s, close_s) - low_s)) / candle_range).replace([np.inf, -np.inf], np.nan).fillna(1.0)
        sign_series = np.sign((close_s - ema20_ltf).fillna(0.0).to_numpy())
        nonzero_signs = [int(s) for s in sign_series if s != 0]
        ema20_crosses = sum(1 for i in range(1, len(nonzero_signs)) if nonzero_signs[i] != nonzero_signs[i - 1])
        mean_body_ratio = float(body_ratio.mean()) if len(body_ratio) else 0.0
        mean_wickiness = float(wickiness.mean()) if len(wickiness) else 1.0

        effective_max_wickiness = impulse_max_wickiness if trade_type == "impulse" else max_wickiness
        effective_min_body_ratio = impulse_min_body_ratio if trade_type == "impulse" else min_body_ratio

        if ema20_crosses > max_crosses:
            return False, {"reason": "chop_too_many_ema20_crosses", "trade_type": trade_type, "ema20_crosses": ema20_crosses, "max_crosses": max_crosses}

        if mean_wickiness > effective_max_wickiness and mean_body_ratio < effective_min_body_ratio:
            return False, {
                "reason": "choppy_wicky_price_action",
                "trade_type": trade_type,
                "mean_wickiness": mean_wickiness,
                "max_wickiness": effective_max_wickiness,
                "mean_body_ratio": mean_body_ratio,
                "min_body_ratio": effective_min_body_ratio,
                "atr_ltf": atr_ltf,
            }

        return True, {
            "trade_type": trade_type,
            "ema20_slope_pct": ema20_slope_pct,
            "ema50_slope_pct": ema50_slope_pct,
            "ema20_crosses": ema20_crosses,
            "mean_wickiness": mean_wickiness,
            "mean_body_ratio": mean_body_ratio,
        }



    def signal(self, df: pd.DataFrame) -> Optional[str]:
        self.last_signal_meta = empty_signal_meta()
        signal_ctx = extract_signal_context(df)
        if signal_ctx is None:
            return None

        last = signal_ctx["last"]
        close = signal_ctx["close"]
        high = signal_ctx["high"]
        low = signal_ctx["low"]
        volume = signal_ctx["volume"]
        rsi_ltf = signal_ctx["rsi_ltf"]
        atr_ltf = signal_ctx["atr_ltf"]
        ema20_h = signal_ctx["ema20_h"]
        ema50_h = signal_ctx["ema50_h"]
        ema200_h = signal_ctx["ema200_h"]
        atr_h = signal_ctx["atr_h"]
        adx_h = signal_ctx["adx_h"]
        rsi_h = signal_ctx["rsi_h"]
        sma_trend_h = signal_ctx["sma_trend_h"]

        # ======================================================
        # 1) HTF/market state
        # ======================================================
        regime = self._resolve_regime_from_values(ema20_h, ema50_h, ema200_h)
        symbol = self._extract_symbol(df)
        if bool(getattr(cfg, "V39_BTC_SCALE_ENGINE_ENABLED", False)):
            disabled = {str(x).upper() for x in (getattr(cfg, "V39_DISABLED_SYMBOLS", []) or [])}
            production = {str(x).upper() for x in (getattr(cfg, "V39_PRODUCTION_SYMBOLS", ["BTCUSDT"]) or ["BTCUSDT"])}
            symbol_u = str(symbol or "").upper()
            if symbol_u in disabled or (production and symbol_u not in production):
                return None
        is_alt = self._is_alt_symbol(symbol)

        # v86 production refactor: keep all meta/control variables initialized
        # before optional signal branches. This removes fragile locals() checks
        # and avoids "referenced before assignment" warnings in static analysis.
        btc_meta = {}
        volume_meta = {}
        regime_gate_ok = False
        regime_gate_meta = {"not_evaluated": True}
        trend_quality_ok = False
        trend_quality_meta = {"not_evaluated": True}
        strong_setup = False

        self._current_symbol = symbol
        self._current_regime = regime
        self._alt_trace("signal_enter", symbol=symbol, rows=len(df), close=round(close, 6), adx_h=round(adx_h, 6), regime=regime)

        session_ok, session_meta = self._is_allowed_trading_time(df)
        if not session_ok:
            if is_alt and bool(getattr(cfg, "ALT_IGNORE_SESSION_FILTER", True)):
                self._alt_trace("soft_pass", symbol=symbol, stage="session", reason="alt_ignore_disallowed_trading_time")
            else:
                logger.debug("[MTF] skip disallowed trading session: %s", session_meta)
                self._alt_trace("early_return", symbol=symbol, stage="session", reason="disallowed_trading_time")
                return None

        precheck = run_market_regime_precheck(
            self,
            df,
            symbol=symbol,
            is_alt=is_alt,
            regime=regime,
            close=close,
            atr_ltf=atr_ltf,
            atr_h=atr_h,
            adx_h=adx_h,
            ema20_h=ema20_h,
            ema50_h=ema50_h,
        )
        if precheck.get("should_return"):
            return precheck.get("result")

        atr_pct_h = float(precheck["atr_pct_h"])
        drift = float(precheck["drift"])
        drift_h = float(precheck["drift_h"])
        drift_min_pct = float(precheck["drift_min_pct"])
        drift_strong_pct = float(precheck["drift_strong_pct"])
        market_state = precheck["market_state"]
        market_meta = precheck["market_meta"]
        transition_state = bool(precheck["transition_state"])
        self._current_market_state = str(market_state or "unknown")
        self._current_adx_h = float(adx_h)
        self._current_drift = float(drift)

        # ======================================================
        # 2) LTF breakout (M15)
        # ======================================================
        # Динамический lookback на LTF в зависимости от HTF-волатильности.
        # Базовое значение берём из конфигурации, но сужаем/расширяем при высокой/низкой волатильности.
        base_lookback = cfg.get_symbol_param_int(symbol, "MTF_LTF_LOOKBACK", int(getattr(cfg, "MTF_LTF_LOOKBACK", getattr(cfg, "BREAKOUT_LOOKBACK", 20))))
        low_vol_pct = float(getattr(cfg, "MTF_ATR_LOW_VOL_PCT", 0.003))
        high_vol_pct = float(getattr(cfg, "MTF_ATR_HIGH_VOL_PCT", 0.015))
        lb_min = int(getattr(cfg, "MTF_LOOKBACK_MIN", 40))
        lb_max = int(getattr(cfg, "MTF_LOOKBACK_MAX", 80))

        lookback_ltf = base_lookback
        # atr_pct_h уже посчитан выше как atr_h / close
        if atr_pct_h < low_vol_pct:
            # рынок очень спокойный -> расширяем диапазон
            lookback_ltf = min(lb_max, int(base_lookback * 1.3))
        elif atr_pct_h > high_vol_pct:
            # рынок очень волатильный -> чуть сужаем диапазон
            lookback_ltf = max(lb_min, int(base_lookback * 0.7))

        # Дополнительная адаптация lookback по силе тренда (дрейфу).
        # При слабом тренде расширяем диапазон, чтобы реже ловить шумовые пробои.
        # При сильном тренде слегка сужаем, чтобы входить раньше.
        if drift > drift_min_pct and drift < drift_strong_pct:
            lookback_ltf = min(lb_max, int(lookback_ltf * 1.2))
        elif drift >= drift_strong_pct:
            lookback_ltf = max(lb_min, int(lookback_ltf * 0.85))

        if len(df) < lookback_ltf + 2:
            return None

        recent = df.iloc[-lookback_ltf - 1:-1]
        range_high = float(recent["high"].max())
        range_low = float(recent["low"].min())

        # Буфер по цене: BREAKOUT_BUFFER_PCT трактуем как долю (0.001 = 0.1%)
        buf = cfg.get_symbol_param_float(symbol, "BREAKOUT_BUFFER_PCT", float(getattr(cfg, "BREAKOUT_BUFFER_PCT", 0.001)))
        long_trigger = range_high * (1.0 + buf)
        short_trigger = range_low * (1.0 - buf)

        bar_index = len(df) - 1
        is_btc_symbol = symbol == str(getattr(cfg, "BTC_REGIME_FILTER_SYMBOL", "BTCUSDT"))
        eth_engine_symbols = set(getattr(cfg, "V14_ETH_ENGINE_SYMBOLS", ["ETHUSDT", "SOLUSDT", "AVAXUSDT", "BNBUSDT"]) or ["ETHUSDT", "SOLUSDT", "AVAXUSDT", "BNBUSDT"])
        is_eth_liquidity_symbol = symbol in eth_engine_symbols
        v14_split_enabled = bool(getattr(cfg, "V14_MULTI_ASSET_SPLIT_ENABLED", False))
        btc_trend_only = v14_split_enabled and is_btc_symbol and bool(getattr(cfg, "V14_BTC_TREND_ONLY", True))
        eth_disable_legacy_non_trend = v14_split_enabled and is_eth_liquidity_symbol and bool(getattr(cfg, "V14_ETH_DISABLE_LEGACY_NON_TREND", True))

        if bool(getattr(cfg, "V72_ENABLE_LEGACY_ETH_LIQUIDITY_ENGINE", False)) and v14_split_enabled and is_eth_liquidity_symbol:
            if bool(getattr(cfg, "V28_MICRO_ENGINE_ENABLED", False)) and str(market_state) in set(getattr(cfg, "V28_MICRO_ALLOWED_MARKET_STATES", ["range", "transition", "flat"]) or ["range", "transition", "flat"]):
                eth_cooldown = int(getattr(cfg, "V28_MICRO_COOLDOWN_BARS", getattr(cfg, "V17_ETH_LIQUIDITY_COOLDOWN_BARS", 20)))
            elif symbol in set(getattr(cfg, "V27_ALT_TREND_SYMBOLS", []) or []):
                eth_cooldown = int(getattr(cfg, "V30_ALT_TREND_COOLDOWN_BARS", getattr(cfg, "V27_ALT_TREND_COOLDOWN_BARS", getattr(cfg, "V17_ETH_TREND_COOLDOWN_BARS", 14))))
            elif bool(getattr(cfg, "V17_ETH_USE_SEPARATE_TREND_COOLDOWN", False)) and market_state == "trend":
                eth_cooldown = int(getattr(cfg, "V17_ETH_TREND_COOLDOWN_BARS", getattr(cfg, "V14_ETH_COOLDOWN_BARS", 14)))
            else:
                eth_cooldown = int(getattr(cfg, "V17_ETH_LIQUIDITY_COOLDOWN_BARS", getattr(cfg, "V14_ETH_COOLDOWN_BARS", 14)))
            last_bar_by_symbol = getattr(self, "_last_eth_liquidity_bar_by_symbol", None)
            if last_bar_by_symbol is None:
                last_bar_by_symbol = {}
                self._last_eth_liquidity_bar_by_symbol = last_bar_by_symbol
            last_eth_bar = int(last_bar_by_symbol.get(symbol, -10**9))
            if bar_index - last_eth_bar >= eth_cooldown:
                eth_signal, eth_trade_type, eth_risk, eth_meta = run_eth_liquidity_engine_v1(
                    cfg=cfg, symbol=symbol, market_state=market_state, regime=regime, df=df, recent=recent, last=last, close=close, atr_ltf=atr_ltf, adx_h=adx_h, drift=drift, range_high=range_high, range_low=range_low, market_meta=market_meta,
                )
                if eth_signal is not None:
                    last_bar_by_symbol[symbol] = bar_index
                    self._eth_debug("engine_signal", symbol=symbol, signal=eth_signal, trade_type=eth_trade_type, side=("long" if eth_signal == "buy" else "short"), market_state=market_state, regime=regime, reason=eth_meta.get("reason"))
                    return self._set_signal(eth_signal, trade_type=eth_trade_type, risk_multiplier=eth_risk, market_state=market_state, regime=regime, symbol=symbol, side=("long" if eth_signal == "buy" else "short"), eth_liquidity_meta=eth_meta)
                else:
                    self._eth_debug("engine_skip", symbol=symbol, market_state=market_state, regime=regime, reason=eth_meta.get("reason"), long_candidate_reason=eth_meta.get("long_candidate_reason"), short_candidate_reason=eth_meta.get("short_candidate_reason"), adx_h=adx_h, drift=drift)
            if bool(getattr(cfg, "V14_ETH_DISABLE_LEGACY_TREND", True)):
                self._eth_debug("engine_skip", symbol=symbol, market_state=market_state, regime=regime, reason="eth_legacy_trend_disabled_no_signal", adx_h=adx_h, drift=drift)
                return None

        if bool(getattr(cfg, "V72_ENABLE_LEGACY_NON_TREND_ENGINES", False)) and not btc_trend_only and not eth_disable_legacy_non_trend:
            range_engine_cooldown_bars = int(getattr(cfg, "BTC_RANGE_ENGINE_V1_COOLDOWN_BARS", 8))
            if is_btc_symbol and (bar_index - int(getattr(self, "_last_btc_range_engine_bar_index", -10**9)) >= range_engine_cooldown_bars):
                range_engine_signal, range_engine_trade_type, range_engine_risk, range_engine_meta = run_btc_range_engine_v1(
                    cfg=cfg,
                    symbol=symbol,
                    market_state=market_state,
                    regime=regime,
                    df=df,
                    recent=recent,
                    last=last,
                    close=close,
                    atr_ltf=atr_ltf,
                    adx_h=adx_h,
                    drift=drift,
                    range_high=range_high,
                    range_low=range_low,
                    market_meta=market_meta,
                )
                if range_engine_signal is not None:
                    self._last_btc_range_engine_bar_index = bar_index
                    range_setup = str(range_engine_meta.get("range_setup", "") or "")
                    side = "long" if range_engine_signal == "buy" else "short"
                    meta_key = f"{range_setup}_meta" if range_setup else "range_engine_meta"
                    self._btc_range_debug("engine_signal", symbol=symbol, signal=range_engine_signal, trade_type=range_engine_trade_type, side=side, market_state=market_state, regime=regime, range_setup=range_setup, range_regime=range_engine_meta.get("range_regime"), reason=range_engine_meta.get("reason"))
                    return self._set_signal(range_engine_signal, trade_type=range_engine_trade_type, risk_multiplier=range_engine_risk, market_state=market_state, regime=regime, side=side, allow_btc_range_short_bypass=bool(range_engine_meta.get("allow_btc_range_short_bypass", False)), **{meta_key: range_engine_meta})
                elif is_btc_symbol and self._btc_range_debug_enabled():
                    max_logs = int(getattr(cfg, "BTC_RANGE_DEBUG_MAX_NO_SIGNAL_LOGS", 250))
                    if self._btc_range_debug_no_signal_logs < max_logs:
                        self._btc_range_debug_no_signal_logs += 1
                        self._btc_range_debug("engine_skip", symbol=symbol, market_state=market_state, regime=regime, reason=range_engine_meta.get("reason"), range_regime=range_engine_meta.get("range_regime"), long_candidate_reason=range_engine_meta.get("long_candidate_reason"), short_candidate_reason=range_engine_meta.get("short_candidate_reason"), long_validation_reason=range_engine_meta.get("long_validation_reason"), short_validation_reason=range_engine_meta.get("short_validation_reason"), allow_shorts=range_engine_meta.get("allow_shorts"), adx_h=adx_h, drift=drift)

            liquidity_signal, liquidity_meta = self._check_btc_liquidity_reversal(symbol=symbol, market_state=market_state, df=df, recent=recent, range_high=range_high, range_low=range_low, atr_ltf=atr_ltf, adx_h=adx_h, drift=drift, bar_index=bar_index)
            if liquidity_signal is not None:
                self._last_btc_liquidity_reversal_bar_index = bar_index
                return self._set_signal(liquidity_signal, trade_type="liquidity_reversal", risk_multiplier=float(cfg.get_symbol_param_float(symbol, "BTC_LIQUIDITY_REVERSAL_RISK_MULT", float(getattr(cfg, "BTC_LIQUIDITY_REVERSAL_RISK_MULT", 0.42)))), market_state=market_state, regime=regime, liquidity_meta=liquidity_meta, side="long" if liquidity_signal == "buy" else "short")

            stage10v2_mr_signal, stage10v2_mr_meta = self._check_stage10v2_basic_btc_mr(symbol=symbol, market_state=market_state, recent=recent, candle=last, atr_ltf=atr_ltf, adx_h=adx_h, drift=drift, bar_index=bar_index)
            if stage10v2_mr_signal is not None:
                self._last_btc_stage10v2_mr_bar_index = bar_index
                return self._set_signal(stage10v2_mr_signal, trade_type="mean_reversion", risk_multiplier=float(cfg.get_symbol_param_float(symbol, "BTC_STAGE10V2_BASIC_MR_RISK_MULT", float(getattr(cfg, "BTC_STAGE10V2_BASIC_MR_RISK_MULT", 0.48)))), market_state=market_state, regime=regime, mean_reversion_meta=stage10v2_mr_meta, side="long")

            v22_signal, v22_trade_type, v22_risk_mult, v22_meta = run_v22_nontrend_engine(cfg=cfg, symbol=symbol, market_state=market_state, regime=regime, recent=recent, candle=last, atr_ltf=atr_ltf, adx_h=adx_h, drift=drift)
            if v22_signal is not None:
                logger.debug("[MTF] V22 %s %s state=%s meta=%s", str(v22_trade_type).upper(), v22_signal.upper(), market_state, v22_meta)
                return self._set_signal(v22_signal, trade_type=v22_trade_type, risk_multiplier=v22_risk_mult, market_state=market_state, regime=regime, v22_meta=v22_meta, side="long" if v22_signal == "buy" else "short")

            mr_signal, mr_meta = check_v52_mean_reversion_entry(cfg=cfg, symbol=symbol, market_state=market_state, recent=recent, candle=last, atr_ltf=atr_ltf)
            if mr_signal is not None:
                if symbol == "ETHUSDT" and mr_signal == "sell" and bool(getattr(cfg, "V54_ETH_DISABLE_SHORTS", True)):
                    mr_signal = None
                else:
                    logger.debug("[MTF] MR %s state=%s meta=%s", mr_signal.upper(), market_state, mr_meta)
                    return self._set_signal(mr_signal, trade_type="mean_reversion", risk_multiplier=self._mr_risk_multiplier(symbol), market_state=market_state, regime=regime, mean_reversion_meta=mr_meta, side="long" if mr_signal == "buy" else "short")

            if symbol == "ETHUSDT" and bool(getattr(cfg, "V54_ETH_MR_ONLY", True)):
                return self._set_signal(None)

            if market_state in {"range", "transition"} and self._symbol_flag(symbol, "ENABLE_FAKEOUT", False):
                fake_long_ok, fake_long_meta = check_fakeout_reversal_entry(symbol=symbol, df=df, recent=recent, side="long", range_high=range_high, range_low=range_low, atr_ltf=atr_ltf, adx_h=adx_h)
                if fake_long_ok:
                    v86_long_ok, v86_long_flags = self._apply_v86_inline_long_suppression(symbol=symbol, trade_type="fakeout", market_state=market_state, regime=regime, btc_meta=btc_meta if isinstance(btc_meta, dict) else {}, rs_meta={}, trend_quality_meta={}, regime_gate_meta={}, volume_meta={}, adx_h=adx_h, drift=drift, strong_setup=False)
                    if not v86_long_ok:
                        logger.debug("[MTF] skip BUY fakeout by v86 inline long suppression: %s", v86_long_flags)
                    else:
                        return self._set_signal("buy", trade_type="fakeout", risk_multiplier=float(cfg.get_symbol_param_float(symbol, "RISK_MULTIPLIER_FAKEOUT", float(getattr(cfg, "RISK_MULTIPLIER_FAKEOUT", 0.50)))), market_state=market_state, fakeout_meta=fake_long_meta, side="long", **v86_long_flags)
                fake_short_ok, fake_short_meta = check_fakeout_reversal_entry(symbol=symbol, df=df, recent=recent, side="short", range_high=range_high, range_low=range_low, atr_ltf=atr_ltf, adx_h=adx_h)
                if fake_short_ok:
                    if symbol == str(getattr(cfg, "BTC_REGIME_FILTER_SYMBOL", "BTCUSDT")) or not bool(getattr(cfg, "ALT_SHORTS_REQUIRE_STRONG_BTC_BEAR", True)):
                        btc_short_ctx_ok, btc_short_ctx_meta = self._btc_short_trade_ok(symbol=symbol, trade_type="fakeout", regime=regime, market_state=market_state, adx_h=adx_h, rsi_h=rsi_h, drift=drift)
                        if btc_short_ctx_ok:
                            v85_short_ok, v85_short_flags = self._apply_v85_inline_short_suppression(symbol=symbol, trade_type="fakeout", market_state=market_state, regime=regime, btc_meta=btc_short_ctx_meta if isinstance(btc_short_ctx_meta, dict) else {}, rs_meta={}, trend_quality_meta={}, regime_gate_meta={}, strong_setup=False)
                            if not v85_short_ok:
                                logger.debug("[MTF] skip SELL fakeout by v85 inline short suppression: %s", v85_short_flags)
                                return None
                            return self._set_signal("sell", trade_type="fakeout", risk_multiplier=float(cfg.get_symbol_param_float(symbol, "RISK_MULTIPLIER_FAKEOUT", float(getattr(cfg, "RISK_MULTIPLIER_FAKEOUT", 0.50)))), market_state=market_state, fakeout_meta=fake_short_meta, btc_short_ctx=btc_short_ctx_meta, side="short", **v85_short_flags)
                    btc_short_ok, btc_short_meta = self._check_btc_regime_filter(df, symbol=symbol, side="short")
                    btc_short_ctx_ok, btc_short_ctx_meta = self._btc_short_trade_ok(symbol=symbol, trade_type="fakeout", regime=regime, market_state=market_state, adx_h=adx_h, rsi_h=rsi_h, drift=drift, btc_score=float(btc_short_meta.get("score", 0.0)))
                    if btc_short_ok and btc_short_ctx_ok:
                        v85_short_ok, v85_short_flags = self._apply_v85_inline_short_suppression(symbol=symbol, trade_type="fakeout", market_state=market_state, regime=regime, btc_meta=btc_short_meta if isinstance(btc_short_meta, dict) else {}, rs_meta={}, trend_quality_meta={}, regime_gate_meta={}, strong_setup=False)
                        if not v85_short_ok:
                            logger.debug("[MTF] skip SELL fakeout by v85 inline short suppression: %s", v85_short_flags)
                            return None
                        return self._set_signal("sell", trade_type="fakeout", risk_multiplier=float(cfg.get_symbol_param_float(symbol, "RISK_MULTIPLIER_FAKEOUT", float(getattr(cfg, "RISK_MULTIPLIER_FAKEOUT", 0.50)))), market_state=market_state, fakeout_meta=fake_short_meta, btc_meta=btc_short_meta, btc_short_ctx=btc_short_ctx_meta, side="short", **v85_short_flags)

            if market_state == "range":
                disable_legacy_btc_range = bool(getattr(cfg, "BTC_RANGE_ENGINE_V4_DISABLE_LEGACY_BTC_RANGE_FALLBACK", False))
                if is_btc_symbol and disable_legacy_btc_range:
                    self._btc_range_debug("legacy_range_skipped", symbol=symbol, market_state=market_state, reason="BTC_RANGE_ENGINE_V4_DISABLE_LEGACY_BTC_RANGE_FALLBACK")
                else:
                    range_sig, range_meta = range_signal(symbol=symbol, df=df, recent=recent, close=close, atr_ltf=atr_ltf, adx_h=adx_h, market_meta=market_meta)
                    if range_sig is not None:
                        logger.debug("[MTF] RANGE %s state=%s meta=%s", range_sig.upper(), market_state, range_meta)
                        return self._set_signal(range_sig, trade_type="range", risk_multiplier=float(getattr(cfg, "RISK_MULTIPLIER_RANGE", 0.45)), market_state=market_state, range_meta=range_meta, side="long" if range_sig == "buy" else "short")

        # 3) LTF ATR-фильтр + RSI-фильтр (вариант B — сбалансированный)
        # ======================================================
        # Фильтруем слишком тихий рынок на M15 по ATR
        if close <= 0 or atr_ltf <= 0:
            self._alt_trace("early_return", symbol=symbol, stage="ltf_inputs", reason="non_positive_close_or_atr")
            return None
        atr_pct_ltf = atr_ltf / close
        ltf_atr_min = float(getattr(cfg, "LTF_ATR_MIN_PCT", 0.0002))
        if atr_pct_ltf < ltf_atr_min:
            self._alt_trace("early_return", symbol=symbol, stage="ltf_atr", reason="atr_below_min", atr_pct_ltf=round(atr_pct_ltf, 6), ltf_atr_min=round(ltf_atr_min, 6))
            return None

        # Дополнительный micro-noise фильтр: если волатильность очень мала и цена почти не двигается,
        # то считаем, что это локальный флэт и пропускаем сигналы.
        micro_atr_pct = float(getattr(cfg, "LTF_MICRO_ATR_PCT", 0.0015))
        slope_lookback = int(getattr(cfg, "LTF_SLOPE_LOOKBACK", 30))
        slope_min_abs = float(getattr(cfg, "LTF_SLOPE_MIN_ABS", 0.001))

        try:
            close_series_ltf = df["close"].astype(float)
            last_price_ltf = float(close_series_ltf.iloc[-1])
            prev_price_ltf = float(close_series_ltf.iloc[-slope_lookback-1]) if len(df) > slope_lookback + 1 else None
        except Exception:
            last_price_ltf = None
            prev_price_ltf = None

        if (
            last_price_ltf is not None
            and prev_price_ltf is not None
            and last_price_ltf > 0.0
        ):
            slope_abs = abs(last_price_ltf - prev_price_ltf) / last_price_ltf
        else:
            slope_abs = None

        # Volatile driftless filter: высокая ATR, но низкий наклон -> волатильная пила без направления.
        volatile_slope_factor = float(getattr(cfg, "LTF_VOLATILE_SLOPE_FACTOR", 5.0))
        if (
            slope_abs is not None
            and atr_pct_ltf > micro_atr_pct
            and slope_abs < slope_min_abs * volatile_slope_factor
        ):
            if is_alt and bool(getattr(cfg, "ALT_DISABLE_LTF_VOLATILE_DRIFTLESS_FILTER", True)):
                self._alt_trace("soft_pass", symbol=symbol, stage="ltf_noise", reason="alt_disable_volatile_driftless", atr_pct_ltf=round(atr_pct_ltf, 6), slope_abs=round(slope_abs, 6), slope_threshold=round(slope_min_abs * volatile_slope_factor, 6))
            else:
                self._alt_trace("early_return", symbol=symbol, stage="ltf_noise", reason="volatile_driftless", atr_pct_ltf=round(atr_pct_ltf, 6), slope_abs=round(slope_abs, 6), slope_threshold=round(slope_min_abs * volatile_slope_factor, 6))
                return None

        rsi_long_min = cfg.get_symbol_param_float(symbol, "MTF_RSI_LONG_MIN", float(getattr(cfg, "MTF_RSI_LONG_MIN", 50.0)))
        rsi_long_max = cfg.get_symbol_param_float(symbol, "MTF_RSI_LONG_MAX", float(getattr(cfg, "MTF_RSI_LONG_MAX", 85.0)))
        rsi_short_min = cfg.get_symbol_param_float(symbol, "MTF_RSI_SHORT_MIN", float(getattr(cfg, "MTF_RSI_SHORT_MIN", 15.0)))
        rsi_short_max = cfg.get_symbol_param_float(symbol, "MTF_RSI_SHORT_MAX", float(getattr(cfg, "MTF_RSI_SHORT_MAX", 55.0)))

        # Адаптивные RSI-диапазоны в зависимости от силы тренда (дрейфа).
        rsi_long_tighten = float(getattr(cfg, "MTF_RSI_LONG_TIGHTEN", 5.0))
        rsi_short_tighten = float(getattr(cfg, "MTF_RSI_SHORT_TIGHTEN", 5.0))

        # При слабом тренде (дрейф ближе к минимальному) ужесточаем фильтры:
        # LONG берём только при более "заряженном" RSI,
        # SHORT берём только при более "разряженном" RSI.
        if drift > drift_min_pct and drift < drift_strong_pct:
            rsi_long_min += rsi_long_tighten
            rsi_short_max -= rsi_short_tighten

        # При очень сильном тренде можно немного ослабить фильтры,
        # чтобы не пропускать хорошие пробои.
        elif drift >= drift_strong_pct:
            rsi_long_min = max(40.0, rsi_long_min - rsi_long_tighten * 0.5)
            rsi_short_max = min(60.0, rsi_short_max + rsi_short_tighten * 0.5)

        # Дополнительная адаптация RSI под силу объёмного импульса пробоя.
        # Слабый импульс -> вход требовательнее. Сильный импульс -> можно чуть смягчить.
        if not isinstance(volume_meta, dict):
            volume_meta = {}
        volume_filter_enabled = bool(getattr(cfg, "BREAKOUT_VOLUME_FILTER_ENABLED", True))
        volume_ok = bool(volume_meta) and not str(volume_meta.get("reason", "")).startswith("weak_")
        if bool(getattr(cfg, "BREAKOUT_RSI_ADAPT_BY_VOLUME_ENABLED", True)):
            weak_tighten = float(getattr(cfg, "BREAKOUT_RSI_WEAK_VOLUME_TIGHTEN", 2.5))
            strong_loosen = float(getattr(cfg, "BREAKOUT_RSI_STRONG_VOLUME_LOOSEN", 1.5))
            impulse_score = float(volume_meta.get("impulse_score", 0.0))
            strong_impulse = bool(volume_meta.get("is_strong_impulse", False))
            min_impulse_score = float(getattr(cfg, "BREAKOUT_MIN_VOLUME_IMPULSE_SCORE", 0.55))

            if impulse_score < min_impulse_score * 1.15:
                rsi_long_min += weak_tighten
                rsi_short_max -= weak_tighten
            elif strong_impulse:
                rsi_long_min = max(40.0, rsi_long_min - strong_loosen)
                rsi_short_max = min(60.0, rsi_short_max + strong_loosen)

        if self._is_alt_symbol(symbol):
            rsi_long_min = max(40.0, rsi_long_min - float(cfg.get_symbol_param_float(symbol, "ALT_RSI_LONG_MIN_LOOSEN", float(getattr(cfg, "ALT_RSI_LONG_MIN_LOOSEN", 3.0)))))
            rsi_short_max = min(60.0, rsi_short_max + float(cfg.get_symbol_param_float(symbol, "ALT_RSI_SHORT_MAX_LOOSEN", float(getattr(cfg, "ALT_RSI_SHORT_MAX_LOOSEN", 3.0)))))

        # ======================================================
        # 4) Итоговые сигналы
        # ======================================================

        breakout_quality_enabled = bool(getattr(cfg, "BREAKOUT_CANDLE_QUALITY_ENABLED", True))

        # Continuation entry: available in trend and transition states.
        continuation_states = {"trend"}
        if bool(getattr(cfg, "CONTINUATION_ALLOW_IN_TRANSITION", True)) and not (strict_alt_trade_filter and bool(getattr(cfg, "ALT_CONTINUATION_DISABLE_IN_TRANSITION", True))):
            continuation_states.add("transition")
        if is_alt and bool(getattr(cfg, "ALT_CONTINUATION_ALLOW_IN_RANGE", True)) and not strict_alt_trade_filter:
            continuation_states.add("range")

        if market_state in continuation_states or transition_state:
            if regime == "bear" and str(symbol).upper() == "BTCUSDT":
                self._v60_1_short_hit("bear_state", {"reason": f"market_state={market_state}"})
            self._alt_trace("entry_path", symbol=symbol, path="continuation_block", market_state=market_state, regime=regime)
            pullback_states = {"trend"}
            if bool(getattr(cfg, "PULLBACK_TREND_ALLOW_IN_TRANSITION", False)):
                pullback_states.add("transition")
            pullback_enabled = bool(getattr(cfg, "PULLBACK_TREND_ENABLED", False)) and symbol in set(getattr(cfg, "PULLBACK_TREND_SYMBOLS", []))
            if pullback_enabled and market_state in pullback_states:
                if regime == "bull":
                    btc_ok, btc_meta = self._check_btc_regime_filter(df, symbol=symbol, side="long")
                    pullback_ok, pullback_meta = check_pullback_trend_entry(symbol=symbol, df=df, side="long", atr_ltf=atr_ltf)
                    v43_ok, v43_meta = self._check_v43_btc_pullback_regime(symbol=symbol, side="long", df=df, close=close, market_state=market_state, adx_h=adx_h, atr_pct_h=atr_pct_h, drift=drift, pullback_meta=pullback_meta, is_addon=False)
                    v45_ok, v45_meta = self._check_v45_structural_rr(symbol=symbol, side="long", df=df, close=close, atr_ltf=atr_ltf, pullback_meta=pullback_meta)
                    v51_ok, v51_meta = self._check_v51_free_liquidity_filter(symbol=symbol, side="long", df=df, pullback_meta=pullback_meta)
                    v52_ok, v52_meta = self._check_v52_candle_microstructure(symbol=symbol, side="long", df=df, close=close, atr_ltf=atr_ltf, pullback_meta=pullback_meta)
                    if btc_ok and pullback_ok and v43_ok and v45_ok and v51_ok and v52_ok:
                        pullback_meta = {**(pullback_meta or {}), **(v45_meta or {}), **(v51_meta or {}), **(v52_meta or {})}
                        regime_gate_ok, regime_gate_meta = self._check_directional_regime_gate(symbol=symbol, side="long", trade_type="continuation", regime=regime, market_state=market_state, adx_h=adx_h, atr_pct_h=atr_pct_h, drift=drift, rsi_h=rsi_h)
                        if regime_gate_ok:
                            trend_quality_ok, trend_quality_meta = self._check_trend_strength_and_chop(symbol=symbol, df=df, recent=recent, side="long", trade_type="continuation", close=close, atr_ltf=atr_ltf, adx_h=adx_h, atr_pct_h=atr_pct_h, drift=drift)
                            if trend_quality_ok:
                                risk_mult = float(cfg.get_symbol_param_float(symbol, "PULLBACK_RISK_MULTIPLIER", float(getattr(cfg, "PULLBACK_RISK_MULTIPLIER", 0.75))))
                                if bool(getattr(cfg, "V39_BTC_SCALE_ENGINE_ENABLED", False)) and str(symbol).upper() == "BTCUSDT":
                                    pb = pullback_meta or {}
                                    base = float(getattr(cfg, "V39_BTC_PULLBACK_BASE_RISK_MULT", risk_mult))
                                    strong = float(getattr(cfg, "V39_BTC_PULLBACK_STRONG_RISK_MULT", base))
                                    elite = float(getattr(cfg, "V39_BTC_PULLBACK_ELITE_RISK_MULT", strong))
                                    max_r = float(getattr(cfg, "V39_BTC_PULLBACK_MAX_RISK_MULT", elite))
                                    pre_imp = float(pb.get("pre_impulse_atr", 0.0) or 0.0)
                                    close_pos = float(pb.get("close_pos", 0.0) or 0.0)
                                    strong_ok = adx_h >= float(getattr(cfg, "V39_BTC_PULLBACK_STRONG_ADX", 26.0)) and pre_imp >= float(getattr(cfg, "V39_BTC_PULLBACK_STRONG_PRE_IMPULSE_ATR", 1.40)) and close_pos >= float(getattr(cfg, "V39_BTC_PULLBACK_MIN_CLOSE_POS_STRONG", 0.56))
                                    elite_ok = adx_h >= float(getattr(cfg, "V39_BTC_PULLBACK_ELITE_ADX", 32.0)) and pre_imp >= float(getattr(cfg, "V39_BTC_PULLBACK_ELITE_PRE_IMPULSE_ATR", 2.20))
                                    risk_mult = min(max_r, elite if elite_ok else (strong if strong_ok else base))
                                    risk_mult *= float((pullback_meta or {}).get("v45_risk_mult", 1.0) or 1.0)
                                    pullback_meta = {**pb, **(pullback_meta or {}), "v39_scaled": True, "v39_strong_pullback": bool(strong_ok), "v39_elite_pullback": bool(elite_ok), "v39_risk_mult": risk_mult}
                                    strong_setup = bool(strong_ok or elite_ok)
                                risk_mult, v54_flags = self._apply_v54_performance_scaling(symbol=symbol, side="long", trade_type="pullback", risk_mult=risk_mult, meta=(pullback_meta or {}), adx_h=adx_h, drift=drift)
                                pullback_meta = {**(pullback_meta or {}), **(v54_flags or {})}
                                risk_mult, v55_flags = self._apply_v55_global_risk_scale(symbol=symbol, side="long", trade_type="pullback", risk_mult=risk_mult, meta=(pullback_meta or {}))
                                pullback_meta = {**(pullback_meta or {}), **(v55_flags or {})}
                                risk_mult, long_stack_ok, long_stack_flags = apply_pullback_long_risk_stack(self, symbol=symbol, risk_multiplier=risk_mult, market_state=market_state, regime=regime, btc_meta=btc_meta, volume_meta=volume_meta, trend_quality_meta=trend_quality_meta, regime_gate_meta=regime_gate_meta, adx_h=adx_h, drift=drift)
                                if not long_stack_ok:
                                    logger.debug("[MTF] skip BUY pullback by pullback long risk stack: %s", long_stack_flags)
                                else:
                                    return self._set_signal("buy", trade_type="pullback", risk_multiplier=risk_mult, market_state=market_state, pullback_meta=pullback_meta, regime_gate_meta=regime_gate_meta, trend_quality_meta=trend_quality_meta, v43_regime_meta=v43_meta, v45_struct_meta=v45_meta, v51_liquidity_meta=v51_meta, v52_microstructure_meta=v52_meta, v45_struct_stop_price=(pullback_meta or {}).get("v45_struct_stop_price"), v45_rr=(pullback_meta or {}).get("v45_rr"), side="long", strong_setup=bool(strong_setup), **long_stack_flags)
                elif regime == "bear":
                    self._v60_1_short_hit("bear_pullback_path", {"reason": "entered_bear_pullback_path"})
                    btc_ok, btc_meta = self._check_btc_regime_filter(df, symbol=symbol, side="short")
                    if btc_ok:
                        self._v60_1_short_hit("btc_ok", btc_meta if isinstance(btc_meta, dict) else {})
                    else:
                        self._v60_1_short_hit("btc_rejected", btc_meta if isinstance(btc_meta, dict) else {"reason": "btc_regime_false"})
                    pullback_ok, pullback_meta = check_pullback_trend_entry(symbol=symbol, df=df, side="short", atr_ltf=atr_ltf)
                    self._v60_1_short_hit("pullback_checked", pullback_meta if isinstance(pullback_meta, dict) else {"reason": "pullback_meta_missing"})
                    if pullback_ok:
                        self._v60_1_short_hit("pullback_ok", pullback_meta if isinstance(pullback_meta, dict) else {})
                    else:
                        self._v60_1_short_hit("pullback_rejected", pullback_meta if isinstance(pullback_meta, dict) else {"reason": "pullback_false"})
                    btc_short_ok, btc_short_meta = self._btc_short_trade_ok(symbol=symbol, trade_type="pullback", regime=regime, market_state=market_state, adx_h=adx_h, rsi_h=rsi_h, drift=drift, btc_score=float(btc_meta.get("score", 0.0)))
                    if btc_short_ok:
                        self._v60_1_short_hit("btc_short_ok", btc_short_meta if isinstance(btc_short_meta, dict) else {})
                    else:
                        self._v60_1_short_hit("btc_short_rejected", btc_short_meta if isinstance(btc_short_meta, dict) else {"reason": "btc_short_context_false"})
                    v43_ok, v43_meta = self._check_v43_btc_pullback_regime(symbol=symbol, side="short", df=df, close=close, market_state=market_state, adx_h=adx_h, atr_pct_h=atr_pct_h, drift=drift, pullback_meta=pullback_meta, is_addon=False)
                    if v43_ok:
                        self._v60_1_short_hit("v43_ok", v43_meta if isinstance(v43_meta, dict) else {})
                    else:
                        self._v60_1_short_hit("v43_rejected", v43_meta if isinstance(v43_meta, dict) else {"reason": "v43_false"})
                    v60_ok, v60_meta = self._check_v60_short_microstructure(symbol=symbol, side="short", df=df, close=close, atr_ltf=atr_ltf, pullback_meta=pullback_meta)
                    v60_real_enable = bool(getattr(cfg, "V60_2_REAL_SHORT_ENABLE", False)) and str(symbol).upper() == "BTCUSDT" and bool(v60_ok)
                    if v60_real_enable and not btc_short_ok and bool(getattr(cfg, "V60_2_BYPASS_LEGACY_BTC_SHORT_GATE", True)):
                        btc_short_ok = True
                        btc_short_meta = {**(btc_short_meta if isinstance(btc_short_meta, dict) else {}), "reason": "v60_2_legacy_btc_short_gate_bypass", "v60_2_bypass": True}
                        self._v60_1_short_hit("btc_short_ok", btc_short_meta)
                    if btc_ok and pullback_ok and btc_short_ok and v43_ok and v60_ok:
                        if v60_real_enable and bool(getattr(cfg, "V60_2_BYPASS_LEGACY_DIRECTIONAL_GATES", True)):
                            regime_gate_ok, regime_gate_meta = True, {"reason": "v60_2_directional_gate_bypass", "v60_2_bypass": True}
                            trend_quality_ok, trend_quality_meta = True, {"reason": "v60_2_trend_quality_bypass", "v60_2_bypass": True}
                            self._v60_1_short_hit("regime_gate_ok", regime_gate_meta)
                            self._v60_1_short_hit("trend_quality_ok", trend_quality_meta)
                        else:
                            regime_gate_ok, regime_gate_meta = self._check_directional_regime_gate(symbol=symbol, side="short", trade_type="pullback", regime=regime, market_state=market_state, adx_h=adx_h, atr_pct_h=atr_pct_h, drift=drift, rsi_h=rsi_h)
                            if regime_gate_ok:
                                self._v60_1_short_hit("regime_gate_ok", regime_gate_meta if isinstance(regime_gate_meta, dict) else {})
                                trend_quality_ok, trend_quality_meta = self._check_trend_strength_and_chop(symbol=symbol, df=df, recent=recent, side="short", trade_type="pullback", close=close, atr_ltf=atr_ltf, adx_h=adx_h, atr_pct_h=atr_pct_h, drift=drift)
                                if trend_quality_ok:
                                    self._v60_1_short_hit("trend_quality_ok", trend_quality_meta if isinstance(trend_quality_meta, dict) else {})
                                else:
                                    self._v60_1_short_hit("trend_quality_rejected", trend_quality_meta if isinstance(trend_quality_meta, dict) else {"reason": "trend_quality_false"})
                            else:
                                self._v60_1_short_hit("regime_gate_rejected", regime_gate_meta if isinstance(regime_gate_meta, dict) else {"reason": "regime_gate_false"})
                        if regime_gate_ok and trend_quality_ok:
                            risk_mult = float(cfg.get_symbol_param_float(symbol, "PULLBACK_RISK_MULTIPLIER", float(getattr(cfg, "PULLBACK_RISK_MULTIPLIER", 0.75))))
                            if v60_real_enable and bool(getattr(cfg, "V60_2_BYPASS_LEGACY_SHORT_RISK_STACK", True)):
                                short_stack_ok = True
                                short_stack_flags = {"v60_2_short_stack_bypass": True, "v60_2_short_stack_reason": "approved_v60_short"}
                            else:
                                risk_mult, short_stack_ok, short_stack_flags = apply_standard_short_risk_stack(self, symbol=symbol, trade_type="pullback", risk_multiplier=risk_mult, market_state=market_state, regime=regime, btc_meta=btc_meta, alt_meta={}, rs_meta={}, volume_meta=volume_meta, trend_quality_meta=trend_quality_meta, regime_gate_meta=regime_gate_meta, adx_h=adx_h, drift=drift, strong_setup=False)
                            if not short_stack_ok:
                                self._v60_1_short_hit("short_stack_rejected", short_stack_flags if isinstance(short_stack_flags, dict) else {"reason": "short_stack_false"})
                                logger.debug("[MTF] skip SELL pullback by standard short risk stack: %s", short_stack_flags)
                                return None
                            self._v60_1_short_hit("short_stack_ok", short_stack_flags if isinstance(short_stack_flags, dict) else {})
                            risk_mult *= float(getattr(cfg, "V60_SHORT_RISK_MULT", 0.92)) if bool(getattr(cfg, "V60_SHORT_ENGINE_ENABLED", False)) else 1.0
                            self._v60_1_short_hit("signal_returned", {"reason": "v60_2_short_signal_returned" if v60_real_enable else "v60_short_signal_returned"})
                            return self._set_signal("sell", trade_type="pullback", risk_multiplier=risk_mult, market_state=market_state, pullback_meta=pullback_meta, btc_short_ctx=btc_short_meta, regime_gate_meta=regime_gate_meta, trend_quality_meta=trend_quality_meta, v43_regime_meta=v43_meta, v60_short_meta=v60_meta, side="short", allow_btc_range_short_bypass=True, **short_stack_flags)
            if bool(getattr(cfg, "V37_BTC_PULLBACK_ONLY_ENABLED", False)) and symbol in set(getattr(cfg, "V37_BTC_PULLBACK_ONLY_SYMBOLS", ["BTCUSDT"]) or ["BTCUSDT"]):
                logger.debug("[MTF] v37 BTC pullback-only: skip continuation path after pullback check")
                return None

            if regime == "bull":
                btc_ok, btc_meta = self._check_btc_regime_filter(df, symbol=symbol, side="long")
                alt_ok, alt_meta = self._calc_alt_quality_score(symbol=symbol, recent=recent, atr_ltf=atr_ltf, side="long")
                rs_ok, rs_meta = self._check_relative_strength_filter(df=df, symbol=symbol, side="long")
                cont_comp_ok, cont_comp_meta = (False, {"disabled": True})
                if self._symbol_flag(symbol, "ENABLE_CONT_COMP", False):
                    cont_comp_ok, cont_comp_meta = check_continuation_compression_entry(symbol=symbol, df=df, side="long", atr_ltf=atr_ltf)
                alt_ok, rs_ok, alt_meta, rs_meta = self._relax_alt_filters(symbol, "long", alt_ok, alt_meta, rs_ok, rs_meta)
                if btc_ok and alt_ok and rs_ok and cont_comp_ok:
                    upgrade_ok, upgrade_meta = self._alt_upgrade_gate(symbol=symbol, side="long", trade_type="cont_compression", alt_meta=alt_meta, rs_meta=rs_meta, btc_meta=btc_meta, adx_h=adx_h, drift=drift, volume_meta=volume_meta)
                    if not upgrade_ok:
                        logger.debug("[MTF] skip BUY cont_compression by alt v1 upgrade gate: %s", upgrade_meta)
                    else:
                        regime_gate_ok = False
                        regime_gate_meta = {"not_evaluated": True}
                        trend_quality_ok = False
                        trend_quality_meta = {"not_evaluated": True}
                        regime_gate_ok, regime_gate_meta = self._check_directional_regime_gate(symbol=symbol, side="long", trade_type="cont_compression", regime=regime, market_state=market_state, adx_h=adx_h, atr_pct_h=atr_pct_h, drift=drift, rsi_h=rsi_h)
                        if regime_gate_ok:
                            trend_quality_ok, trend_quality_meta = self._check_trend_strength_and_chop(symbol=symbol, df=df, recent=recent, side="long", trade_type="cont_compression", close=close, atr_ltf=atr_ltf, adx_h=adx_h, atr_pct_h=atr_pct_h, drift=drift)
                            if trend_quality_ok:
                                risk_mult = float(cfg.get_symbol_param_float(symbol, "RISK_MULTIPLIER_CONT_COMP", float(getattr(cfg, "RISK_MULTIPLIER_CONT_COMP", 0.75))))
                                strong_setup = self._alt_strong_setup(symbol, adx_h, drift, volume_meta, rs_meta, side="long")
                                if strong_setup:
                                    risk_mult *= float(cfg.get_symbol_param_float(symbol, "ALT_STRONG_SETUP_RISK_MULT", float(getattr(cfg, "ALT_STRONG_SETUP_RISK_MULT", 1.30))))
                                risk_mult, long_stack_flags = apply_standard_long_risk_stack(self, symbol=symbol, trade_type="cont_compression", risk_multiplier=risk_mult, market_state=market_state, regime=regime, btc_meta=btc_meta, alt_meta=alt_meta, rs_meta=rs_meta, volume_meta=volume_meta, trend_quality_meta=trend_quality_meta, regime_gate_meta=regime_gate_meta, adx_h=adx_h, drift=drift, strong_setup=strong_setup)
                                v86_long_ok, v86_long_flags = self._apply_v86_inline_long_suppression(symbol=symbol, trade_type="cont_compression", market_state=market_state, regime=regime, btc_meta=btc_meta, rs_meta=rs_meta, trend_quality_meta=trend_quality_meta, regime_gate_meta=regime_gate_meta, volume_meta=volume_meta, adx_h=adx_h, drift=drift, strong_setup=strong_setup)
                                if not v86_long_ok:
                                    logger.debug("[MTF] skip BUY cont_compression by v86 inline long suppression: %s", v86_long_flags)
                                else:
                                    return self._set_signal("buy", trade_type="cont_compression", risk_multiplier=risk_mult, market_state=market_state, cont_comp_meta=cont_comp_meta, regime_gate_meta=regime_gate_meta, trend_quality_meta=trend_quality_meta, side="long", strong_setup=strong_setup, alt_upgrade_meta=upgrade_meta, **long_stack_flags, **v86_long_flags)
                            logger.debug("[MTF] skip BUY cont_compression by trend quality/chop: %s", trend_quality_meta)
                        else:
                            logger.debug("[MTF] skip BUY cont_compression by directional regime gate: %s", regime_gate_meta)
                cont_ok, cont_meta = check_continuation_entry(symbol=symbol, df=df, side="long", atr_ltf=atr_ltf)
                alt_ok, rs_ok, alt_meta, rs_meta = self._relax_alt_filters(symbol, "long", alt_ok, alt_meta, rs_ok, rs_meta)
                if btc_ok and alt_ok and rs_ok and cont_ok:
                    upgrade_ok, upgrade_meta = self._alt_upgrade_gate(symbol=symbol, side="long", trade_type="continuation", alt_meta=alt_meta, rs_meta=rs_meta, btc_meta=btc_meta, adx_h=adx_h, drift=drift, volume_meta=volume_meta)
                    if not upgrade_ok:
                        logger.debug("[MTF] skip BUY continuation by alt v1 upgrade gate: %s", upgrade_meta)
                    else:
                        regime_gate_ok = False
                        regime_gate_meta = {"not_evaluated": True}
                        trend_quality_ok = False
                        trend_quality_meta = {"not_evaluated": True}
                        regime_gate_ok, regime_gate_meta = self._check_directional_regime_gate(symbol=symbol, side="long", trade_type="continuation", regime=regime, market_state=market_state, adx_h=adx_h, atr_pct_h=atr_pct_h, drift=drift, rsi_h=rsi_h)
                        if regime_gate_ok:
                            trend_quality_ok, trend_quality_meta = self._check_trend_strength_and_chop(symbol=symbol, df=df, recent=recent, side="long", trade_type="continuation", close=close, atr_ltf=atr_ltf, adx_h=adx_h, atr_pct_h=atr_pct_h, drift=drift)
                            if trend_quality_ok:
                                strong_setup = self._alt_strong_setup(symbol, adx_h, drift, volume_meta, rs_meta, side="long")
                                alt_regime_ok, alt_regime_meta = alt_regime_filter_helper(self, symbol=symbol, side="long", trade_type="continuation", market_state=market_state, alt_meta=alt_meta, rs_meta=rs_meta, btc_meta=btc_meta, adx_h=adx_h, drift=drift, volume_meta=volume_meta, strong_setup=strong_setup)
                                if not alt_regime_ok:
                                    logger.debug("[MTF] skip BUY continuation by alt regime filter: %s", alt_regime_meta)
                                else:
                                    logger.debug("[MTF] BUY continuation: state=%s rsi=%.2f alt_score=%.3f btc_score=%.3f rs_ratio=%.3f cont=%s", market_state, rsi_ltf, float(alt_meta.get("score", 1.0)), float(btc_meta.get("score", 1.0)), float(rs_meta.get("ratio", 1.0)), cont_meta)
                                    risk_mult = float(cfg.get_symbol_param_float(symbol, "RISK_MULTIPLIER_CONTINUATION", float(getattr(cfg, "RISK_MULTIPLIER_CONTINUATION", 0.65))))
                                    if strong_setup:
                                        risk_mult *= float(cfg.get_symbol_param_float(symbol, "ALT_STRONG_SETUP_RISK_MULT", float(getattr(cfg, "ALT_STRONG_SETUP_RISK_MULT", 1.30))))
                                    risk_mult, long_stack_flags = apply_standard_long_risk_stack(self, symbol=symbol, trade_type="continuation", risk_multiplier=risk_mult, market_state=market_state, regime=regime, btc_meta=btc_meta, alt_meta=alt_meta, rs_meta=rs_meta, volume_meta=volume_meta, trend_quality_meta=trend_quality_meta, regime_gate_meta=regime_gate_meta, adx_h=adx_h, drift=drift, strong_setup=strong_setup)
                                    v86_long_ok, v86_long_flags = self._apply_v86_inline_long_suppression(symbol=symbol, trade_type="continuation", market_state=market_state, regime=regime, btc_meta=btc_meta, rs_meta=rs_meta, trend_quality_meta=trend_quality_meta, regime_gate_meta=regime_gate_meta, volume_meta=volume_meta, adx_h=adx_h, drift=drift, strong_setup=strong_setup)
                                    if not v86_long_ok:
                                        logger.debug("[MTF] skip BUY continuation by v86 inline long suppression: %s", v86_long_flags)
                                    else:
                                        return self._set_signal("buy", trade_type="continuation", risk_multiplier=risk_mult, market_state=market_state, cont_meta=cont_meta, regime_gate_meta=regime_gate_meta, trend_quality_meta=trend_quality_meta, side="long", strong_setup=strong_setup, alt_upgrade_meta=upgrade_meta, **long_stack_flags, **v86_long_flags)
                            logger.debug("[MTF] skip BUY continuation by trend quality/chop: %s", trend_quality_meta)
                        else:
                            logger.debug("[MTF] skip BUY continuation by directional regime gate: %s", regime_gate_meta)
            elif regime == "bear":
                btc_ok, btc_meta = self._check_btc_regime_filter(df, symbol=symbol, side="short")
                alt_ok, alt_meta = self._calc_alt_quality_score(symbol=symbol, recent=recent, atr_ltf=atr_ltf, side="short")
                rs_ok, rs_meta = self._check_relative_strength_filter(df=df, symbol=symbol, side="short")
                allow_short = True
                if symbol != str(getattr(cfg, "BTC_REGIME_FILTER_SYMBOL", "BTCUSDT")) and bool(getattr(cfg, "ALT_SHORTS_REQUIRE_STRONG_BTC_BEAR", True)):
                    btc_short_min = float(getattr(cfg, "BTC_REGIME_MIN_SCORE_SHORT", max(float(getattr(cfg, "BTC_REGIME_MIN_SCORE", 0.95)), 1.05)))
                    allow_short = float(btc_meta.get("score", 0.0)) >= btc_short_min
                cont_comp_ok, cont_comp_meta = (False, {"disabled": True})
                if self._symbol_flag(symbol, "ENABLE_CONT_COMP", False):
                    cont_comp_ok, cont_comp_meta = check_continuation_compression_entry(symbol=symbol, df=df, side="short", atr_ltf=atr_ltf)
                btc_short_ctx_ok, btc_short_ctx_meta = self._btc_short_trade_ok(symbol=symbol, trade_type="cont_compression", regime=regime, market_state=market_state, adx_h=adx_h, rsi_h=rsi_h, drift=drift, btc_score=float(btc_meta.get("score", 0.0)))
                alt_ok, rs_ok, alt_meta, rs_meta = self._relax_alt_filters(symbol, "short", alt_ok, alt_meta, rs_ok, rs_meta)
                if btc_ok and alt_ok and rs_ok and cont_comp_ok and allow_short and btc_short_ctx_ok:
                    upgrade_ok, upgrade_meta = self._alt_upgrade_gate(symbol=symbol, side="short", trade_type="cont_compression", alt_meta=alt_meta, rs_meta=rs_meta, btc_meta=btc_meta, adx_h=adx_h, drift=drift, volume_meta=volume_meta)
                    if not upgrade_ok:
                        logger.debug("[MTF] skip SELL cont_compression by alt v1 upgrade gate: %s", upgrade_meta)
                    else:
                        regime_gate_ok = False
                        regime_gate_meta = {"not_evaluated": True}
                        trend_quality_ok = False
                        trend_quality_meta = {"not_evaluated": True}
                        regime_gate_ok, regime_gate_meta = self._check_directional_regime_gate(symbol=symbol, side="short", trade_type="cont_compression", regime=regime, market_state=market_state, adx_h=adx_h, atr_pct_h=atr_pct_h, drift=drift, rsi_h=rsi_h)
                        if regime_gate_ok:
                            trend_quality_ok, trend_quality_meta = self._check_trend_strength_and_chop(symbol=symbol, df=df, recent=recent, side="short", trade_type="cont_compression", close=close, atr_ltf=atr_ltf, adx_h=adx_h, atr_pct_h=atr_pct_h, drift=drift)
                            if trend_quality_ok:
                                risk_mult = float(cfg.get_symbol_param_float(symbol, "RISK_MULTIPLIER_CONT_COMP", float(getattr(cfg, "RISK_MULTIPLIER_CONT_COMP", 0.75))))
                                strong_setup = self._alt_strong_setup(symbol, adx_h, drift, volume_meta, rs_meta, side="short")
                                if strong_setup:
                                    risk_mult *= float(cfg.get_symbol_param_float(symbol, "ALT_STRONG_SETUP_RISK_MULT", float(getattr(cfg, "ALT_STRONG_SETUP_RISK_MULT", 1.30))))
                                risk_mult, short_stack_ok, short_stack_flags = apply_standard_short_risk_stack(self, symbol=symbol, trade_type="cont_compression", risk_multiplier=risk_mult, market_state=market_state, regime=regime, btc_meta=btc_meta, alt_meta=alt_meta, rs_meta=rs_meta, volume_meta=volume_meta, trend_quality_meta=trend_quality_meta, regime_gate_meta=regime_gate_meta, adx_h=adx_h, drift=drift, strong_setup=strong_setup)
                                if not short_stack_ok:
                                    logger.debug("[MTF] skip SELL cont_compression by standard short risk stack: %s", short_stack_flags)
                                    return None
                                return self._set_signal("sell", trade_type="cont_compression", risk_multiplier=risk_mult, market_state=market_state, cont_comp_meta=cont_comp_meta, btc_short_ctx=btc_short_ctx_meta, regime_gate_meta=regime_gate_meta, trend_quality_meta=trend_quality_meta, side="short", strong_setup=strong_setup, alt_upgrade_meta=upgrade_meta, **short_stack_flags)
                            logger.debug("[MTF] skip SELL cont_compression by trend quality/chop: %s", trend_quality_meta)
                        else:
                            logger.debug("[MTF] skip SELL cont_compression by directional regime gate: %s", regime_gate_meta)
                cont_ok, cont_meta = check_continuation_entry(symbol=symbol, df=df, side="short", atr_ltf=atr_ltf)
                btc_short_cont_ok, btc_short_cont_meta = self._btc_short_trade_ok(symbol=symbol, trade_type="continuation", regime=regime, market_state=market_state, adx_h=adx_h, rsi_h=rsi_h, drift=drift, btc_score=float(btc_meta.get("score", 0.0)))
                alt_ok, rs_ok, alt_meta, rs_meta = self._relax_alt_filters(symbol, "short", alt_ok, alt_meta, rs_ok, rs_meta)
                if btc_ok and alt_ok and rs_ok and cont_ok and allow_short and btc_short_cont_ok:
                    upgrade_ok, upgrade_meta = self._alt_upgrade_gate(symbol=symbol, side="short", trade_type="continuation", alt_meta=alt_meta, rs_meta=rs_meta, btc_meta=btc_meta, adx_h=adx_h, drift=drift, volume_meta=volume_meta)
                    if not upgrade_ok:
                        logger.debug("[MTF] skip SELL continuation by alt v1 upgrade gate: %s", upgrade_meta)
                    else:
                        regime_gate_ok = False
                        regime_gate_meta = {"not_evaluated": True}
                        trend_quality_ok = False
                        trend_quality_meta = {"not_evaluated": True}
                        regime_gate_ok, regime_gate_meta = self._check_directional_regime_gate(symbol=symbol, side="short", trade_type="continuation", regime=regime, market_state=market_state, adx_h=adx_h, atr_pct_h=atr_pct_h, drift=drift, rsi_h=rsi_h)
                        if regime_gate_ok:
                            trend_quality_ok, trend_quality_meta = self._check_trend_strength_and_chop(symbol=symbol, df=df, recent=recent, side="short", trade_type="continuation", close=close, atr_ltf=atr_ltf, adx_h=adx_h, atr_pct_h=atr_pct_h, drift=drift)
                            if trend_quality_ok:
                                strong_setup = self._alt_strong_setup(symbol, adx_h, drift, volume_meta, rs_meta, side="short")
                                alt_regime_ok, alt_regime_meta = alt_regime_filter_helper(self, symbol=symbol, side="short", trade_type="continuation", market_state=market_state, alt_meta=alt_meta, rs_meta=rs_meta, btc_meta=btc_meta, adx_h=adx_h, drift=drift, volume_meta=volume_meta, strong_setup=strong_setup)
                                if not alt_regime_ok:
                                    logger.debug("[MTF] skip SELL continuation by alt regime filter: %s", alt_regime_meta)
                                else:
                                    logger.debug("[MTF] SELL continuation: state=%s rsi=%.2f alt_score=%.3f btc_score=%.3f rs_ratio=%.3f cont=%s", market_state, rsi_ltf, float(alt_meta.get("score", 1.0)), float(btc_meta.get("score", 1.0)), float(rs_meta.get("ratio", 1.0)), cont_meta)
                                    risk_mult = float(cfg.get_symbol_param_float(symbol, "RISK_MULTIPLIER_CONTINUATION", float(getattr(cfg, "RISK_MULTIPLIER_CONTINUATION", 0.65))))
                                    if strong_setup:
                                        risk_mult *= float(cfg.get_symbol_param_float(symbol, "ALT_STRONG_SETUP_RISK_MULT", float(getattr(cfg, "ALT_STRONG_SETUP_RISK_MULT", 1.30))))
                                    risk_mult, short_stack_ok, short_stack_flags = apply_standard_short_risk_stack(self, symbol=symbol, trade_type="continuation", risk_multiplier=risk_mult, market_state=market_state, regime=regime, btc_meta=btc_meta, alt_meta=alt_meta, rs_meta=rs_meta, volume_meta=volume_meta, trend_quality_meta=trend_quality_meta, regime_gate_meta=regime_gate_meta, adx_h=adx_h, drift=drift, strong_setup=strong_setup)
                                    if not short_stack_ok:
                                        logger.debug("[MTF] skip SELL continuation by standard short risk stack: %s", short_stack_flags)
                                        return None
                                    return self._set_signal("sell", trade_type="continuation", risk_multiplier=risk_mult, market_state=market_state, cont_meta=cont_meta, btc_short_ctx=btc_short_cont_meta, regime_gate_meta=regime_gate_meta, trend_quality_meta=trend_quality_meta, side="short", strong_setup=strong_setup, alt_upgrade_meta=upgrade_meta, **short_stack_flags)
                            logger.debug("[MTF] skip SELL continuation by trend quality/chop: %s", trend_quality_meta)
                        else:
                            logger.debug("[MTF] skip SELL continuation by directional regime gate: %s", regime_gate_meta)

        if market_state != "trend":
            if is_alt and market_state in {"transition", "range"} and bool(getattr(cfg, "ALT_CONTINUATION_ALLOW_IN_RANGE", True)):
                self._alt_trace("soft_pass", symbol=symbol, market_state=market_state, regime=regime, reason="alt_allow_not_trend_after_continuation")
            else:
                self._alt_trace("signal_fallthrough", symbol=symbol, market_state=market_state, regime=regime, reason="not_trend_after_continuation")
                return None

        if volume_filter_enabled and not volume_ok and not bool(getattr(cfg, "BREAKOUT_ALLOW_WITHOUT_VOLUME_IF_CONTINUATION_ONLY", False)):
            if is_alt and bool(getattr(cfg, "ALT_ALLOW_WEAK_BREAKOUT_VOLUME", True)):
                self._alt_trace("soft_pass", symbol=symbol, stage="volume_filter", reason="alt_allow_weak_breakout_volume", impulse_score=round(float(volume_meta.get("impulse_score",0.0) or 0.0), 6))
            else:
                logger.debug("[MTF] skip weak breakout volume/momentum: %s", volume_meta)
                self._alt_trace("early_return", symbol=symbol, stage="volume_filter", reason="weak_breakout_volume", impulse_score=round(float(volume_meta.get("impulse_score",0.0) or 0.0), 6))
                return None

        alt_entry_tol = float(getattr(cfg, "ALT_ENTRY_TRIGGER_TOLERANCE_PCT", 0.0035)) if is_alt else 0.0
        alt_rsi_pad = float(getattr(cfg, "ALT_ENTRY_RSI_PAD", 6.0)) if is_alt else 0.0
        long_entry_hit = close > long_trigger
        short_entry_hit = close < short_trigger
        alt_near_long = bool(is_alt and bool(getattr(cfg, "ALT_NEAR_TRIGGER_ALLOW", True)) and regime == "bull" and close >= long_trigger * (1.0 - alt_entry_tol))
        alt_near_short = bool(is_alt and bool(getattr(cfg, "ALT_NEAR_TRIGGER_ALLOW", True)) and regime == "bear" and close <= short_trigger * (1.0 + alt_entry_tol))
        long_rsi_ok = (rsi_long_min <= rsi_ltf <= rsi_long_max) or bool(is_alt and (rsi_long_min - alt_rsi_pad) <= rsi_ltf <= (rsi_long_max + alt_rsi_pad))
        short_rsi_ok = (rsi_short_min <= rsi_ltf <= rsi_short_max) or bool(is_alt and (rsi_short_min - alt_rsi_pad) <= rsi_ltf <= (rsi_short_max + alt_rsi_pad))

        # LONG: H1 bull-тренд + подтверждённое закрытие M15 выше диапазона
        if regime == "bull" and (long_entry_hit or alt_near_long) and long_rsi_ok:
            if alt_near_long and not long_entry_hit:
                self._alt_trace("soft_pass", symbol=symbol, stage="entry_trigger", reason="alt_near_long_trigger", close=round(close,6), trigger=round(long_trigger,6), tolerance=round(alt_entry_tol,6))
            self._alt_trace("entry_path", symbol=symbol, path="impulse_long_candidate", close=round(close,6), trigger=round(long_trigger,6), rsi_ltf=round(rsi_ltf,4))
            btc_ok, btc_meta = self._check_btc_regime_filter(df, symbol=symbol, side="long")
            if not btc_ok:
                logger.debug("[MTF] skip BUY by BTC regime filter: %s", btc_meta)
                return None
            alt_ok, alt_meta = self._calc_alt_quality_score(symbol=symbol, recent=recent, atr_ltf=atr_ltf, side="long")
            if not alt_ok:
                logger.debug("[MTF] skip BUY by alt quality: %s", alt_meta)
                return None
            confirm_ok, confirm_meta = check_breakout_confirmation(
                symbol=symbol, df=df, side="long", trigger=long_trigger, range_high=range_high, range_low=range_low, atr_ltf=atr_ltf
            )
            if not confirm_ok:
                if is_alt and alt_near_long and bool(getattr(cfg, "ALT_NEAR_TRIGGER_ALLOW", True)):
                    self._alt_trace("soft_pass", symbol=symbol, stage="breakout_confirmation", reason="alt_near_long_confirmation_bypass")
                    confirm_ok = True
                else:
                    logger.debug("[MTF] skip BUY by breakout confirmation: %s", confirm_meta)
                    return None
            rs_ok, rs_meta = self._check_relative_strength_filter(df=df, symbol=symbol, side="long")
            alt_ok, rs_ok, alt_meta, rs_meta = self._relax_alt_filters(symbol, "long", alt_ok, alt_meta, rs_ok, rs_meta)
            if not rs_ok:
                logger.debug("[MTF] skip BUY by relative strength: %s", rs_meta)
                return None
            impulse_ok, impulse_meta = check_impulse_breakout(symbol=symbol, recent=recent, candle=last, side="long", trigger=long_trigger, atr_ltf=atr_ltf)
            if not impulse_ok:
                if is_alt and alt_near_long and bool(getattr(cfg, "ALT_NEAR_TRIGGER_ALLOW", True)):
                    self._alt_trace("soft_pass", symbol=symbol, stage="impulse_breakout", reason="alt_near_long_impulse_bypass")
                    impulse_ok = True
                    impulse_meta = {**(impulse_meta or {}), "soft_pass": True, "near_trigger": True}
                else:
                    logger.debug("[MTF] skip BUY by impulse breakout: %s", impulse_meta)
                    return None
            if breakout_quality_enabled:
                quality_ok, quality_meta = self._calc_breakout_candle_quality(last, atr_ltf, side="long")
                if not quality_ok:
                    logger.debug("[MTF] skip BUY poor breakout candle: %s", quality_meta)
                    return None
            else:
                quality_meta = {}

            regime_gate_ok, regime_gate_meta = self._check_directional_regime_gate(symbol=symbol, side="long", trade_type="impulse", regime=regime, market_state=market_state, adx_h=adx_h, atr_pct_h=atr_pct_h, drift=drift, rsi_h=rsi_h)
            if not regime_gate_ok:
                logger.debug("[MTF] skip BUY impulse by directional regime gate: %s", regime_gate_meta)
                return None
            trend_quality_ok, trend_quality_meta = self._check_trend_strength_and_chop(symbol=symbol, df=df, recent=recent, side="long", trade_type="impulse", close=close, atr_ltf=atr_ltf, adx_h=adx_h, atr_pct_h=atr_pct_h, drift=drift)
            if not trend_quality_ok:
                logger.debug("[MTF] skip BUY impulse by trend quality/chop: %s", trend_quality_meta)
                return None
            strong_setup = self._alt_strong_setup(symbol, adx_h, drift, volume_meta, rs_meta, side="long")
            alt_regime_ok, alt_regime_meta = alt_regime_filter_helper(self, symbol=symbol, side="long", trade_type="impulse", market_state=market_state, alt_meta=alt_meta, rs_meta=rs_meta, btc_meta=btc_meta, adx_h=adx_h, drift=drift, volume_meta=volume_meta, strong_setup=strong_setup)
            if not alt_regime_ok:
                logger.debug("[MTF] skip BUY impulse by alt regime filter: %s", alt_regime_meta)
                return None
            logger.debug(
                "[MTF] BUY: state=%s close=%.2f rh=%.2f vol=%.0f vol_ema=%.0f vol_med=%.0f imp=%.3f adx_h=%.2f atr_pct_h=%.5f rsi_ltf=%.2f alt_score=%.3f btc_score=%.3f rs_ratio=%.3f exc=%.5f body=%.5f uw=%.5f lw=%.5f",
                market_state,
                close,
                range_high,
                volume,
                float(volume_meta.get("vol_ema", 0.0)),
                float(volume_meta.get("vol_median", 0.0)),
                float(volume_meta.get("impulse_score", 0.0)),
                adx_h,
                atr_pct_h,
                rsi_ltf,
                float(alt_meta.get("score", 1.0)),
                float(btc_meta.get("score", 1.0)),
                float(rs_meta.get("ratio", 1.0)),
                float(impulse_meta.get("excursion", 0.0)),
                float(quality_meta.get("body", 0.0)),
                float(quality_meta.get("upper_wick", 0.0)),
                float(quality_meta.get("lower_wick", 0.0)),
            )
            risk_mult = float(cfg.get_symbol_param_float(symbol, "RISK_MULTIPLIER_IMPULSE", float(getattr(cfg, "RISK_MULTIPLIER_IMPULSE", 1.00))))
            if is_alt and alt_near_long and not long_entry_hit:
                near_mult = float(getattr(cfg, "ALT_NEAR_TRIGGER_RISK_MULT", 0.85))
                risk_mult *= near_mult
                self._alt_trace("soft_pass", symbol=symbol, stage="risk", reason="alt_near_long_risk_mult", risk_mult=round(risk_mult,6), near_mult=near_mult)
            if strong_setup:
                risk_mult *= float(cfg.get_symbol_param_float(symbol, "ALT_STRONG_SETUP_RISK_MULT", float(getattr(cfg, "ALT_STRONG_SETUP_RISK_MULT", 1.30))))
            risk_mult, setup_flags = apply_directional_setup_scaling_helper(self, symbol=symbol, base_risk_multiplier=risk_mult, adx_h=adx_h, drift=drift, volume_meta=volume_meta, trade_type="impulse", side="long", market_state=market_state, trend_quality_meta=trend_quality_meta)
            risk_mult, v7_flags = apply_v7_direct_boost_helper(self, symbol=symbol, side="long", trade_type="impulse", base_risk_multiplier=risk_mult, adx_h=adx_h, drift=drift, volume_meta=volume_meta, strong_setup=strong_setup)
            risk_mult, v78_flags = apply_v78_selective_risk_reduction_helper(self, symbol=symbol, side="long", trade_type="impulse", base_risk_multiplier=risk_mult, market_state=market_state, regime=regime, regime_gate_meta=regime_gate_meta, trend_quality_meta=trend_quality_meta, volume_meta=volume_meta, strong_setup=strong_setup, v7_flags=v7_flags)
            risk_mult, v80_alt_flags = apply_v80_alt_engine_upgrade_helper(self, symbol=symbol, side="long", trade_type="impulse", risk_multiplier=risk_mult, alt_meta=alt_meta, btc_meta=btc_meta, rs_meta=rs_meta, adx_h=adx_h, drift=drift, volume_meta=volume_meta, strong_setup=strong_setup)
            v86_long_ok, v86_long_flags = self._apply_v86_inline_long_suppression(symbol=symbol, trade_type="impulse", market_state=market_state, regime=regime, btc_meta=btc_meta, rs_meta=rs_meta, trend_quality_meta=trend_quality_meta, regime_gate_meta=regime_gate_meta, volume_meta=volume_meta, adx_h=adx_h, drift=drift, strong_setup=strong_setup)
            if not v86_long_ok:
                logger.debug("[MTF] skip BUY impulse by v86 inline long suppression: %s", v86_long_flags)
            else:
                return self._set_signal("buy", trade_type="impulse", risk_multiplier=risk_mult, market_state=market_state, impulse_meta=impulse_meta, regime_gate_meta=regime_gate_meta, trend_quality_meta=trend_quality_meta, side="long", strong_setup=strong_setup, **setup_flags, **v7_flags, **v78_flags, **v80_alt_flags, **v86_long_flags)

        # SHORT: H1 bear-тренд + подтверждённое закрытие M15 ниже диапазона
        if regime == "bear" and (short_entry_hit or alt_near_short) and short_rsi_ok:
            self._alt_trace("entry_path", symbol=symbol, path="impulse_short_candidate", close=round(close,6), trigger=round(short_trigger,6), rsi_ltf=round(rsi_ltf,4))
            alt_force_exec_short = False
            alt_late_entry_short = False
            if alt_late_entry_short:
                self._alt_trace("soft_pass", symbol=symbol, stage="late_entry", reason="alt_late_entry_short_candidate", close=round(close,6), trigger=round(short_trigger,6), drift=round(float(drift or 0.0),6), rsi_ltf=round(float(rsi_ltf or 0.0),4))
            if alt_near_short and not short_entry_hit:
                self._alt_trace("soft_pass", symbol=symbol, stage="entry_trigger", reason="alt_near_short_trigger", close=round(close,6), trigger=round(short_trigger,6), tolerance=round(alt_entry_tol,6))
            btc_ok, btc_meta = self._check_btc_regime_filter(df, symbol=symbol, side="short")
            if not btc_ok:
                if alt_force_exec_short:
                    self._alt_trace("soft_pass", symbol=symbol, stage="btc_regime_filter", reason="alt_force_exec_btc_regime_bypass")
                    btc_ok = True
                    btc_meta = btc_meta or {}
                else:
                    logger.debug("[MTF] skip SELL by BTC regime filter: %s", btc_meta)
                    return None
            alt_ok, alt_meta = self._calc_alt_quality_score(symbol=symbol, recent=recent, atr_ltf=atr_ltf, side="short")
            if not alt_ok:
                logger.debug("[MTF] skip SELL by alt quality: %s", alt_meta)
                return None
            if symbol != str(getattr(cfg, "BTC_REGIME_FILTER_SYMBOL", "BTCUSDT")) and bool(getattr(cfg, "ALT_SHORTS_REQUIRE_STRONG_BTC_BEAR", True)):
                btc_short_min = float(getattr(cfg, "BTC_REGIME_MIN_SCORE_SHORT", max(float(getattr(cfg, "BTC_REGIME_MIN_SCORE", 0.95)), 1.05)))
                if float(btc_meta.get("score", 0.0)) < btc_short_min:
                    if alt_force_exec_short:
                        self._alt_trace("soft_pass", symbol=symbol, stage="btc_bear_strength", reason="alt_force_exec_btc_bear_bypass", btc_score=round(float(btc_meta.get("score",0.0)),6), min_score=round(btc_short_min,6))
                    else:
                        logger.debug("[MTF] skip SELL weak BTC bear context: %s", btc_meta)
                        return None
            btc_short_ctx_ok, btc_short_ctx_meta = self._btc_short_trade_ok(symbol=symbol, trade_type="continuation", regime=regime, market_state=market_state, adx_h=adx_h, rsi_h=rsi_h, drift=drift, btc_score=float(btc_meta.get("score", 0.0)))
            if not btc_short_ctx_ok:
                if alt_force_exec_short:
                    self._alt_trace("soft_pass", symbol=symbol, stage="btc_short_context", reason="alt_force_exec_btc_short_ctx_bypass")
                else:
                    logger.debug("[MTF] skip SELL by BTC short context: %s", btc_short_ctx_meta)
                    return None
            confirm_ok, confirm_meta = check_breakout_confirmation(
                symbol=symbol, df=df, side="short", trigger=short_trigger, range_high=range_high, range_low=range_low, atr_ltf=atr_ltf
            )
            if not confirm_ok:

                if (is_alt and alt_near_short and bool(getattr(cfg, "ALT_NEAR_TRIGGER_ALLOW", True))) or alt_force_exec_short or alt_late_entry_short:
                    self._alt_trace("soft_pass", symbol=symbol, stage="breakout_confirmation", reason="alt_near_short_confirmation_bypass")
                    confirm_ok = True
                else:
                    logger.debug("[MTF] skip SELL by breakout confirmation: %s", confirm_meta)
                    return None
            rs_ok, rs_meta = self._check_relative_strength_filter(df=df, symbol=symbol, side="short")
            alt_ok, rs_ok, alt_meta, rs_meta = self._relax_alt_filters(symbol, "short", alt_ok, alt_meta, rs_ok, rs_meta)
            if not rs_ok:
                logger.debug("[MTF] skip SELL by relative strength: %s", rs_meta)
                return None
            impulse_ok, impulse_meta = check_impulse_breakout(symbol=symbol, recent=recent, candle=last, side="short", trigger=short_trigger, atr_ltf=atr_ltf)
            if not impulse_ok:

                if (is_alt and alt_near_short and bool(getattr(cfg, "ALT_NEAR_TRIGGER_ALLOW", True))) or alt_force_exec_short or alt_late_entry_short:
                    self._alt_trace("soft_pass", symbol=symbol, stage="impulse_breakout", reason="alt_near_short_impulse_bypass")
                    impulse_ok = True
                    impulse_meta = {**(impulse_meta or {}), "soft_pass": True, "near_trigger": True, "force_exec": alt_force_exec_short, "late_entry": alt_late_entry_short}
                else:
                    logger.debug("[MTF] skip SELL by impulse breakout: %s", impulse_meta)
                    return None
            if breakout_quality_enabled:
                quality_ok, quality_meta = self._calc_breakout_candle_quality(last, atr_ltf, side="short")
                if not quality_ok:
                    logger.debug("[MTF] skip SELL poor breakout candle: %s", quality_meta)
                    return None
            else:
                quality_meta = {}

            regime_gate_ok, regime_gate_meta = self._check_directional_regime_gate(symbol=symbol, side="short", trade_type="impulse", regime=regime, market_state=market_state, adx_h=adx_h, atr_pct_h=atr_pct_h, drift=drift, rsi_h=rsi_h)
            if not regime_gate_ok:
                logger.debug("[MTF] skip SELL impulse by directional regime gate: %s", regime_gate_meta)
                return None
            trend_quality_ok, trend_quality_meta = self._check_trend_strength_and_chop(symbol=symbol, df=df, recent=recent, side="short", trade_type="impulse", close=close, atr_ltf=atr_ltf, adx_h=adx_h, atr_pct_h=atr_pct_h, drift=drift)
            if not trend_quality_ok:
                logger.debug("[MTF] skip SELL impulse by trend quality/chop: %s", trend_quality_meta)
                return None
            strong_setup = self._alt_strong_setup(symbol, adx_h, drift, volume_meta, rs_meta, side="short")
            alt_regime_ok, alt_regime_meta = alt_regime_filter_helper(self, symbol=symbol, side="short", trade_type="impulse", market_state=market_state, alt_meta=alt_meta, rs_meta=rs_meta, btc_meta=btc_meta, adx_h=adx_h, drift=drift, volume_meta=volume_meta, strong_setup=strong_setup)
            if not alt_regime_ok:
                logger.debug("[MTF] skip SELL impulse by alt regime filter: %s", alt_regime_meta)
                return None
            logger.debug(
                "[MTF] SELL: state=%s close=%.2f rl=%.2f vol=%.0f vol_ema=%.0f vol_med=%.0f imp=%.3f adx_h=%.2f atr_pct_h=%.5f rsi_ltf=%.2f alt_score=%.3f btc_score=%.3f rs_ratio=%.3f exc=%.5f body=%.5f uw=%.5f lw=%.5f",
                market_state,
                close,
                range_low,
                volume,
                float(volume_meta.get("vol_ema", 0.0)),
                float(volume_meta.get("vol_median", 0.0)),
                float(volume_meta.get("impulse_score", 0.0)),
                adx_h,
                atr_pct_h,
                rsi_ltf,
                float(alt_meta.get("score", 1.0)),
                float(btc_meta.get("score", 1.0)),
                float(rs_meta.get("ratio", 1.0)),
                float(impulse_meta.get("excursion", 0.0)),
                float(quality_meta.get("body", 0.0)),
                float(quality_meta.get("upper_wick", 0.0)),
                float(quality_meta.get("lower_wick", 0.0)),
            )
            risk_mult = float(cfg.get_symbol_param_float(symbol, "RISK_MULTIPLIER_IMPULSE", float(getattr(cfg, "RISK_MULTIPLIER_IMPULSE", 1.00))))
            if is_alt and alt_near_short and not short_entry_hit:
                near_mult = float(getattr(cfg, "ALT_NEAR_TRIGGER_RISK_MULT", 0.85))
                risk_mult *= near_mult
                self._alt_trace("soft_pass", symbol=symbol, stage="risk", reason="alt_near_short_risk_mult", risk_mult=round(risk_mult,6), near_mult=near_mult)

            if strong_setup:
                risk_mult *= float(cfg.get_symbol_param_float(symbol, "ALT_STRONG_SETUP_RISK_MULT", float(getattr(cfg, "ALT_STRONG_SETUP_RISK_MULT", 1.30))))
            risk_mult, short_stack_ok, short_stack_flags = apply_impulse_short_risk_stack(self, symbol=symbol, risk_multiplier=risk_mult, market_state=market_state, regime=regime, btc_meta=btc_meta, alt_meta=alt_meta, rs_meta=rs_meta, volume_meta=volume_meta, trend_quality_meta=trend_quality_meta, regime_gate_meta=regime_gate_meta, adx_h=adx_h, drift=drift, strong_setup=strong_setup, allow_late_entry_bypass=alt_late_entry_short)
            if not short_stack_ok:
                logger.debug("[MTF] skip SELL impulse by impulse short risk stack: %s", short_stack_flags)
                return None
            if alt_late_entry_short and short_stack_flags.get("late_entry"):
                if short_stack_flags.get("soft_pass"):
                    suppression_stage = "v83_short_suppression" if "v83_short_suppressed" in short_stack_flags else "v85_inline_short_suppression"
                    self._alt_trace("soft_pass", symbol=symbol, stage=suppression_stage, reason="alt_late_entry_short_stack_bypass")
            return self._set_signal("sell", trade_type="impulse", risk_multiplier=risk_mult, market_state=market_state, impulse_meta=impulse_meta, btc_short_ctx=btc_short_ctx_meta, regime_gate_meta=regime_gate_meta, trend_quality_meta=trend_quality_meta, side="short", strong_setup=strong_setup, **short_stack_flags)

        self._alt_trace("signal_fallthrough", symbol=symbol, market_state=market_state, regime=regime, reason="no_entry_triggered")
        return None
