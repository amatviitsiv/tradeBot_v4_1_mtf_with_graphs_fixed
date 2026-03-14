# Step 4 — Cooldown после стопа / серии неудачных входов

Что добавлено:
- cooldown после убыточного `stop_loss` по конкретному `symbol + direction`;
- блокировка повторного входа в ту же сторону на `N` баров;
- поддержка серии одинаковых стопов: при достижении порога серия даёт увеличенную паузу;
- сохранение cooldown/streak в `state_manager`, чтобы live-бот не забывал паузу после рестарта;
- такая же логика добавлена в `backtester_full.py`, чтобы поведение live и backtest было ближе.

Новые параметры `config.py`:
- `ENTRY_COOLDOWN_AFTER_STOP_ENABLED`
- `ENTRY_COOLDOWN_AFTER_STOP_BARS`
- `ENTRY_COOLDOWN_STREAK_THRESHOLD`
- `ENTRY_COOLDOWN_STREAK_EXTRA_BARS`
- `ENTRY_COOLDOWN_RESET_ON_NON_LOSS_EXIT`
- `ENTRY_COOLDOWN_BAR_SECONDS`
