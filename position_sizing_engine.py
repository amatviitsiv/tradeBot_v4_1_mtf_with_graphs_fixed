from __future__ import annotations

from typing import Any


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return float(default)


def _v70_aggressive_risk_multiplier(*, cfg, sig_meta: dict, symbol: str, side: str, trade_type: str, equity: float, equity_peak: float) -> tuple[float, dict]:
    """Return V70 risk multiplier and flags for approved BTC pullback trades.

    V70 intentionally lives in the execution sizing layer so it changes real
    position size instead of only annotating strategy metadata.
    """
    flags: dict[str, Any] = {"v70_enabled": False, "v70_scaled": False, "v70_mult": 1.0}
    try:
        if not bool(getattr(cfg, 'V70_AGGRESSIVE_RISK_PROFILE_ENABLED', False)):
            return 1.0, flags
        allowed_symbols = {str(x).upper() for x in (getattr(cfg, 'V70_SYMBOLS', ['BTCUSDT']) or ['BTCUSDT'])}
        allowed_types = {str(x).lower() for x in (getattr(cfg, 'V70_TRADE_TYPES', ['pullback']) or ['pullback'])}
        symbol_u = str(symbol or '').upper()
        side_l = str(side or '').lower()
        trade_l = str(trade_type or '').lower()
        if symbol_u not in allowed_symbols or trade_l not in allowed_types:
            flags['v70_reason'] = 'not_allowed_symbol_or_type'
            return 1.0, flags
        if side_l == 'long' and not bool(getattr(cfg, 'V70_APPLY_TO_LONG', True)):
            flags['v70_reason'] = 'long_disabled'
            return 1.0, flags
        if side_l == 'short' and not bool(getattr(cfg, 'V70_APPLY_TO_SHORT', True)):
            flags['v70_reason'] = 'short_disabled'
            return 1.0, flags

        # Read quality from the metadata already produced by v52/v60.
        score = _safe_float(
            sig_meta.get('v52_score',
            sig_meta.get('v60_score',
            (sig_meta.get('v52_microstructure_meta') or {}).get('v52_score',
            (sig_meta.get('v60_short_meta') or {}).get('v60_score', 0.0)))),
            0.0,
        )
        failed = int(_safe_float(
            sig_meta.get('v52_failed_breakouts',
            (sig_meta.get('v52_microstructure_meta') or {}).get('v52_failed_breakouts', 0)),
            0.0,
        ))
        vol_ratio = _safe_float(
            sig_meta.get('v52_vol_ratio',
            (sig_meta.get('v52_microstructure_meta') or {}).get('v52_vol_ratio', 1.0)),
            1.0,
        )
        upper_wick = _safe_float(
            sig_meta.get('v52_upper_wick_atr',
            (sig_meta.get('v52_microstructure_meta') or {}).get('v52_upper_wick_atr', 0.0)),
            0.0,
        )
        lower_wick = _safe_float(
            sig_meta.get('v60_lower_wick_atr',
            (sig_meta.get('v60_short_meta') or {}).get('v60_lower_wick_atr', 0.0)),
            0.0,
        )

        if failed > int(getattr(cfg, 'V70_MAX_FAILED_BREAKOUTS', 3)):
            flags.update({'v70_enabled': True, 'v70_reason': 'too_many_failed_breakouts', 'v70_score': round(score, 4)})
            return 1.0, flags
        if vol_ratio > _safe_float(getattr(cfg, 'V70_MAX_VOL_RATIO', 4.5), 4.5):
            flags.update({'v70_enabled': True, 'v70_reason': 'volume_spike_too_high', 'v70_score': round(score, 4)})
            return 1.0, flags
        if side_l == 'long' and upper_wick > _safe_float(getattr(cfg, 'V70_MAX_UPPER_WICK_ATR_LONG', 1.35), 1.35):
            flags.update({'v70_enabled': True, 'v70_reason': 'upper_wick_too_high', 'v70_score': round(score, 4)})
            return 1.0, flags
        if side_l == 'short' and lower_wick > _safe_float(getattr(cfg, 'V70_MAX_LOWER_WICK_ATR_SHORT', 1.35), 1.35):
            flags.update({'v70_enabled': True, 'v70_reason': 'lower_wick_too_high', 'v70_score': round(score, 4)})
            return 1.0, flags

        mult = _safe_float(getattr(cfg, 'V70_BASE_RISK_MULT', 1.85), 1.85)
        tier = 'base'
        if score >= _safe_float(getattr(cfg, 'V70_ELITE_SCORE', 0.86), 0.86):
            mult *= _safe_float(getattr(cfg, 'V70_ELITE_EXTRA_MULT', 1.18), 1.18)
            tier = 'elite'
        elif score >= _safe_float(getattr(cfg, 'V70_STRONG_SCORE', 0.72), 0.72):
            mult *= _safe_float(getattr(cfg, 'V70_STRONG_EXTRA_MULT', 1.10), 1.10)
            tier = 'strong'

        if equity_peak and equity and equity_peak > 0 and equity > 0:
            dd_pct = max(0.0, (float(equity_peak) - float(equity)) / float(equity_peak) * 100.0)
            if dd_pct >= _safe_float(getattr(cfg, 'V70_DD_SEVERE_PCT', 11.0), 11.0):
                mult *= _safe_float(getattr(cfg, 'V70_DD_SEVERE_MULT', 0.62), 0.62)
                tier += '_dd_severe'
            elif dd_pct >= _safe_float(getattr(cfg, 'V70_DD_MILD_PCT', 7.0), 7.0):
                mult *= _safe_float(getattr(cfg, 'V70_DD_MILD_MULT', 0.82), 0.82)
                tier += '_dd_mild'

        max_mult = _safe_float(getattr(cfg, 'V70_MAX_EFFECTIVE_MULT', 2.35), 2.35)
        mult = max(1.0, min(max_mult, mult))
        flags.update({'v70_enabled': True, 'v70_scaled': mult > 1.000001, 'v70_mult': round(mult, 6), 'v70_tier': tier, 'v70_score': round(score, 4)})
        return mult, flags
    except Exception as exc:
        flags.update({'v70_enabled': True, 'v70_error': str(exc)})
        return 1.0, flags



