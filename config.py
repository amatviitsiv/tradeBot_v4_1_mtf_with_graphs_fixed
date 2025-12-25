STRATEGY_NAME = "mtf_breakout"

# config.py
"""
Глобальные настройки бота (актуально: только фьючерсы Binance USDT-M).
Текущая конфигурация рассчитана на:

- торговлю фьючерсами USDT-M (без спотового режима),
- multi-asset: BTC, ETH, SOL, BNB, AVAX,
- переключение paper / real одним флагом,
- работу стратегий:
  * MTF Breakout (H1 тренд + M15 вход).
"""



# ===== РЕЖИМ ТОРГОВЛИ =====
# False = paper trading (без реальных ордеров)
# True  = реальная торговля (нужны ключи и аккуратность!)
REAL_TRADING = False

EQUITY_NOTIFY_INTERVAL = 600
# API ключи для Binance (заполняешь ТОЛЬКО если REAL_TRADING = True)
API_KEY = "cOzVm76AAqWwFe6vvHcoZ2wB1mNhJg01DJ9GpA5ZXq12nBpGmsJdwMoXTyRVA9Hw"
API_SECRET = "O4o0oORj7wloy6DfeuWbcOVUy9SfV8z94gSyBQF63kHyQkPPJDXlZqYmuKwmKcfX"

FUTURES_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "AVAXUSDT"]
# ===== СПИСОК ПАР ДЛЯ ТОРГОВЛИ =====

# config.py (важные куски)

INITIAL_BALANCE_USDT = 5000

TIMEFRAME = "1m"
HISTORY_LIMIT = 300

CAPITAL_ALLOCATION_PER_SYMBOL = 0.4   # 40% от equity на символ

TAKE_PROFIT_PCT = 0.004   # 0.4%
STOP_LOSS_PCT   = 0.002   # 0.2%

# Трейлинг можно оставить как было, если он у тебя уже настроен
TRAILING_ACTIVATION_PCT = 0.01
TRAILING_STOP_PCT       = 0.005

# Пирамидинг пока выключим — сначала добьёмся положительной базовой стратегии
PYRAMID_ENABLED   = False
PYRAMID_STEP_PCT  = 0.01
PYRAMID_ADD_PCT   = 0.5
PYRAMID_MAX_MULT  = 3.0

# Индикаторы тренда
SMA_TREND_PERIOD = 200
EMA_FAST = 5
EMA_SLOW = 13
ATR_PERIOD = 14
ADX_PERIOD = 14

ADX_TREND_THRESHOLD = 15.0        # минимальный ADX, чтобы считать рынок трендовым
ANTI_CHOP_MIN_ATR_PCT = 0.0005    # фильтр "слишком тихого" рынка


# === ВОЛАТИЛЬНОСТНЫЙ BREAKOUT ===
BREAKOUT_LOOKBACK = 12          # сколько свечей смотреть назад
BREAKOUT_BUFFER_PCT = 0.0010     # на сколько выше high/ниже low должен уйти пробой (0.1%)


# ===== КОМИССИИ =====
# Комиссия спота (пример: 0.1% = 0.001)
SPOT_FEE_RATE = 0.001
# Комиссия фьючерсов (пример: 0.04% = 0.0004)
FUTURES_FEE_RATE = 0.0004

# Риск на сделку (если захочешь считать через стоп)
RISK_PER_TRADE = 0.01                 # 1% от equity

# ===== ФЬЮЧЕРСЫ =====
# Базовое плечо. В коде можно будет делать dynamic_leverage(equity)
FUTURES_LEVERAGE_DEFAULT = 5
FUTURES_NOTIONAL_LIMIT = 2000.0  # максимальный размер позиции в USDT (для безопасности)

# ===== ЛОГИКА ОПРОСА =====
# Как часто перезапускаем цикл оценки стратегии (в секундах)
POLL_INTERVAL = 30.0

# Раз в сколько минут слать апдейт по equity (0 = выключить)
TELEGRAM_EQUITY_INTERVAL_MIN = 5

# ===== ЛОГИ =====
LOG_LEVEL = "INFO"
LOG_FILE = "bot.log"
TRADES_LOG_FILE = "trades.log"
ERROR_LOG_FILE = "errors.log"
LOG_MAX_BYTES = 5 * 1024 * 1024
LOG_BACKUP_COUNT = 3
# === Trend strategy params (Dual Trend Bot) ===


# Максимальное количество добавочных входов поверх первой позиции
PYRAMID_MAX_LAYERS = 2              # напр: 0 = отключено, 1–3 = разумно

# Размер каждого добавочного входа относительно исходного notional
PYRAMID_SCALE = 0.5                 # 0.5 = каждый догон на половину первоначального объёма

