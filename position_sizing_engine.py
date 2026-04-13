from __future__ import annotations

from typing import Any


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return float(default)


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
        return risk_pct, flags
    if side != 'long':
        flags['v25_position_sizing_skipped'] = 'side_not_enabled'
        return risk_pct, flags

    trade_type = str(sig_meta.get('trade_type', '') or '').lower()
    strong_setup = bool(sig_meta.get('strong_setup', False))
    market_state = str(sig_meta.get('market_state', '') or '').lower()
    regime = str(sig_meta.get('regime', '') or '').lower()
    exec_mult = _safe_float(sig_meta.get('execution_risk_multiplier', sig_meta.get('risk_multiplier', 1.0)), 1.0)
    volume_meta = sig_meta.get('volume_meta') or {}
    impulse_score = _safe_float(volume_meta.get('impulse_score', 0.0), 0.0)

    sizing_mult = 1.0
    tier = 'normal'

    if symbol == 'BTCUSDT':
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
    elif symbol == 'ETHUSDT':
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
    max_cap = _safe_float(getattr(cfg, 'V25_MAX_RISK_PER_TRADE', max(base_risk_per_trade, 0.03)), max(base_risk_per_trade, 0.03))
    min_cap = _safe_float(getattr(cfg, 'V25_MIN_RISK_PER_TRADE', 0.0025), 0.0025)
    risk_pct = max(min_cap, min(max_cap, risk_pct))

    flags.update({
        'v25_position_sizing_enabled': True,
        'v25_tier': tier,
        'v25_sizing_mult': round(float(sizing_mult), 6),
        'v25_risk_pct': round(float(risk_pct), 6),
        'v25_dd_pct': round(float(dd_pct), 4),
    })
    return float(risk_pct), flags