def _extract_micro_metrics(sig_meta: dict, side: str) -> dict:
    """Collect stable quality/regime metrics produced by V52/V60 and signal meta."""
    side_l = str(side or '').lower()
    v52m = sig_meta.get('v52_microstructure_meta') or {}
    v60m = sig_meta.get('v60_short_meta') or {}
    score = _safe_float(
        sig_meta.get('v52_score', sig_meta.get('v60_score', v52m.get('v52_score', v60m.get('v60_score', 0.0)))),
        0.0,
    )
    failed = int(_safe_float(sig_meta.get('v52_failed_breakouts', v52m.get('v52_failed_breakouts', 0)), 0.0))
    vol_ratio = _safe_float(sig_meta.get('v52_vol_ratio', v52m.get('v52_vol_ratio', 1.0)), 1.0)
    upper_wick = _safe_float(sig_meta.get('v52_upper_wick_atr', v52m.get('v52_upper_wick_atr', 0.0)), 0.0)
    lower_wick = _safe_float(sig_meta.get('v60_lower_wick_atr', v60m.get('v60_lower_wick_atr', 0.0)), 0.0)
    bad_wick = lower_wick if side_l == 'short' else upper_wick
    return {
        'score': score,
        'failed': failed,
        'vol_ratio': vol_ratio,
        'upper_wick': upper_wick,
        'lower_wick': lower_wick,
        'bad_wick': bad_wick,
        'market_state': str(sig_meta.get('market_state', '') or '').lower(),
        'regime': str(sig_meta.get('regime', '') or '').lower(),
    }


