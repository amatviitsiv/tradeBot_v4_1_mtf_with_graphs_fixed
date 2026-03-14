# Step 3 — Overheated move filter

Добавлен фильтр перегретого движения на HTF:

- считаем дистанцию текущей цены до `HTF_EMA20` и `HTF_EMA50` в единицах `HTF_ATR`;
- для `LONG` не входим, если цена уже слишком высоко над EMA20/EMA50;
- для `SHORT` не входим, если цена уже слишком низко под EMA20/EMA50;
- пороги вынесены в `config.py` и настраиваются отдельно.

Новые параметры:

- `HTF_OVEREXTENSION_FILTER_ENABLED = True`
- `HTF_MAX_DIST_FROM_EMA20_ATR = 1.6`
- `HTF_MAX_DIST_FROM_EMA50_ATR = 2.4`
