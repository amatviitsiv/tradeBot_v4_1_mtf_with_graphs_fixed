# Step 2 — HTF trend vitality filter

Что добавлено:
- фильтр «живого» тренда на HTF перед входом в breakout;
- проверка наклона HTF EMA50;
- проверка наклона HTF EMA200;
- минимальная дистанция между HTF EMA20 и HTF EMA50;
- блокировка входов, если HTF-тренд слишком плоский.

Новые параметры в `config.py`:
- `HTF_TREND_VITALITY_ENABLED = True`
- `HTF_EMA_SLOPE_LOOKBACK_BARS = 8`
- `HTF_EMA50_MIN_SLOPE_PCT = 0.0008`
- `HTF_EMA200_MIN_SLOPE_PCT = 0.00025`
- `HTF_EMA20_EMA50_MIN_DIST_PCT = 0.0010`

Логика:
- для LONG требуется положительный минимальный наклон EMA50 и EMA200;
- для SHORT требуется отрицательный минимальный наклон EMA50 и EMA200;
- если EMA20 и EMA50 слишком близко друг к другу, новый вход блокируется как «плоский / выдыхающийся» тренд.