# ATR-фильтр волатильности (% от цены)
ATR_MIN_PCT = 0.1     # слишком тихий рынок ниже этого
ATR_MAX_PCT = 3.0     # слишком волатильный рынок выше этого

# RSI-зоны для входа
RSI_LONG_MIN = 60.0
RSI_LONG_MAX = 80.0
RSI_SHORT_MAX = 40.0
RSI_SHORT_MIN = 20.0

# ===== ЛИМИТЫ ПО КОЛИЧЕСТВУ ПОЗИЦИЙ =====
# Максимальное количество одновременно открытых фьючерсных позиций
MAX_OPEN_POSITIONS = 3

# ===== ATR-базированные уровни SL/TP/трейлинга (для бэктестера и стратегий) =====
# Стоп-лосс: entry_price ± ATR * ATR_SL_MULT
# Для крипты на трендовых системах разумно держать SL шире, чтобы не выбивало шумом.
ATR_SL_MULT = 5.0

# Первая цель по прибыли: entry_price ± ATR * ATR_TP_MULT_1
# Здесь фиксируем часть позиции и включаем трейлинг.
ATR_TP_MULT_1 = 10.0

# Вторая цель по прибыли (можно использовать в будущем для частичного выхода)
ATR_TP_MULT_2 = 12.0

# Множитель для трейлингового стопа относительно ATR
ATR_TS_MULT = 5.0


BREAKOUT_VOLUME_MULT = 1.5  # volume > MA(volume) * BREAKOUT_VOLUME_MULT
BREAKOUT_ADX_MIN = 20.0      # минимальный ADX для подтверждения пробоя


# ===== MTF (H1 + M15) ПАРАМЕТРЫ =====
# Длина диапазона на LTF (M15) для поиска пробоя
MTF_LTF_LOOKBACK = 60

# RSI-фильтры для MTF-входа (вариант B, но чуть мягче)
MTF_RSI_LONG_MIN = 50.0
MTF_RSI_LONG_MAX = 85.0
MTF_RSI_SHORT_MIN = 15.0
MTF_RSI_SHORT_MAX = 55.0

# Минимальная волатильность на LTF (M15) в доле цены
# Пример: 0.0002 = 0.02% (слишком тихий рынок не торгуем)
LTF_ATR_MIN_PCT = 0.0002
# Максимальное время жизни позиции в барах LTF (для MTF-стратегии)
# Пример: 96 баров M15 ≈ 1 день
MTF_MAX_BARS_IN_POSITION = 96

# Динамический коэффициент для lookback по волатильности:
# При высокой волатильности (atr_pct_h > MTF_ATR_HIGH_VOL_PCT) lookback уменьшается,
# при низкой (atr_pct_h < MTF_ATR_LOW_VOL_PCT) увеличивается.
MTF_ATR_LOW_VOL_PCT = 0.003   # 0.3% от цены
MTF_ATR_HIGH_VOL_PCT = 0.015  # 1.5% от цены
MTF_LOOKBACK_MIN = 40         # минимальный lookback на LTF
MTF_LOOKBACK_MAX = 80         # максимальный lookback на LTF

# Ограничение по количеству одновременных позиций в MTF-режиме
# (может быть ниже глобального MAX_OPEN_POSITIONS при высокой волатильности рынка)
MTF_MAX_OPEN_POSITIONS = 3

# ===== ФИЛЬТРЫ РЫНКА ДЛЯ MTF-СТРАТЕГИИ =====
# Простая защита от "взрывного флэта" по ATR на HTF (H1).
# Если относительный ATR на H1 выше порога, то новые входы по MTF-стратегии отключаются.
# Порог задаётся в доле от цены (0.02 = 2%).
MTF_ATR_SUPER_HIGH_PCT = 0.02

# Включить/выключить фильтр "взрывного флэта" для MTF-стратегии.
MTF_DISABLE_VOLATILE_FLAT = True

# Drift-фильтр: минимальное суточное (96 баров M15) движение цены, при котором имеет смысл
# считать рынок трендовым. Если дрейф меньше этого порога, MTF-стратегия не торгует.
MTF_DRIFT_LOOKBACK_BARS = 96       # ~1 день на M15
MTF_DRIFT_MIN_PCT = 0.006          # 0.3% движения цены за сутки

# Порог "сильного тренда" по дрейфу. Нужен для адаптивных фильтров (RSI/lookback).
MTF_DRIFT_STRONG_TREND_PCT = 0.01  # 1% и более за сутки считаем сильным трендом

# Дополнительное ужесточение RSI-фильтра при слабом тренде (в пунктах RSI).
MTF_RSI_LONG_TIGHTEN = 5.0   # на сколько повысить нижнюю границу RSI для LONG
MTF_RSI_SHORT_TIGHTEN = 5.0  # на сколько понизить верхнюю границу RSI для SHORT

