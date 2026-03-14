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

# ===== Улучшенный volume / momentum фильтр для breakout =====
# Вместо грубого volume > average используем устойчивую комбинацию:
# - volume EMA,
# - медиану объёма,
# - общий impulse score = volume * body * quality close.
BREAKOUT_VOLUME_FILTER_V2_ENABLED = True
BREAKOUT_VOLUME_EMA_SPAN = 20
BREAKOUT_VOLUME_MIN_RATIO_TO_EMA = 1.10
BREAKOUT_VOLUME_MIN_RATIO_TO_MEDIAN = 1.20
BREAKOUT_MIN_VOLUME_IMPULSE_SCORE = 0.55
BREAKOUT_STRONG_VOLUME_IMPULSE_SCORE = 0.95

# ===== Качество пробойной свечи =====
# Пробой должен подтверждаться закрытием уже закрытой свечи, а не одним касанием диапазона.
# Дополнительно фильтруем слабые/шумовые свечи: маленькое тело, закрытие далеко от экстремума,
# а также длинный фитиль в сторону пробоя.
BREAKOUT_CANDLE_QUALITY_ENABLED = True
BREAKOUT_MIN_BODY_ATR = 0.35                # минимальный размер тела пробойной свечи в ATR(LTF)
BREAKOUT_MAX_CLOSE_FROM_EXTREME_PCT = 0.25 # закрытие должно быть в лучших 25% диапазона свечи
BREAKOUT_MAX_WICK_BODY_RATIO = 0.80        # фитиль в сторону пробоя не должен доминировать над телом
BREAKOUT_MAX_WICK_RANGE_RATIO = 0.35       # и не должен занимать слишком большую часть всей свечи


# ===== MTF (H1 + M15) ПАРАМЕТРЫ =====
# Длина диапазона на LTF (M15) для поиска пробоя
MTF_LTF_LOOKBACK = 60

# RSI-фильтры для MTF-входа (вариант B, но чуть мягче)
MTF_RSI_LONG_MIN = 50.0
MTF_RSI_LONG_MAX = 85.0
MTF_RSI_SHORT_MIN = 15.0
MTF_RSI_SHORT_MAX = 55.0

# Дополнительная адаптация RSI под силу объёма/импульса breakout-свечи.
BREAKOUT_RSI_ADAPT_BY_VOLUME_ENABLED = True
BREAKOUT_RSI_WEAK_VOLUME_TIGHTEN = 2.5
BREAKOUT_RSI_STRONG_VOLUME_LOOSEN = 1.5

# Минимальная волатильность на LTF (M15) в доле цены
# Пример: 0.0002 = 0.02% (слишком тихий рынок не торгуем)
LTF_ATR_MIN_PCT = 0.0002
# Максимальное время жизни позиции в барах LTF (для MTF-стратегии)
# Пример: 96 баров M15 ≈ 1 день
MTF_MAX_BARS_IN_POSITION = 192

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

# Адаптивный порог дрейфа: во "вкусном" тренде можно слегка смещать минимальное требуемое
# суточное движение, чтобы не выкидывать хорошие, но чуть менее мощные тренды.
# Включено по умолчанию, можно отключить для более консервативного поведения.
MTF_DRIFT_ADAPTIVE_ENABLED = True

# Насколько снижаем минимальный дрейф в сильном тренде (0.7 = на 30% ниже базового порога).
MTF_DRIFT_MIN_LOOSEN_FACTOR = 0.7

# Запас по ADX сверх BREAKOUT_ADX_MIN, при котором считаем тренд достаточно сильным
# для ослабления порога дрейфа.
MTF_STRONG_TREND_ADX_MARGIN = 5.0


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


