from __future__ import annotations

import math
import pandas as pd

from .mtf_market_helpers import calc_false_breakout_ratio, calc_recent_wickiness
from .mtf_mean_reversion_helpers import check_v52_mean_reversion_entry, mr_risk_multiplier


def _safe_float(v, default=0.0) -> float:
    try:
        x = float(v)
        if math.isnan(x) or math.isinf(x):
            return float(default)
        return x
    except Exception:
        return float(default)


def run_v22_nontrend_engine(*, cfg, symbol: str, market_state: str, regime: str, recent: pd.DataFrame, candle: pd.Series, atr_ltf: float, adx_h: float, drift: float) -> tuple[str | None, str | None, float, dict]:
    if not bool(getattr(cfg, "V22_DUAL_STRATEGY_ENABLED", True)):
        return None, None, 1.0, {"reason": "disabled"}
    symbols = set(getattr(cfg, "V22_DUAL_STRATEGY_SYMBOLS", ["BTCUSDT", "ETHUSDT"]) or [])
    if symbol not in symbols:
        return None, None, 1.0, {"reason": "symbol_not_enabled"}
    allowed_states = set(getattr(cfg, "V22_NON_TREND_STATES", ["range", "transition"]) or ["range", "transition"])
    if market_state not in allowed_states:
        return None, None, 1.0, {"reason": "state_not_enabled", "market_state": market_state}
    if recent is None or len(recent) < 20 or atr_ltf <= 0:
        return None, None, 1.0, {"reason": "not_enough_data"}

    max_engine_adx = float(getattr(cfg, "V22_ENGINE_MAX_HTF_ADX", 22.0 if symbol == "BTCUSDT" else 20.0))
    max_engine_drift = float(getattr(cfg, "V22_ENGINE_MAX_DRIFT_PCT", 0.0054 if symbol == "BTCUSDT" else 0.0048))
    if adx_h > max_engine_adx or drift > max_engine_drift:
        return None, None, 1.0, {"reason": "nontrend_guard_blocked", "adx_h": adx_h, "drift": drift}

    # 1) Existing controlled mean reversion becomes the first engine in weak regimes.
    mr_enabled = bool(getattr(cfg, "V22_MR_ENABLED", True))
    if symbol == "ETHUSDT":
        mr_enabled = bool(getattr(cfg, "V22_ETH_MR_ENABLED", False))
    elif symbol == "BTCUSDT":
        mr_enabled = bool(getattr(cfg, "V22_BTC_MR_ENABLED", True))

    mr_allowed_states = set(getattr(cfg, "V22_MR_ALLOWED_STATES", ["range"]) or ["range"])
    mr_meta = {"reason": "mr_skipped"}
    mr_signal = None
    selective_mr_max_adx = float(getattr(cfg, "V23_MR_MAX_HTF_ADX_BTC", 18.5)) if symbol == "BTCUSDT" else float(getattr(cfg, "V23_MR_MAX_HTF_ADX_ETH", 15.5))
    selective_mr_max_drift = float(getattr(cfg, "V23_MR_MAX_DRIFT_PCT_BTC", 0.0036)) if symbol == "BTCUSDT" else float(getattr(cfg, "V23_MR_MAX_DRIFT_PCT_ETH", 0.0028))
    selective_mr_max_vol_ratio = float(getattr(cfg, "V23_MR_MAX_VOL_RATIO_BTC", 1.08)) if symbol == "BTCUSDT" else float(getattr(cfg, "V23_MR_MAX_VOL_RATIO_ETH", 1.02))
    mr_quiet_enough = adx_h <= selective_mr_max_adx and drift <= selective_mr_max_drift
    # use candle volume/body shape as additional anti-breakout guard
    mr_candle_ok = True
    try:
        tmp_volume = float(candle.get("volume", 0.0) or 0.0)
        tmp_vols = recent["volume"].astype(float).tail(12) if "volume" in recent.columns else pd.Series(dtype=float)
        tmp_vol_ma = float(tmp_vols.mean()) if len(tmp_vols) else max(tmp_volume, 1.0)
        tmp_vol_ratio = (tmp_volume / tmp_vol_ma) if tmp_vol_ma > 0 else 1.0
        tmp_body_atr = abs(float(candle.get("close", 0.0) or 0.0) - float(candle.get("open", 0.0) or 0.0)) / max(atr_ltf, 1e-9)
        mr_candle_ok = tmp_vol_ratio <= selective_mr_max_vol_ratio and tmp_body_atr <= float(getattr(cfg, "V23_MR_MAX_BODY_ATR", 0.42))
    except Exception:
        tmp_vol_ratio = 1.0
        tmp_body_atr = 0.0
    if mr_enabled and market_state in mr_allowed_states and mr_quiet_enough and mr_candle_ok:
        mr_signal, mr_meta = check_v52_mean_reversion_entry(
        cfg=cfg,
        symbol=symbol,
        market_state=market_state,
        recent=recent,
        candle=candle,
        atr_ltf=atr_ltf,
        )
    else:
        mr_meta = {
            "reason": "mr_selective_blocked",
            "mr_quiet_enough": mr_quiet_enough,
            "mr_candle_ok": mr_candle_ok,
            "tmp_vol_ratio": tmp_vol_ratio,
            "tmp_body_atr": tmp_body_atr,
        }
    if mr_signal == "buy":
        risk_mult = mr_risk_multiplier(cfg=cfg, symbol=symbol) * float(getattr(cfg, "V22_MR_LONG_RISK_MULT", 1.0))
        risk_mult *= float(getattr(cfg, "V23_MR_RISK_MULT_BTC", 0.92)) if symbol == "BTCUSDT" else float(getattr(cfg, "V23_MR_RISK_MULT_ETH", 0.80))
        return "buy", "mean_reversion", risk_mult, {**mr_meta, "engine": "v23_selective_mr"}

    # 2) Range reclaim long: small long-only engine for flat/weak bull context.
    if regime != "bull":
        return None, None, 1.0, {"reason": "reclaim_requires_bull", "mr_reason": mr_meta.get("reason") if isinstance(mr_meta, dict) else None}
    reclaim_allowed_states = set(getattr(cfg, "BTC_RECLAIM_ALLOWED_STATES", ["range", "flat"]) if symbol == "BTCUSDT" else ["range", "transition"])
    if market_state not in reclaim_allowed_states:
        return None, None, 1.0, {"reason": "reclaim_state_blocked", "market_state": market_state}

    close = _safe_float(candle.get("close"))
    open_ = _safe_float(candle.get("open"), close)
    high = _safe_float(candle.get("high"), close)
    low = _safe_float(candle.get("low"), close)
    ema20 = _safe_float(candle.get("EMA20"), close)
    rsi = _safe_float(candle.get("RSI"), 50.0)
    htf_rsi = _safe_float(candle.get("HTF_RSI"), 50.0)
    htf_adx = _safe_float(candle.get("HTF_ADX"), adx_h)
    volume = _safe_float(candle.get("volume"), 0.0)

    if close <= 0 or ema20 <= 0:
        return None, None, 1.0, {"reason": "bad_price_inputs"}

    vols = recent["volume"].astype(float).tail(12) if "volume" in recent.columns else pd.Series(dtype=float)
    vol_ma = float(vols.mean()) if len(vols) else max(volume, 1.0)
    vol_ratio = (volume / vol_ma) if vol_ma > 0 else 1.0
    candle_range = max(high - low, 1e-9)
    body_atr = abs(close - open_) / max(atr_ltf, 1e-9)
    close_pos = (close - low) / candle_range
    progress_from_low_atr = max(close - low, 0.0) / max(atr_ltf, 1e-9)
    ema_reclaim_pct = (close - ema20) / close
    wickiness = calc_recent_wickiness(recent)
    false_breakout_ratio = calc_false_breakout_ratio(recent, lookback=min(10, max(6, len(recent) // 4)))

    # v23 selective non-trend: only allow weak-engine in genuinely quiet/rangy conditions,
    # not when candles already look like directional expansion.
    engine_max_vol_ratio = float(getattr(cfg, "V23_ENGINE_MAX_VOL_RATIO_BTC", 1.12)) if symbol == "BTCUSDT" else float(getattr(cfg, "V23_ENGINE_MAX_VOL_RATIO_ETH", 1.05))
    engine_max_body_atr = float(getattr(cfg, "V23_ENGINE_MAX_BODY_ATR_BTC", 0.58)) if symbol == "BTCUSDT" else float(getattr(cfg, "V23_ENGINE_MAX_BODY_ATR_ETH", 0.48))
    engine_max_close_pos = float(getattr(cfg, "V23_ENGINE_MAX_CLOSE_POS_BTC", 0.88)) if symbol == "BTCUSDT" else float(getattr(cfg, "V23_ENGINE_MAX_CLOSE_POS_ETH", 0.82))
    if vol_ratio > engine_max_vol_ratio or body_atr > engine_max_body_atr or close_pos > engine_max_close_pos:
        return None, None, 1.0, {
            "reason": "selective_nontrend_breakout_guard",
            "vol_ratio": vol_ratio,
            "body_atr": body_atr,
            "close_pos": close_pos,
            "market_state": market_state,
        }

    max_adx = float(getattr(cfg, "V22_RECLAIM_MAX_HTF_ADX_BTC", 21.5)) if symbol == "BTCUSDT" else float(getattr(cfg, "V22_RECLAIM_MAX_HTF_ADX_ETH", 19.5))
    max_drift = float(getattr(cfg, "V22_RECLAIM_MAX_DRIFT_PCT_BTC", 0.0048)) if symbol == "BTCUSDT" else float(getattr(cfg, "V22_RECLAIM_MAX_DRIFT_PCT_ETH", 0.0042))
    min_vol_ratio = float(getattr(cfg, "V22_RECLAIM_MIN_VOL_RATIO_BTC", 1.00)) if symbol == "BTCUSDT" else float(getattr(cfg, "V22_RECLAIM_MIN_VOL_RATIO_ETH", 1.04))
    min_body_atr = float(getattr(cfg, "V22_RECLAIM_MIN_BODY_ATR_BTC", 0.22)) if symbol == "BTCUSDT" else float(getattr(cfg, "V22_RECLAIM_MIN_BODY_ATR_ETH", 0.26))
    min_close_pos = float(getattr(cfg, "V22_RECLAIM_MIN_CLOSE_POS_BTC", 0.62)) if symbol == "BTCUSDT" else float(getattr(cfg, "V22_RECLAIM_MIN_CLOSE_POS_ETH", 0.66))
    max_wickiness = float(getattr(cfg, "V22_RECLAIM_MAX_WICKINESS_BTC", 0.62)) if symbol == "BTCUSDT" else float(getattr(cfg, "V22_RECLAIM_MAX_WICKINESS_ETH", 0.56))
    max_false_breakout = float(getattr(cfg, "V22_RECLAIM_MAX_FALSE_BREAKOUT_BTC", 0.50)) if symbol == "BTCUSDT" else float(getattr(cfg, "V22_RECLAIM_MAX_FALSE_BREAKOUT_ETH", 0.42))
    min_reclaim_pct = float(getattr(cfg, "V22_RECLAIM_MIN_EMA20_RECLAIM_PCT_BTC", 0.0008)) if symbol == "BTCUSDT" else float(getattr(cfg, "V22_RECLAIM_MIN_EMA20_RECLAIM_PCT_ETH", 0.0012))
    rsi_min = float(getattr(cfg, "V22_RECLAIM_RSI_MIN_BTC", 44.0)) if symbol == "BTCUSDT" else float(getattr(cfg, "V22_RECLAIM_RSI_MIN_ETH", 45.0))
    rsi_max = float(getattr(cfg, "V22_RECLAIM_RSI_MAX_BTC", 56.0)) if symbol == "BTCUSDT" else float(getattr(cfg, "V22_RECLAIM_RSI_MAX_ETH", 55.0))
    htf_rsi_min = float(getattr(cfg, "V22_RECLAIM_HTF_RSI_MIN_BTC", 48.0)) if symbol == "BTCUSDT" else float(getattr(cfg, "V22_RECLAIM_HTF_RSI_MIN_ETH", 50.0))

    anti_knife_ok = True
    if symbol == "BTCUSDT" and bool(getattr(cfg, "BTC_MR_ANTI_KNIFE_ENABLED", True)):
        anti_knife_max_body_atr = float(getattr(cfg, "BTC_MR_ANTI_KNIFE_MAX_BODY_ATR", 0.95))
        anti_knife_max_neg_progress_atr = float(getattr(cfg, "BTC_MR_ANTI_KNIFE_MAX_NEG_PROGRESS_ATR", 0.55))
        anti_knife_require_green = bool(getattr(cfg, "BTC_MR_ANTI_KNIFE_REQUIRE_GREEN_CANDLE", True))
        anti_knife_ok = body_atr <= anti_knife_max_body_atr and progress_from_low_atr <= anti_knife_max_neg_progress_atr
        if anti_knife_require_green and close < open_:
            anti_knife_ok = False

    reasons: list[str] = []
    if htf_adx > max_adx:
        reasons.append("adx_too_high")
    if drift > max_drift:
        reasons.append("drift_too_high")
    if vol_ratio < min_vol_ratio:
        reasons.append("vol_too_low")
    if body_atr < min_body_atr:
        reasons.append("body_too_small")
    if close_pos < min_close_pos:
        reasons.append("weak_close")
    if wickiness > max_wickiness:
        reasons.append("too_wicky")
    if false_breakout_ratio > max_false_breakout:
        reasons.append("too_many_false_breakouts")
    if ema_reclaim_pct < min_reclaim_pct:
        reasons.append("ema20_not_reclaimed")
    if not (rsi_min <= rsi <= rsi_max):
        reasons.append("rsi_not_balanced")
    if htf_rsi < htf_rsi_min:
        reasons.append("htf_rsi_too_low")
    if not anti_knife_ok:
        reasons.append("anti_knife_blocked")

    meta = {
        "engine": "v22_reclaim",
        "market_state": market_state,
        "regime": regime,
        "vol_ratio": vol_ratio,
        "body_atr": body_atr,
        "close_pos": close_pos,
        "ema_reclaim_pct": ema_reclaim_pct,
        "wickiness": wickiness,
        "false_breakout_ratio": false_breakout_ratio,
        "rsi": rsi,
        "htf_rsi": htf_rsi,
        "htf_adx": htf_adx,
        "drift": drift,
        "mr_reason": mr_meta.get("reason") if isinstance(mr_meta, dict) else None,
    }
    if reasons:
        return None, None, 1.0, {**meta, "reason": "reclaim_not_ready", "reasons": reasons}

    base_risk = float(getattr(cfg, "V22_RECLAIM_RISK_MULTIPLIER_BTC", 0.44)) if symbol == "BTCUSDT" else float(getattr(cfg, "V22_RECLAIM_RISK_MULTIPLIER_ETH", 0.30))
    if market_state == "transition":
        base_risk *= float(getattr(cfg, "V22_RECLAIM_TRANSITION_MULT", 0.84))
    return "buy", "reclaim_range", base_risk, meta
