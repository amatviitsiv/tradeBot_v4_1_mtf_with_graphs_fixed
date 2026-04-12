import logging
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
        self.last_signal_meta = {"signal": None, "trade_type": None, "risk_multiplier": 1.0}
        self._current_symbol = None
        self._current_regime = None
        self._trace_file_initialized = False
        self._trace_file_path = None
        self._last_atr_pct_h = 0.0
        self._maybe_reset_alt_trace_file()

    def _apply_directional_setup_scaling(self, symbol: str, base_risk_multiplier: float, adx_h: float, drift: float, volume_meta: dict | None = None, trade_type: str = "", side: str = "", market_state: str = "", trend_quality_meta: dict | None = None) -> tuple[float, dict]:
        return apply_directional_setup_scaling_helper(self, symbol=symbol, base_risk_multiplier=base_risk_multiplier, adx_h=adx_h, drift=drift, volume_meta=volume_meta, trade_type=trade_type, side=side, market_state=market_state, trend_quality_meta=trend_quality_meta)

    def _apply_v7_direct_boost(self, symbol: str, side: str, trade_type: str, base_risk_multiplier: float, adx_h: float, drift: float, volume_meta: dict | None = None, strong_setup: bool = False, regime_gate_meta: dict | None = None) -> tuple[float, dict]:
        return apply_v7_direct_boost_helper(self, symbol=symbol, side=side, trade_type=trade_type, base_risk_multiplier=base_risk_multiplier, adx_h=adx_h, drift=drift, volume_meta=volume_meta, strong_setup=strong_setup, regime_gate_meta=regime_gate_meta)

    def _apply_v78_selective_risk_reduction(self, symbol: str, side: str, trade_type: str, base_risk_multiplier: float, market_state: str = "", regime: str = "", regime_gate_meta: dict | None = None, trend_quality_meta: dict | None = None, volume_meta: dict | None = None, strong_setup: bool = False, v7_flags: dict | None = None) -> tuple[float, dict]:
        return apply_v78_selective_risk_reduction_helper(self, symbol=symbol, side=side, trade_type=trade_type, base_risk_multiplier=base_risk_multiplier, market_state=market_state, regime=regime, regime_gate_meta=regime_gate_meta, trend_quality_meta=trend_quality_meta, volume_meta=volume_meta, strong_setup=strong_setup, v7_flags=v7_flags)

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
        allowed_symbols = set(getattr(cfg, "ALT_TRACE_SYMBOLS", ["ETHUSDT", "SOLUSDT", "BNBUSDT", "AVAXUSDT"]) or [])
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

    def _set_signal(self, signal: Optional[str], trade_type: str | None = None, risk_multiplier: float = 1.0, **meta):
        exec_risk = float(risk_multiplier)
        symbol = str(meta.get("symbol") or self._current_symbol or "")
        side = str(meta.get("side") or ("short" if signal == "sell" else "long" if signal == "buy" else "")).lower()
        regime = str(meta.get("regime") or self._current_regime or "")
        self._alt_trace("set_signal_call", symbol=symbol, signal=signal, trade_type=trade_type, risk_multiplier=exec_risk, regime=regime, side=side)
        if signal == "sell" and side == "short" and self._should_suppress_short_signal(symbol=symbol, trade_type=trade_type, regime=regime, meta=meta):
            self.last_signal_meta = {
                "signal": None,
                "trade_type": trade_type,
                "risk_multiplier": 1.0,
                "execution_risk_multiplier": 1.0,
                "v84_short_suppressed": True,
                "v84_short_suppression_reason": self._build_short_suppression_reason(symbol=symbol, trade_type=trade_type, regime=regime, meta=meta),
                **meta,
            }
            self._alt_trace("set_signal_return", symbol=symbol, signal=None, trade_type=trade_type, risk_multiplier=1.0, regime=regime, side=side, suppressed=True)
            return None
        self.last_signal_meta = {
            "signal": signal,
            "trade_type": trade_type,
            "risk_multiplier": exec_risk,
            "execution_risk_multiplier": exec_risk,
            **meta,
        }
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

    def _is_mean_reversion_symbol(self, symbol: str) -> bool:
        return is_mean_reversion_symbol(cfg=cfg, symbol=symbol)

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
        alt_symbols = set(getattr(cfg, "BTC_REGIME_ALT_SYMBOLS", ["ETHUSDT", "SOLUSDT", "BNBUSDT", "AVAXUSDT"]) or [])
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
        self.last_signal_meta = {"signal": None, "trade_type": None, "risk_multiplier": 1.0}
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
        is_alt = self._is_alt_symbol(symbol)
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

        mr_signal, mr_meta = check_v52_mean_reversion_entry(cfg=cfg, symbol=symbol, market_state=market_state, recent=recent, candle=last, atr_ltf=atr_ltf)
        if mr_signal is not None:
            if symbol == "ETHUSDT" and mr_signal == "sell" and bool(getattr(cfg, "V54_ETH_DISABLE_SHORTS", True)):
                mr_signal = None
            else:
                logger.debug("[MTF] MR %s state=%s meta=%s", mr_signal.upper(), market_state, mr_meta)
                return self._set_signal(mr_signal, trade_type="mean_reversion", risk_multiplier=self._mr_risk_multiplier(symbol), market_state=market_state, mean_reversion_meta=mr_meta, side="long" if mr_signal == "buy" else "short")

        if symbol == "ETHUSDT" and bool(getattr(cfg, "V54_ETH_MR_ONLY", True)):
            return self._set_signal(None)

        if market_state in {"range", "transition"} and self._symbol_flag(symbol, "ENABLE_FAKEOUT", False):
            fake_long_ok, fake_long_meta = check_fakeout_reversal_entry(symbol=symbol, df=df, recent=recent, side="long", range_high=range_high, range_low=range_low, atr_ltf=atr_ltf, adx_h=adx_h)
            if fake_long_ok:
                v86_long_ok, v86_long_flags = self._apply_v86_inline_long_suppression(symbol=symbol, trade_type="fakeout", market_state=market_state, regime=regime, btc_meta=btc_meta if 'btc_meta' in locals() and isinstance(btc_meta, dict) else {}, rs_meta={}, trend_quality_meta={}, regime_gate_meta={}, volume_meta={}, adx_h=adx_h, drift=drift, strong_setup=False)
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
            range_sig, range_meta = range_signal(
                symbol=symbol,
                df=df,
                recent=recent,
                close=close,
                atr_ltf=atr_ltf,
                adx_h=adx_h,
                market_meta=market_meta,
            )
            if range_sig is not None:
                logger.debug("[MTF] RANGE %s state=%s meta=%s", range_sig.upper(), market_state, range_meta)
                return self._set_signal(range_sig, trade_type="range", risk_multiplier=float(getattr(cfg, "RISK_MULTIPLIER_RANGE", 0.45)), market_state=market_state, range_meta=range_meta)

        if symbol == str(getattr(cfg, "BTC_REGIME_FILTER_SYMBOL", "BTCUSDT")):
            btc_exh_ok, btc_exh_meta = check_btc_exhaustion_short(symbol=symbol, df=df, recent=recent, atr_ltf=atr_ltf, adx_h=adx_h, rsi_h=rsi_h, ema20_h=ema20_h, ema50_h=ema50_h, regime=regime)
            if btc_exh_ok:
                logger.debug("[MTF] BTC exhaustion short: state=%s meta=%s", market_state, btc_exh_meta)
                v85_short_ok, v85_short_flags = self._apply_v85_inline_short_suppression(symbol=symbol, trade_type="btc_exhaustion", market_state=market_state, regime=regime, btc_meta=btc_meta if 'btc_meta' in locals() and isinstance(btc_meta, dict) else {}, rs_meta={}, trend_quality_meta={}, regime_gate_meta={}, strong_setup=False)
                if not v85_short_ok:
                    logger.debug("[MTF] skip SELL btc_exhaustion by v85 inline short suppression: %s", v85_short_flags)
                    return None
                return self._set_signal("sell", trade_type="btc_exhaustion", risk_multiplier=float(cfg.get_symbol_param_float(symbol, "BTC_EXHAUSTION_RISK_MULTIPLIER", float(getattr(cfg, "BTC_EXHAUSTION_RISK_MULTIPLIER", 0.70)))), market_state=market_state, btc_exhaustion_meta=btc_exh_meta, side="short", **v85_short_flags)

        # Более устойчивый volume / momentum фильтр на LTF.
        volume_filter_enabled = bool(getattr(cfg, "BREAKOUT_VOLUME_FILTER_V2_ENABLED", True))
        if volume_filter_enabled:
            volume_ok, volume_meta = self._calc_breakout_volume_momentum(recent=recent, candle=last, atr_ltf=atr_ltf, side="long" if regime == "bull" else "short")
        else:
            volume_ok = True
            volume_meta = {
                "volume": volume,
                "vol_ema": float(recent["volume"].astype(float).ewm(span=20, adjust=False).mean().iloc[-1]),
                "vol_median": float(recent["volume"].median()),
                "impulse_score": 0.0,
                "is_strong_impulse": False,
            }

        # ======================================================
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
        if bool(getattr(cfg, "CONTINUATION_ALLOW_IN_TRANSITION", True)):
            continuation_states.add("transition")
        if is_alt and bool(getattr(cfg, "ALT_CONTINUATION_ALLOW_IN_RANGE", True)):
            continuation_states.add("range")

        if market_state in continuation_states or transition_state:
            self._alt_trace("entry_path", symbol=symbol, path="continuation_block", market_state=market_state, regime=regime)
            pullback_states = {"trend"}
            if bool(getattr(cfg, "PULLBACK_TREND_ALLOW_IN_TRANSITION", False)):
                pullback_states.add("transition")
            pullback_enabled = bool(getattr(cfg, "PULLBACK_TREND_ENABLED", False)) and symbol in set(getattr(cfg, "PULLBACK_TREND_SYMBOLS", []))
            if pullback_enabled and market_state in pullback_states:
                if regime == "bull":
                    btc_ok, btc_meta = self._check_btc_regime_filter(df, symbol=symbol, side="long")
                    pullback_ok, pullback_meta = check_pullback_trend_entry(symbol=symbol, df=df, side="long", atr_ltf=atr_ltf)
                    if btc_ok and pullback_ok:
                        regime_gate_ok, regime_gate_meta = self._check_directional_regime_gate(symbol=symbol, side="long", trade_type="continuation", regime=regime, market_state=market_state, adx_h=adx_h, atr_pct_h=atr_pct_h, drift=drift, rsi_h=rsi_h)
                        if regime_gate_ok:
                            trend_quality_ok, trend_quality_meta = self._check_trend_strength_and_chop(symbol=symbol, df=df, recent=recent, side="long", trade_type="continuation", close=close, atr_ltf=atr_ltf, adx_h=adx_h, atr_pct_h=atr_pct_h, drift=drift)
                            if trend_quality_ok:
                                risk_mult = float(cfg.get_symbol_param_float(symbol, "PULLBACK_RISK_MULTIPLIER", float(getattr(cfg, "PULLBACK_RISK_MULTIPLIER", 0.75))))
                                risk_mult, long_stack_ok, long_stack_flags = apply_pullback_long_risk_stack(self, symbol=symbol, risk_multiplier=risk_mult, market_state=market_state, regime=regime, btc_meta=btc_meta, volume_meta=volume_meta, trend_quality_meta=trend_quality_meta, regime_gate_meta=regime_gate_meta, adx_h=adx_h, drift=drift)
                                if not long_stack_ok:
                                    logger.debug("[MTF] skip BUY pullback by pullback long risk stack: %s", long_stack_flags)
                                else:
                                    return self._set_signal("buy", trade_type="pullback", risk_multiplier=risk_mult, market_state=market_state, pullback_meta=pullback_meta, regime_gate_meta=regime_gate_meta, trend_quality_meta=trend_quality_meta, side="long", **long_stack_flags)
                elif regime == "bear":
                    btc_ok, btc_meta = self._check_btc_regime_filter(df, symbol=symbol, side="short")
                    pullback_ok, pullback_meta = check_pullback_trend_entry(symbol=symbol, df=df, side="short", atr_ltf=atr_ltf)
                    btc_short_ok, btc_short_meta = self._btc_short_trade_ok(symbol=symbol, trade_type="continuation", regime=regime, market_state=market_state, adx_h=adx_h, rsi_h=rsi_h, drift=drift, btc_score=float(btc_meta.get("score", 0.0)))
                    if btc_ok and pullback_ok and btc_short_ok:
                        regime_gate_ok, regime_gate_meta = self._check_directional_regime_gate(symbol=symbol, side="short", trade_type="continuation", regime=regime, market_state=market_state, adx_h=adx_h, atr_pct_h=atr_pct_h, drift=drift, rsi_h=rsi_h)
                        if regime_gate_ok:
                            trend_quality_ok, trend_quality_meta = self._check_trend_strength_and_chop(symbol=symbol, df=df, recent=recent, side="short", trade_type="continuation", close=close, atr_ltf=atr_ltf, adx_h=adx_h, atr_pct_h=atr_pct_h, drift=drift)
                            if trend_quality_ok:
                                risk_mult = float(cfg.get_symbol_param_float(symbol, "PULLBACK_RISK_MULTIPLIER", float(getattr(cfg, "PULLBACK_RISK_MULTIPLIER", 0.75))))
                                risk_mult, short_stack_ok, short_stack_flags = apply_standard_short_risk_stack(self, symbol=symbol, trade_type="pullback", risk_multiplier=risk_mult, market_state=market_state, regime=regime, btc_meta=btc_meta, alt_meta={}, rs_meta={}, volume_meta=volume_meta, trend_quality_meta=trend_quality_meta, regime_gate_meta=regime_gate_meta, adx_h=adx_h, drift=drift, strong_setup=False)
                                if not short_stack_ok:
                                    logger.debug("[MTF] skip SELL pullback by standard short risk stack: %s", short_stack_flags)
                                    return None
                                return self._set_signal("sell", trade_type="pullback", risk_multiplier=risk_mult, market_state=market_state, pullback_meta=pullback_meta, btc_short_ctx=btc_short_meta, regime_gate_meta=regime_gate_meta, trend_quality_meta=trend_quality_meta, side="short", **short_stack_flags)
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
            alt_force_exec_short = bool(
                is_alt
                and bool(getattr(cfg, "ALT_FINAL_ENTRY_EXECUTION_ALLOW", True))
                and symbol in set(getattr(cfg, "ALT_FINAL_ENTRY_EXECUTION_SYMBOLS", ["SOLUSDT", "BNBUSDT", "AVAXUSDT"]) or [])
                and alt_near_short
                and not short_entry_hit
                and float(adx_h or 0.0) >= float(getattr(cfg, "ALT_FORCE_EXEC_MIN_ADX_H", 15.0))
                and float(drift or 0.0) >= float(getattr(cfg, "ALT_FORCE_EXEC_MIN_DRIFT", 0.02))
                and float((volume_meta or {}).get("impulse_score", 0.0) or 0.0) >= float(getattr(cfg, "ALT_FORCE_EXEC_MIN_IMPULSE_SCORE", 0.095))
            )
            alt_late_entry_short = bool(
                is_alt
                and bool(getattr(cfg, "ALT_LATE_ENTRY_IMPROVEMENT_ALLOW", True))
                and symbol in set(getattr(cfg, "ALT_LATE_ENTRY_SYMBOLS", ["SOLUSDT", "BNBUSDT", "AVAXUSDT"]) or [])
                and alt_near_short
                and not short_entry_hit
                and abs(float(close or 0.0) - float(short_trigger or 0.0)) / max(abs(float(short_trigger or 0.0)), 1e-9) <= float(getattr(cfg, "ALT_LATE_ENTRY_MAX_TRIGGER_DIST_PCT", 0.0025))
                and float(drift or 0.0) >= float(getattr(cfg, "ALT_LATE_ENTRY_MIN_DRIFT", 0.03))
                and float(rsi_ltf or 50.0) <= float(getattr(cfg, "ALT_LATE_ENTRY_MAX_RSI_SHORT", 32.0))
                and float(adx_h or 0.0) >= float(getattr(cfg, "ALT_LATE_ENTRY_MIN_ADX_H", 17.0))
                and float((volume_meta or {}).get("impulse_score", 0.0) or 0.0) >= float(getattr(cfg, "ALT_LATE_ENTRY_MIN_IMPULSE_SCORE", 0.14))
            )
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
                if False and alt_force_exec_short:
                    self._alt_trace("soft_pass", symbol=symbol, stage="alt_quality", reason="alt_force_exec_alt_quality_bypass")
                    alt_ok = True
                    alt_meta = {**(alt_meta or {}), "soft_pass": True, "force_exec": True}
                else:
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
                if False and alt_force_exec_short:
                    self._alt_trace("soft_pass", symbol=symbol, stage="relative_strength", reason="alt_force_exec_rs_bypass")
                    rs_ok = True
                    rs_meta = {**(rs_meta or {}), "soft_pass": True, "force_exec": True}
                else:
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
                    if False and alt_force_exec_short:
                        self._alt_trace("soft_pass", symbol=symbol, stage="breakout_quality", reason="alt_force_exec_quality_bypass")
                        quality_ok = True
                    else:
                        logger.debug("[MTF] skip SELL poor breakout candle: %s", quality_meta)
                        return None
            else:
                quality_meta = {}

            regime_gate_ok, regime_gate_meta = self._check_directional_regime_gate(symbol=symbol, side="short", trade_type="impulse", regime=regime, market_state=market_state, adx_h=adx_h, atr_pct_h=atr_pct_h, drift=drift, rsi_h=rsi_h)
            if not regime_gate_ok:
                if False and alt_force_exec_short:
                    self._alt_trace("soft_pass", symbol=symbol, stage="directional_regime_gate", reason="alt_force_exec_regime_gate_bypass")
                    regime_gate_ok = True
                    regime_gate_meta = {**(regime_gate_meta or {}), "soft_pass": True, "force_exec": True}
                else:
                    logger.debug("[MTF] skip SELL impulse by directional regime gate: %s", regime_gate_meta)
                    return None
            trend_quality_ok, trend_quality_meta = self._check_trend_strength_and_chop(symbol=symbol, df=df, recent=recent, side="short", trade_type="impulse", close=close, atr_ltf=atr_ltf, adx_h=adx_h, atr_pct_h=atr_pct_h, drift=drift)
            if not trend_quality_ok:
                if False and alt_force_exec_short:
                    self._alt_trace("soft_pass", symbol=symbol, stage="trend_quality", reason="alt_force_exec_trend_quality_bypass")
                    trend_quality_ok = True
                    trend_quality_meta = {**(trend_quality_meta or {}), "soft_pass": True, "force_exec": True}
                else:
                    logger.debug("[MTF] skip SELL impulse by trend quality/chop: %s", trend_quality_meta)
                    return None
            strong_setup = self._alt_strong_setup(symbol, adx_h, drift, volume_meta, rs_meta, side="short")
            alt_regime_ok, alt_regime_meta = alt_regime_filter_helper(self, symbol=symbol, side="short", trade_type="impulse", market_state=market_state, alt_meta=alt_meta, rs_meta=rs_meta, btc_meta=btc_meta, adx_h=adx_h, drift=drift, volume_meta=volume_meta, strong_setup=strong_setup)
            if not alt_regime_ok:
                if False and alt_force_exec_short:
                    self._alt_trace("soft_pass", symbol=symbol, stage="alt_regime_filter", reason="alt_force_exec_alt_regime_bypass")
                    alt_regime_ok = True
                    alt_regime_meta = {**(alt_regime_meta or {}), "soft_pass": True, "force_exec": True}
                else:
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

            if alt_force_exec_short:
                force_mult = float(getattr(cfg, "ALT_FINAL_ENTRY_EXECUTION_RISK_MULT", 0.72))
                risk_mult *= force_mult
                self._alt_trace("soft_pass", symbol=symbol, stage="risk", reason="alt_force_exec_risk_mult", risk_mult=round(risk_mult,6), force_mult=force_mult)
            if alt_late_entry_short:
                late_mult = float(getattr(cfg, "ALT_LATE_ENTRY_RISK_MULT", 0.74))
                risk_mult *= late_mult
                self._alt_trace("soft_pass", symbol=symbol, stage="risk", reason="alt_late_entry_risk_mult", risk_mult=round(risk_mult,6), late_mult=late_mult)
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