# ===== Symbol-specific params (Step 8) =====
# Ключевые параметры стратегии можно переопределять по каждому символу,
# чтобы не использовать один и тот же профиль для BTC и более волатильных альтов.
SYMBOL_PARAM_OVERRIDES = {
    "BTCUSDT": {
        "BREAKOUT_BUFFER_PCT": 0.0008,
        "MTF_LTF_LOOKBACK": 72,
        "BREAKOUT_VOLUME_MIN_RATIO_TO_EMA": 1.05,
        "BREAKOUT_VOLUME_MIN_RATIO_TO_MEDIAN": 1.10,
        "MTF_RSI_LONG_MIN": 52.0,
        "MTF_RSI_LONG_MAX": 82.0,
        "MTF_RSI_SHORT_MIN": 18.0,
        "MTF_RSI_SHORT_MAX": 52.0,
        "ATR_SL_MULT": 5.5,
        "POSITION_TP1_ATR_MULT": 7.5,
        "POSITION_TRAILING_ATR_MULT": 4.8,
    },
    "ETHUSDT": {
        "BREAKOUT_BUFFER_PCT": 0.0010,
        "MTF_LTF_LOOKBACK": 64,
        "BREAKOUT_VOLUME_MIN_RATIO_TO_EMA": 1.08,
        "BREAKOUT_VOLUME_MIN_RATIO_TO_MEDIAN": 1.15,
        "MTF_RSI_LONG_MIN": 51.0,
        "MTF_RSI_LONG_MAX": 84.0,
        "MTF_RSI_SHORT_MIN": 16.0,
        "MTF_RSI_SHORT_MAX": 54.0,
        "ATR_SL_MULT": 5.2,
        "POSITION_TP1_ATR_MULT": 7.2,
        "POSITION_TRAILING_ATR_MULT": 4.6,
    },
    "SOLUSDT": {
        "BREAKOUT_BUFFER_PCT": 0.0013,
        "MTF_LTF_LOOKBACK": 56,
        "BREAKOUT_VOLUME_MIN_RATIO_TO_EMA": 1.15,
        "BREAKOUT_VOLUME_MIN_RATIO_TO_MEDIAN": 1.25,
        "MTF_RSI_LONG_MIN": 54.0,
        "MTF_RSI_LONG_MAX": 86.0,
        "MTF_RSI_SHORT_MIN": 14.0,
        "MTF_RSI_SHORT_MAX": 53.0,
        "ATR_SL_MULT": 5.0,
        "POSITION_TP1_ATR_MULT": 6.8,
        "POSITION_TRAILING_ATR_MULT": 4.3,
    },
    "BNBUSDT": {
        "BREAKOUT_BUFFER_PCT": 0.0011,
        "MTF_LTF_LOOKBACK": 62,
        "BREAKOUT_VOLUME_MIN_RATIO_TO_EMA": 1.10,
        "BREAKOUT_VOLUME_MIN_RATIO_TO_MEDIAN": 1.18,
        "MTF_RSI_LONG_MIN": 52.0,
        "MTF_RSI_LONG_MAX": 84.0,
        "MTF_RSI_SHORT_MIN": 16.0,
        "MTF_RSI_SHORT_MAX": 54.0,
        "ATR_SL_MULT": 5.1,
        "POSITION_TP1_ATR_MULT": 7.0,
        "POSITION_TRAILING_ATR_MULT": 4.5,
    },
    "AVAXUSDT": {
        "BREAKOUT_BUFFER_PCT": 0.0015,
        "MTF_LTF_LOOKBACK": 52,
        "BREAKOUT_VOLUME_MIN_RATIO_TO_EMA": 1.18,
        "BREAKOUT_VOLUME_MIN_RATIO_TO_MEDIAN": 1.28,
        "MTF_RSI_LONG_MIN": 55.0,
        "MTF_RSI_LONG_MAX": 87.0,
        "MTF_RSI_SHORT_MIN": 13.0,
        "MTF_RSI_SHORT_MAX": 52.0,
        "ATR_SL_MULT": 4.8,
        "POSITION_TP1_ATR_MULT": 6.5,
        "POSITION_TRAILING_ATR_MULT": 4.1,
    },
}


def get_symbol_param(symbol: str, param_name: str, default=None):
    """Возвращает параметр с учётом overrides по символу."""
    try:
        symbol = str(symbol or "").upper()
        overrides = globals().get("SYMBOL_PARAM_OVERRIDES", {}) or {}
        if symbol and symbol in overrides and param_name in overrides[symbol]:
            return overrides[symbol][param_name]
    except Exception:
        pass
    return globals().get(param_name, default)


def get_symbol_param_float(symbol: str, param_name: str, default: float) -> float:
    try:
        return float(get_symbol_param(symbol, param_name, default))
    except Exception:
        return float(default)


def get_symbol_param_int(symbol: str, param_name: str, default: int) -> int:
    try:
        return int(get_symbol_param(symbol, param_name, default))
    except Exception:
        return int(default)