# ===== Дополнительный фильтр волатильной пилы на LTF =====
# Множитель для порога "низкого" наклона при высокой волатильности.
# При slope_abs < LTF_SLOPE_MIN_ABS * LTF_VOLATILE_SLOPE_FACTOR и высокой ATR
# считаем, что это волатильная пила без направления и пропускаем такие сигналы.
LTF_VOLATILE_SLOPE_FACTOR = 5.0


# HTF volatile-trendless filter
HTF_VOLATILE_ATR_PCT=0.004
HTF_VOLATILE_DRIFT_PCT=0.006
HTF_VOLATILE_ADX_MAX=22
HTF_DRIFT_LOOKBACK_BARS = 16

# ===== Ограничение торговли при глубокой просадке (DD cooldown) =====
# Если текущая просадка от пика эквити превышает DD_COOLDOWN_PCT,
# стратегия перестаёт открывать новые позиции на ближайшие DD_COOLDOWN_BARS баров.
DD_COOLDOWN_ENABLE = False
DD_COOLDOWN_PCT = 12.0       # % просадки от пика, после которой включаем "режим восстановления"
DD_COOLDOWN_BARS = 300       # на сколько баров вперёд блокировать новые входы

# ===== Runtime environment / credentials =====
# Настройки окружения вычитываются из переменных среды, чтобы ключи и токены
# не лежали в коде / репозитории. Для локального запуска удобно использовать .env.

import os as _os

# paper / real (можно переопределить переменной BOT_MODE)
BOT_MODE = _os.getenv("BOT_MODE", "paper").lower()

# Ключи к Binance (USDT-M futures). ОБЯЗАТЕЛЬНО задавать через окружение / .env
BINANCE_API_KEY = _os.getenv("BINANCE_API_KEY", "cOzVm76AAqWwFe6vvHcoZ2wB1mNhJg01DJ9GpA5ZXq12nBpGmsJdwMoXTyRVA9Hw")
BINANCE_API_SECRET = _os.getenv("BINANCE_API_SECRET", "O4o0oORj7wloy6DfeuWbcOVUy9SfV8z94gSyBQF63kHyQkPPJDXlZqYmuKwmKcfX")

# Файл состояния (его можно переопределять, если нужно вести несколько ботов)
STATE_FILE = _os.getenv("BOT_STATE_FILE", "bot_state.json")

# Версия стратегии/конфига — можно использовать в логах и state
STRATEGY_VERSION = _os.getenv("STRATEGY_VERSION", "mtf_breakout_prod_prep_1")

# ===== Telegram-уведомления =====
# Если TELEGRAM_ENABLED=1 и заданы токен и chat_id, бот будет слать уведомления.
TELEGRAM_ENABLED = _os.getenv("TELEGRAM_ENABLED", "1") == "1"
TELEGRAM_BOT_TOKEN = _os.getenv("TELEGRAM_BOT_TOKEN", "8269222363:AAF6vM7-ydXHJjBiq42MDK4jWn5sYbIub7w")
TELEGRAM_CHAT_ID = _os.getenv("TELEGRAM_CHAT_ID", "351630680")



# ===== Protective layer (Step9) =====
# Жёсткий лимит по просадке от пика equity (0 = выключено)
HARD_MAX_DRAWDOWN_PCT = float(_os.getenv("HARD_MAX_DRAWDOWN_PCT", "0"))

# Лимит сделок в час (по открытиям позиций); 0 = без ограничения
MAX_TRADES_PER_HOUR = int(_os.getenv("MAX_TRADES_PER_HOUR", "20"))

# Минимальный интервал между повторными входами по одному и тому же символу (анти-луп), сек
MIN_REOPEN_INTERVAL_SEC = int(_os.getenv("MIN_REOPEN_INTERVAL_SEC", "300"))

# Максимально допустимая "тишина" по WebSocket (сек); 0 = не проверять
WS_STALE_SECONDS = int(_os.getenv("WS_STALE_SECONDS", "900"))

# Отключать ли торговлю при рассинхронизации позиций биржа/локальный стейт
POSITION_MISMATCH_DISABLE = _os.getenv("POSITION_MISMATCH_DISABLE", "1") == "1"

# Логировать сырые сообщения WebSocket (0/1)
WS_DEBUG = _os.getenv("WS_DEBUG", "0") == "1"

# ===== Strategy debug (Step11) =====
STRATEGY_DEBUG = _os.getenv('STRATEGY_DEBUG', '1') == '1'

# ===== Live preload history (Step11.1) =====
PRELOAD_HISTORY = _os.getenv('PRELOAD_HISTORY', '1') == '1'
PRELOAD_15M_LIMIT = int(_os.getenv('PRELOAD_15M_LIMIT', '500'))
PRELOAD_1H_LIMIT  = int(_os.getenv('PRELOAD_1H_LIMIT', '200'))
