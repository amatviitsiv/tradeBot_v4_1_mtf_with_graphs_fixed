# Step 5 — BTC regime filter для альтов

Что добавлено:
- для `ETHUSDT/SOLUSDT/BNBUSDT/AVAXUSDT` long-сигналы разрешаются только если `BTC` на HTF находится в bullish-режиме (`EMA20 > EMA50 > EMA200`);
- short-сигналы по тем же альтам разрешаются только если `BTC` на HTF находится в bearish-режиме (`EMA20 < EMA50 < EMA200`);
- в live-runner и backtester добавлено подтягивание `BTC_HTF_*` колонок в DataFrame каждого символа;
- добавлено опциональное ограничение числа однонаправленных альт-сделок через `BTC_REGIME_MAX_SAME_SIDE_ALT_POSITIONS`.

Новые параметры `config.py`:
- `BTC_REGIME_FILTER_ENABLED = True`
- `BTC_REGIME_FILTER_SYMBOL = "BTCUSDT"`
- `BTC_REGIME_ALT_SYMBOLS = ["ETHUSDT", "SOLUSDT", "BNBUSDT", "AVAXUSDT"]`
- `BTC_REGIME_MAX_SAME_SIDE_ALT_POSITIONS = 2`

Замечание:
- если BTC-HTF данные временно недоступны, фильтр для альтов будет блокировать входы, а не пропускать их вслепую.
