# Step 1 — breakout entry quality upgrade

Implemented changes:
- entry stays based on confirmed candle close beyond the range
- added breakout candle quality filter
  - minimum candle body relative to ATR
  - close must be near candle extreme
  - wick-dominant breakout candles are rejected

Main knobs in `config.py`:
- `BREAKOUT_CANDLE_QUALITY_ENABLED`
- `BREAKOUT_MIN_BODY_ATR`
- `BREAKOUT_MAX_CLOSE_FROM_EXTREME_PCT`
- `BREAKOUT_MAX_WICK_BODY_RATIO`
- `BREAKOUT_MAX_WICK_RANGE_RATIO`