def _v82_quality_risk_multiplier(*, cfg, sig_meta: dict, symbol: str, side: str, trade_type: str) -> tuple[float, dict]:
    """V82: reduce risk on weaker BTC pullbacks, keep strong setups unchanged."""
    flags: dict[str, Any] = {'v82_enabled': False, 'v82_mult': 1.0}
    try:
        if not bool(getattr(cfg, 'V82_BTC_QUALITY_WEIGHTED_RISK_ENABLED', False)):
            return 1.0, flags
        allowed_symbols = {str(x).upper() for x in (getattr(cfg, 'V82_SYMBOLS', ['BTCUSDT']) or ['BTCUSDT'])}
        allowed_types = {str(x).lower() for x in (getattr(cfg, 'V82_TRADE_TYPES', ['pullback']) or ['pullback'])}
        if str(symbol or '').upper() not in allowed_symbols or str(trade_type or '').lower() not in allowed_types:
            return 1.0, flags
        m = _extract_micro_metrics(sig_meta, side)
        score = float(m['score'])
        mult = 1.0
        reasons = []
        if score and score < _safe_float(getattr(cfg, 'V82_LOW_SCORE_CUTOFF', 0.58), 0.58):
            mult *= _safe_float(getattr(cfg, 'V82_LOW_SCORE_RISK_MULT', 0.72), 0.72)
            reasons.append('low_score')
        elif score and score < _safe_float(getattr(cfg, 'V82_MID_SCORE_CUTOFF', 0.68), 0.68):
            mult *= _safe_float(getattr(cfg, 'V82_MID_SCORE_RISK_MULT', 0.88), 0.88)
            reasons.append('mid_score')
        if int(m['failed']) > int(getattr(cfg, 'V82_MAX_FAILED_BREAKOUTS_FOR_FULL_RISK', 2)):
            mult *= _safe_float(getattr(cfg, 'V82_CHOPPY_MICRO_RISK_MULT', 0.82), 0.82)
            reasons.append('failed_breakouts')
        if float(m['bad_wick']) > _safe_float(getattr(cfg, 'V82_MAX_BAD_WICK_ATR_FOR_FULL_RISK', 1.05), 1.05):
            mult *= _safe_float(getattr(cfg, 'V82_CHOPPY_MICRO_RISK_MULT', 0.82), 0.82)
            reasons.append('bad_wick')
        mult = max(_safe_float(getattr(cfg, 'V82_MIN_MULT', 0.50), 0.50), min(1.0, mult))
        flags.update({'v82_enabled': True, 'v82_mult': round(mult, 6), 'v82_score': round(score, 4), 'v82_reasons': ','.join(reasons) if reasons else 'full_risk'})
        return mult, flags
    except Exception as exc:
        flags.update({'v82_enabled': True, 'v82_error': str(exc)})
        return 1.0, flags