# ===== Фильтр “живого” HTF-тренда =====
# Даже если EMA формально выстроены, не входим, если старший тренд уже выдыхается:
# проверяем наклон EMA50/EMA200 и достаточную дистанцию между EMA20 и EMA50.
HTF_TREND_VITALITY_ENABLED = True
HTF_EMA_SLOPE_LOOKBACK_BARS = 8          # сколько последних M15-баров брать для оценки наклона HTF EMA
HTF_EMA50_MIN_SLOPE_PCT = 0.0008         # минимальный наклон EMA50 относительно текущего значения (0.08%)
HTF_EMA200_MIN_SLOPE_PCT = 0.00025       # минимальный наклон EMA200 относительно текущего значения (0.025%)
HTF_EMA20_EMA50_MIN_DIST_PCT = 0.0010    # минимальная дистанция между EMA20 и EMA50 (0.10% от цены)

# ===== Фильтр перегретого движения на HTF =====
# Не входим, если цена уже слишком далеко убежала от HTF EMA20/EMA50.
# Дистанция измеряется в ATR(H1), чтобы фильтр был адаптивным к волатильности.
HTF_OVEREXTENSION_FILTER_ENABLED = True
HTF_MAX_DIST_FROM_EMA20_ATR = 1.6      # максимум, насколько цена может отстоять от HTF EMA20
HTF_MAX_DIST_FROM_EMA50_ATR = 2.4      # максимум, насколько цена может отстоять от HTF EMA50


# ===== Cooldown после стопа / серии неудачных входов =====
# Защита от пилы: после убыточного stop-loss по конкретному symbol + direction
# не разрешаем сразу переоткрывать ту же идею. При серии одинаковых стопов
# можно дополнительно увеличить паузу.
ENTRY_COOLDOWN_AFTER_STOP_ENABLED = True
ENTRY_COOLDOWN_AFTER_STOP_BARS = 8               # базовая пауза после убыточного стопа
ENTRY_COOLDOWN_STREAK_THRESHOLD = 2              # с какого подряд стопа считать серию
ENTRY_COOLDOWN_STREAK_EXTRA_BARS = 8             # доп. пауза поверх базовой при серии стопов
ENTRY_COOLDOWN_RESET_ON_NON_LOSS_EXIT = True     # сбрасывать серию после неубыточного/прибыльного выхода
ENTRY_COOLDOWN_BAR_SECONDS = 15 * 60             # M15 = 900 секунд



# ===== BTC regime filter для альтов =====
# Для альтов торгуем только в сторону старшего режима BTC.
# LONG по альтам разрешаем только если BTC HTF bullish,
# SHORT — только если BTC HTF bearish.
BTC_REGIME_FILTER_ENABLED = True
BTC_REGIME_FILTER_SYMBOL = "BTCUSDT"
BTC_REGIME_ALT_SYMBOLS = ["ETHUSDT", "SOLUSDT", "BNBUSDT", "AVAXUSDT"]

# Доп. ограничение: сколько однонаправленных альт-сделок можно держать одновременно.
# 0 = без ограничения.
BTC_REGIME_MAX_SAME_SIDE_ALT_POSITIONS = 2


# ===== Session / time filter =====
# Не торгуем в наименее ликвидные часы.
# Окна задаются в UTC в формате [(start_hour, end_hour), ...], где start включительно, end не включительно.
# Пример: (6, 23) => можно торговать с 06:00:00 до 22:59:59 UTC.
SESSION_TIME_FILTER_ENABLED = True
SESSION_TIME_FILTER_TIMEZONE = "UTC"
SESSION_ALLOWED_WINDOWS = [
    (6, 23),
]


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
STRATEGY_VERSION = _os.getenv("STRATEGY_VERSION", "mtf_breakout_step7_volume_momentum")

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


# ===== Step 6. Улучшенное сопровождение позиции =====
# Цель: стабильнее забирать импульс и меньше отдавать накопленную прибыль назад.
# 1) TP1 делаем ближе, чтобы чаще фиксировать часть импульса;
# 2) перевод в BE включаем раньше и с небольшим запасом на комиссии;
# 3) трейлинг ведём от лучшей достигнутой цены, а не от каждого нового close.
POSITION_MANAGEMENT_V2_ENABLED = True
POSITION_TP1_ATR_MULT = 7.0
POSITION_TP1_CLOSE_FRACTION = 0.40
POSITION_BE_TRIGGER_ATR = 3.0
POSITION_BE_OFFSET_ATR = 0.10
POSITION_TRAILING_ACTIVATION_ATR = 7.0
POSITION_TRAILING_ATR_MULT = 4.5
POSITION_TRAILING_STEP_ATR = 0.25
