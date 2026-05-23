"""Static maps for MTF signal flow metadata.

These constants are descriptive only; they do not change runtime trading logic.
They provide one place to inspect which trade types and stages are active.
"""

ENTRY_TRADE_TYPE_PATHS = {
    "mean_reversion": "check_v52_mean_reversion_entry",
    "fakeout": "check_fakeout_reversal_entry",
    "liquidity_reversal": "check_fakeout_reversal_entry",
    "range": "range_signal",
    "btc_exhaustion": "check_btc_exhaustion_short",
    "impulse": "check_impulse_breakout",
    "continuation": "check_continuation_entry",
    "cont_compression": "check_continuation_compression_entry",
    "pullback": "check_pullback_trend_entry",
}

SIGNAL_FLOW_STAGE_MAP = {
    "time_gate": ["is_allowed_trading_time"],
    "market_regime": [
        "classify_market_state",
        "check_htf_trend_vitality",
        "check_htf_overextension",
        "_check_directional_regime_gate",
    ],
    "specialized_entries": [
        "check_v52_mean_reversion_entry",
        "range_signal",
        "check_fakeout_reversal_entry",
        "_check_btc_liquidity_reversal",
        "check_btc_exhaustion_short",
    ],
    "directional_entries": [
        "check_impulse_breakout",
        "check_continuation_entry",
        "check_continuation_compression_entry",
        "check_pullback_trend_entry",
    ],
    "alt_filters": [
        "_is_alt_symbol",
        "_alt_strong_setup",
        "_alt_setup_tier",
        "_relax_alt_filters",
        "_alt_upgrade_gate",
        "alt_regime_filter_helper",
    ],
    "risk_stack": [
        "apply_directional_setup_scaling_helper",
        "apply_v7_direct_boost_helper",
        "apply_v78_selective_risk_reduction_helper",
        "apply_v80_alt_engine_upgrade_helper",
        "_apply_v80_short_control",
        "_apply_v81_short_adjustment",
    ],
    "inline_suppression": [
        "_apply_v85_inline_short_suppression",
        "_apply_v86_inline_long_suppression",
    ],
    "final_signal": ["_set_signal"],
}