def _v83_adaptive_regime_risk_multiplier(*, cfg, sig_meta: dict, symbol: str, side: str, trade_type: str) -> tuple[float, dict]:
    """V83: adjust BTC risk by broader regime quality, not just local signal score."""
    flags: dict[str, Any] = {'v83_enabled': False, 'v83_mult': 1.0}
    try:
        if not bool(getattr(cfg, 'V83_ADAPTIVE_REGIME_RISK_ENABLED', False)):
            return 1.0, flags
        allowed_symbols = {str(x).upper() for x in (getattr(cfg, 'V83_SYMBOLS', ['BTCUSDT']) or ['BTCUSDT'])}
        allowed_types = {str(x).lower() for x in (getattr(cfg, 'V83_TRADE_TYPES', ['pullback']) or ['pullback'])}
        symbol_u = str(symbol or '').upper()
        side_l = str(side or '').lower()
        trade_l = str(trade_type or '').lower()
        if symbol_u not in allowed_symbols or trade_l not in allowed_types or side_l not in {'long', 'short'}:
            return 1.0, flags
        m = _extract_micro_metrics(sig_meta, side_l)
        score = float(m['score'])
        market_state = str(m['market_state'])
        regime = str(m['regime'])
        directional_ok = (side_l == 'long' and regime == 'bull') or (side_l == 'short' and regime == 'bear')
        strong_score = score >= _safe_float(getattr(cfg, 'V83_STRONG_SCORE', 0.78), 0.78)
        elite_score = score >= _safe_float(getattr(cfg, 'V83_ELITE_SCORE', 0.88), 0.88)
        clean_micro = (
            int(m['failed']) <= int(getattr(cfg, 'V83_MAX_FAILED_BREAKOUTS_FOR_BOOST', 1))
            and float(m['bad_wick']) <= _safe_float(getattr(cfg, 'V83_MAX_BAD_WICK_ATR_FOR_BOOST', 0.85), 0.85)
            and float(m['vol_ratio']) <= _safe_float(getattr(cfg, 'V83_MAX_VOL_RATIO_FOR_BOOST', 3.2), 3.2)
        )
        mult = 1.0
        tier = 'neutral'
        # Boost only the cleanest trend-aligned continuation regimes.
        if market_state == 'trend' and directional_ok and clean_micro and elite_score:
            mult *= _safe_float(getattr(cfg, 'V83_ELITE_TREND_MULT', 1.18), 1.18)
            tier = 'elite_trend'
        elif market_state == 'trend' and directional_ok and clean_micro and strong_score:
            mult *= _safe_float(getattr(cfg, 'V83_STRONG_TREND_MULT', 1.10), 1.10)
            tier = 'strong_trend'
        # Clamp risk in transition/chop or direction mismatch.
        if market_state in {str(x).lower() for x in (getattr(cfg, 'V83_REDUCED_RISK_STATES', ['transition', 'range', 'flat', 'chop']) or [])}:
            mult *= _safe_float(getattr(cfg, 'V83_TRANSITION_RISK_MULT', 0.72), 0.72)
            tier = 'transition_clamp' if tier == 'neutral' else tier + '_transition_clamp'
        if not directional_ok:
            mult *= _safe_float(getattr(cfg, 'V83_REGIME_MISMATCH_MULT', 0.80), 0.80)
            tier = 'regime_mismatch' if tier == 'neutral' else tier + '_regime_mismatch'
        if score and score < _safe_float(getattr(cfg, 'V83_WEAK_SCORE_CUTOFF', 0.62), 0.62):
            mult *= _safe_float(getattr(cfg, 'V83_WEAK_SCORE_MULT', 0.78), 0.78)
            tier = 'weak_score' if tier == 'neutral' else tier + '_weak_score'
        min_mult = _safe_float(getattr(cfg, 'V83_MIN_MULT', 0.45), 0.45)
        max_mult = _safe_float(getattr(cfg, 'V83_MAX_MULT', 1.22), 1.22)
        mult = max(min_mult, min(max_mult, mult))
        flags.update({
            'v83_enabled': True,
            'v83_mult': round(mult, 6),
            'v83_tier': tier,
            'v83_score': round(score, 4),
            'v83_market_state': market_state,
            'v83_regime': regime,
            'v83_directional_ok': bool(directional_ok),
        })
        return mult, flags
    except Exception as exc:
        flags.update({'v83_enabled': True, 'v83_error': str(exc)})
        return 1.0, flags

def compute_position_sizing_risk_pct(*, cfg, sig_meta: dict | None, symbol: str, side: str, base_risk_per_trade: float, equity: float = 0.0, equity_peak: float = 0.0) -> tuple[float, dict]:
    """Return effective risk_per_trade after quality and drawdown based sizing.

    Keeps existing signal logic intact and only changes how much equity is risked.
    """
    flags: dict[str, Any] = {}
    risk_pct = max(0.0, _safe_float(base_risk_per_trade, 0.0))
    if risk_pct <= 0:
        return 0.0, flags
    if not bool(getattr(cfg, 'V25_POSITION_SIZING_ENABLED', True)):
        flags['v25_position_sizing_enabled'] = False
        return risk_pct, flags

    symbol = str(symbol or '')
    side = str(side or '').lower()
    sig_meta = sig_meta or {}
    allowed_symbols = set(getattr(cfg, 'V25_POSITION_SIZING_SYMBOLS', ['BTCUSDT', 'ETHUSDT']) or [])
    if allowed_symbols and symbol not in allowed_symbols:
        flags['v25_position_sizing_skipped'] = 'symbol_not_enabled'
        v25_apply_core = False
    v25_apply_core = (side == 'long')
    if not v25_apply_core:
        flags['v25_position_sizing_skipped'] = 'side_not_enabled'

    trade_type = str(sig_meta.get('trade_type', '') or '').lower()
    strong_setup = bool(sig_meta.get('strong_setup', False))
    market_state = str(sig_meta.get('market_state', '') or '').lower()
    regime = str(sig_meta.get('regime', '') or '').lower()
    exec_mult = _safe_float(sig_meta.get('execution_risk_multiplier', sig_meta.get('risk_multiplier', 1.0)), 1.0)
    volume_meta = sig_meta.get('volume_meta') or {}
    impulse_score = _safe_float(volume_meta.get('impulse_score', 0.0), 0.0)

    sizing_mult = 1.0
    tier = 'normal'

    if v25_apply_core and symbol == 'BTCUSDT':
        very_strong_impulse = (
            trade_type == 'impulse'
            and strong_setup
            and regime == 'bull'
            and market_state == 'trend'
            and exec_mult >= _safe_float(getattr(cfg, 'V25_BTC_VERY_STRONG_MIN_EXEC_MULT', 2.3), 2.3)
            and impulse_score >= _safe_float(getattr(cfg, 'V25_BTC_VERY_STRONG_MIN_IMPULSE', 0.92), 0.92)
        )
        strong_impulse = (
            trade_type == 'impulse'
            and strong_setup
            and regime == 'bull'
            and market_state == 'trend'
            and exec_mult >= _safe_float(getattr(cfg, 'V25_BTC_STRONG_MIN_EXEC_MULT', 1.75), 1.75)
            and impulse_score >= _safe_float(getattr(cfg, 'V25_BTC_STRONG_MIN_IMPULSE', 0.82), 0.82)
        )
        strong_continuation = (
            trade_type == 'continuation'
            and strong_setup
            and regime == 'bull'
            and market_state == 'trend'
            and exec_mult >= _safe_float(getattr(cfg, 'V25_BTC_STRONG_CONT_MIN_EXEC_MULT', 2.0), 2.0)
            and impulse_score >= _safe_float(getattr(cfg, 'V25_BTC_STRONG_CONT_MIN_IMPULSE', 0.88), 0.88)
        )
        weak_continuation = (
            trade_type == 'continuation'
            and (
                market_state != 'trend'
                or exec_mult <= _safe_float(getattr(cfg, 'V25_BTC_WEAK_MAX_EXEC_MULT', 1.05), 1.05)
                or impulse_score < _safe_float(getattr(cfg, 'V25_BTC_WEAK_MIN_IMPULSE', 0.72), 0.72)
            )
        )

        if very_strong_impulse:
            sizing_mult = _safe_float(getattr(cfg, 'V25_BTC_VERY_STRONG_RISK_MULT', 1.22), 1.22)
            tier = 'very_strong'
        elif strong_impulse:
            sizing_mult = _safe_float(getattr(cfg, 'V25_BTC_STRONG_RISK_MULT', 1.10), 1.10)
            tier = 'strong_impulse'
        elif strong_continuation:
            sizing_mult = _safe_float(getattr(cfg, 'V25_BTC_STRONG_CONT_RISK_MULT', 1.06), 1.06)
            tier = 'strong_continuation'
        elif weak_continuation:
            sizing_mult = _safe_float(getattr(cfg, 'V25_BTC_WEAK_RISK_MULT', 0.74), 0.74)
            tier = 'weak_continuation'
    elif v25_apply_core and symbol == 'ETHUSDT':
        sizing_mult = _safe_float(getattr(cfg, 'V25_ETH_BASE_RISK_MULT', 0.55), 0.55)
        tier = 'eth_base'
        if strong_setup and regime == 'bull' and market_state == 'trend' and trade_type == 'impulse' and exec_mult >= _safe_float(getattr(cfg, 'V25_ETH_STRONG_MIN_EXEC_MULT', 1.9), 1.9):
            sizing_mult = _safe_float(getattr(cfg, 'V25_ETH_STRONG_RISK_MULT', 0.70), 0.70)
            tier = 'eth_strong'

    dd_pct = 0.0
    if equity_peak and equity and equity_peak > 0 and equity > 0:
        dd_pct = max(0.0, (float(equity_peak) - float(equity)) / float(equity_peak) * 100.0)
        if dd_pct >= _safe_float(getattr(cfg, 'V25_DD_SEVERE_PCT', 10.0), 10.0):
            sizing_mult *= _safe_float(getattr(cfg, 'V25_DD_SEVERE_MULT', 0.72), 0.72)
            flags['v25_dd_state'] = 'severe'
        elif dd_pct >= _safe_float(getattr(cfg, 'V25_DD_MILD_PCT', 5.0), 5.0):
            sizing_mult *= _safe_float(getattr(cfg, 'V25_DD_MILD_MULT', 0.88), 0.88)
            flags['v25_dd_state'] = 'mild'
        else:
            flags['v25_dd_state'] = 'none'

    risk_pct *= sizing_mult

    v70_mult, v70_flags = _v70_aggressive_risk_multiplier(
        cfg=cfg,
        sig_meta=sig_meta,
        symbol=symbol,
        side=side,
        trade_type=trade_type,
        equity=equity,
        equity_peak=equity_peak,
    )
    if v70_mult > 1.0:
        risk_pct *= v70_mult

    v82_mult, v82_flags = _v82_quality_risk_multiplier(
        cfg=cfg,
        sig_meta=sig_meta,
        symbol=symbol,
        side=side,
        trade_type=trade_type,
    )
    if v82_mult < 1.0:
        risk_pct *= v82_mult

    v83_mult, v83_flags = _v83_adaptive_regime_risk_multiplier(
        cfg=cfg,
        sig_meta=sig_meta,
        symbol=symbol,
        side=side,
        trade_type=trade_type,
    )
    risk_pct *= v83_mult

    if bool(v70_flags.get('v70_enabled', False)):
        max_cap = _safe_float(getattr(cfg, 'V70_MAX_RISK_PER_TRADE', getattr(cfg, 'V25_MAX_RISK_PER_TRADE', max(base_risk_per_trade, 0.03))), max(base_risk_per_trade, 0.03))
        min_cap = _safe_float(getattr(cfg, 'V70_MIN_RISK_PER_TRADE', getattr(cfg, 'V25_MIN_RISK_PER_TRADE', 0.0025)), 0.0025)
    else:
        max_cap = _safe_float(getattr(cfg, 'V25_MAX_RISK_PER_TRADE', max(base_risk_per_trade, 0.03)), max(base_risk_per_trade, 0.03))
        min_cap = _safe_float(getattr(cfg, 'V25_MIN_RISK_PER_TRADE', 0.0025), 0.0025)
    risk_pct = max(min_cap, min(max_cap, risk_pct))

    flags.update(v70_flags)
    flags.update(v82_flags)
    flags.update(v83_flags)
    flags.update({
        'v25_position_sizing_enabled': True,
        'v25_tier': tier,
        'v25_sizing_mult': round(float(sizing_mult), 6),
        'v25_risk_pct': round(float(risk_pct), 6),
        'v25_dd_pct': round(float(dd_pct), 4),
    })
    return float(risk_pct), flags
