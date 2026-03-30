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
import os as _os

API_KEY = "cOzVm76AAqWwFe6vvHcoZ2wB1mNhJg01DJ9GpA5ZXq12nBpGmsJdwMoXTyRVA9Hw"
API_SECRET = "O4o0oORj7wloy6DfeuWbcOVUy9SfV8z94gSyBQF63kHyQkPPJDXlZqYmuKwmKcfX"

FUTURES_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "AVAXUSDT"]
# ===== СПИСОК ПАР ДЛЯ ТОРГОВЛИ =====

# config.py (важные куски)

INITIAL_BALANCE_USDT = 5000

TIMEFRAME = "1m"
HISTORY_LIMIT = 300


# Индикаторы тренда
SMA_TREND_PERIOD = 200
EMA_FAST = 5
EMA_SLOW = 13
EMA_FAST_PERIOD = EMA_FAST
EMA_SLOW_PERIOD = EMA_SLOW
ATR_PERIOD = 14
ADX_PERIOD = 14

ADX_TREND_THRESHOLD = 15.0        # минимальный ADX, чтобы считать рынок трендовым
ANTI_CHOP_MIN_ATR_PCT = 0.0005    # фильтр "слишком тихого" рынка

# ===== Дополнительный market-regime фильтр для новых рыночных режимов =====
# Используется как финальный фильтр перед входом: если HTF-тренд слишком слабый
# или волатильность недостаточна, breakout-сигналы пропускаются.
MARKET_REGIME_FILTER_ENABLED = True
MARKET_REGIME_REQUIRE_TREND_STATE = True
MARKET_REGIME_MIN_HTF_ADX = 18.0
MARKET_REGIME_MIN_HTF_ATR_PCT = 0.0012
MARKET_REGIME_MIN_DRIFT_PCT = 0.0040



# === ВОЛАТИЛЬНОСТНЫЙ BREAKOUT ===
BREAKOUT_LOOKBACK = 12          # сколько свечей смотреть назад
BREAKOUT_BUFFER_PCT = 0.0010     # на сколько выше high/ниже low должен уйти пробой (0.1%)


# ===== КОМИССИИ =====
# Комиссия спота (пример: 0.1% = 0.001)
SPOT_FEE_RATE = 0.001
# Комиссия фьючерсов (пример: 0.04% = 0.0004)
FUTURES_FEE_RATE = 0.0004

# Риск на сделку (если захочешь считать через стоп)
RISK_PER_TRADE = 0.02                 # 2% от equity

# ===== ФЬЮЧЕРСЫ =====
# Базовое плечо. В коде можно будет делать dynamic_leverage(equity)
FUTURES_LEVERAGE_DEFAULT = 5

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
MTF_MAX_BARS_IN_POSITION = 128

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
        "POSITION_TP1_ATR_MULT": 8.6,
        "POSITION_TP1_CLOSE_FRACTION": 0.33,
        "MARKET_REGIME_MIN_HTF_ADX": 20.0,
        "MARKET_REGIME_MIN_HTF_ATR_PCT": 0.0014,
        "MARKET_REGIME_MIN_DRIFT_PCT": 0.0045,
        "TREND_QUALITY_COMBO_MIN_HTF_ADX": 27.0,
        "TREND_QUALITY_COMBO_MIN_DRIFT_PCT": 0.0064,
        "CHOP_FILTER_MAX_EMA20_CROSSES": 3,
        "POSITION_TRAILING_ACTIVATION_ATR": 8.6,
        "POSITION_TRAILING_ATR_MULT": 5.8,
        "POSITION_TRAILING_STEP_ATR": 0.45,
        "POSITION_TP1_ATR_MULT_TREND": 9.2,
        "POSITION_TP1_CLOSE_FRACTION_TREND": 0.30,
        "POSITION_BE_OFFSET_ATR": 0.10,
        "POSITION_BE_MIN_PROGRESS_AFTER_TP1_ATR": 0.55,
        "POSITION_TRAILING_ACTIVATION_ATR_TREND": 8.8,
        "POSITION_TRAILING_ATR_MULT_TREND": 6.1,
        "POSITION_TRAILING_STEP_ATR_TREND": 0.42,
        "POSITION_RUNNER_ACTIVATION_ATR_AFTER_TP1_TREND": 0.60,
        "RISK_MULTIPLIER": 1.00,
        "RANGE_MAX_WIDTH_PCT": 0.10,
        "IMPULSE_BREAKOUT_MIN_BODY_ATR": 0.58,
        "IMPULSE_BREAKOUT_MIN_RANGE_ATR": 0.90,
        "IMPULSE_BREAKOUT_MIN_EXCURSION_ATR": 0.08,
        "REL_STRENGTH_MIN_RATIO": 0.998,
        "REL_STRENGTH_SHORT_MAX_RATIO": 1.002,
        "CONTINUATION_TOUCH_ATR": 0.28,
        "CONTINUATION_MIN_BODY_ATR": 0.36,
        "CONTINUATION_MIN_CLOSE_POS": 0.60,
        "CONTINUATION_MIN_HTF_ADX": 19.0,
        "CONTINUATION_MIN_VOL_RATIO": 0.90,
        "CONTINUATION_RSI_LONG_MIN": 47.0,
        "CONTINUATION_RSI_LONG_MAX": 64.0,
        "CONTINUATION_RSI_SHORT_MIN": 36.0,
        "CONTINUATION_RSI_SHORT_MAX": 53.0,
        "CONTINUATION_PULLBACK_DEPTH_ATR": 0.95,
        "RISK_MULTIPLIER_CONTINUATION": 0.60,
        "CONTINUATION_SOFT_REJECTION": 1.0,
        "BTC_SHORTS_ONLY_STRONG_BEAR": 1,
        "BTC_DISABLE_IMPULSE_SHORT": 1,
        "BTC_DISABLE_FAKEOUT_SHORT": 1,
        "BTC_DISABLE_CONT_COMP_SHORT": 1,
        "BTC_SHORT_CONT_MIN_HTF_ADX": 17.0,
        "BTC_SHORT_CONT_MIN_DRIFT_PCT": 0.004,
        "BTC_SHORT_CONT_MAX_HTF_RSI": 58.0,
        "BTC_SHORT_CONT_MIN_BTC_SCORE": 0.95,
        "ENABLE_CONT_COMP": 0,
        "ENABLE_FAKEOUT": 0,
        "POSITION_TP1_ATR_MULT_RANGE": 5.6,
        "POSITION_TP1_CLOSE_FRACTION_RANGE": 0.50,
        "POSITION_TRAILING_ACTIVATION_ATR_RANGE": 5.6,
        "POSITION_TRAILING_ATR_MULT_RANGE": 3.6,
        "POSITION_TRAILING_STEP_ATR_RANGE": 0.26,
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
        "POSITION_TP1_ATR_MULT": 8.0,
        "POSITION_TP1_CLOSE_FRACTION": 0.33,
        "MARKET_REGIME_MIN_HTF_ADX": 20.0,
        "MARKET_REGIME_MIN_HTF_ATR_PCT": 0.0014,
        "MARKET_REGIME_MIN_DRIFT_PCT": 0.0045,
        "POSITION_TRAILING_ACTIVATION_ATR": 8.0,
        "POSITION_TRAILING_ATR_MULT": 5.3,
        "POSITION_TRAILING_STEP_ATR": 0.40,
        "POSITION_TP1_ATR_MULT_TREND": 8.6,
        "POSITION_TP1_CLOSE_FRACTION_TREND": 0.30,
        "POSITION_BE_OFFSET_ATR": 0.10,
        "POSITION_BE_MIN_PROGRESS_AFTER_TP1_ATR": 0.50,
        "POSITION_TRAILING_ACTIVATION_ATR_TREND": 8.1,
        "POSITION_TRAILING_ATR_MULT_TREND": 5.7,
        "POSITION_TRAILING_STEP_ATR_TREND": 0.38,
        "POSITION_RUNNER_ACTIVATION_ATR_AFTER_TP1_TREND": 0.50,
        "RISK_MULTIPLIER": 0.68,
        "BREAKOUT_HOLD_BUFFER_ATR": 0.04,
        "ALT_QUALITY_MIN_SCORE": 0.48,
        "IMPULSE_BREAKOUT_MIN_BODY_ATR": 0.68,
        "IMPULSE_BREAKOUT_MIN_RANGE_ATR": 1.00,
        "IMPULSE_BREAKOUT_MIN_EXCURSION_ATR": 0.10,
        "REL_STRENGTH_MIN_RATIO": 0.999,
        "REL_STRENGTH_SHORT_MAX_RATIO": 1.0005,
        "RANGE_RSI_LONG_MAX": 28.0,
        "RANGE_RSI_SHORT_MIN": 72.0,
        "RANGE_MIN_STRETCH_FROM_MEAN_ATR": 1.40,
        "CONTINUATION_TOUCH_ATR": 0.29,
        "CONTINUATION_MIN_BODY_ATR": 0.38,
        "CONTINUATION_MIN_CLOSE_POS": 0.61,
        "CONTINUATION_MIN_HTF_ADX": 21.0,
        "CONTINUATION_MIN_VOL_RATIO": 0.98,
        "CONTINUATION_PULLBACK_DEPTH_ATR": 0.95,
        "RISK_MULTIPLIER_CONTINUATION": 0.46,
        "BTC_SHORTS_ONLY_STRONG_BEAR": 1,
        "BTC_DISABLE_IMPULSE_SHORT": 1,
        "BTC_DISABLE_FAKEOUT_SHORT": 1,
        "BTC_DISABLE_CONT_COMP_SHORT": 1,
        "BTC_SHORT_CONT_MIN_HTF_ADX": 17.0,
        "BTC_SHORT_CONT_MIN_DRIFT_PCT": 0.004,
        "BTC_SHORT_CONT_MAX_HTF_RSI": 58.0,
        "BTC_SHORT_CONT_MIN_BTC_SCORE": 0.95,
        "ENABLE_CONT_COMP": 0,
        "ENABLE_FAKEOUT": 0,
        "POSITION_TP1_ATR_MULT_RANGE": 5.4,
        "POSITION_TP1_CLOSE_FRACTION_RANGE": 0.50,
        "POSITION_TRAILING_ACTIVATION_ATR_RANGE": 5.4,
        "POSITION_TRAILING_ATR_MULT_RANGE": 3.5,
        "POSITION_TRAILING_STEP_ATR_RANGE": 0.25,
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
        "POSITION_TP1_ATR_MULT": 6.2,
        "POSITION_TP1_CLOSE_FRACTION": 0.44,
        "POSITION_TRAILING_ATR_MULT": 4.3,
        "POSITION_TP1_ATR_MULT_TREND": 6.8,
        "POSITION_TP1_CLOSE_FRACTION_TREND": 0.40,
        "POSITION_BE_MIN_PROGRESS_AFTER_TP1_ATR_TREND": 0.45,
        "POSITION_TRAILING_ACTIVATION_ATR_TREND": 6.9,
        "POSITION_TRAILING_ATR_MULT_TREND": 4.6,
        "POSITION_RUNNER_ACTIVATION_ATR_AFTER_TP1_TREND": 0.35,
        "RISK_MULTIPLIER": 0.72,
        "ALT_QUALITY_MIN_SCORE": 0.43,
        "BREAKOUT_CONFIRM_BUFFER_ATR": 0.12,
        "BREAKOUT_HOLD_BUFFER_ATR": 0.06,
        "RANGE_ENTRY_ZONE_ATR": 0.95,
        "IMPULSE_BREAKOUT_MIN_BODY_ATR": 0.72,
        "IMPULSE_BREAKOUT_MIN_RANGE_ATR": 1.05,
        "IMPULSE_BREAKOUT_MIN_EXCURSION_ATR": 0.12,
        "REL_STRENGTH_MIN_RATIO": 0.999,
        "REL_STRENGTH_SHORT_MAX_RATIO": 1.001,
        "RANGE_RSI_LONG_MAX": 27.0,
        "RANGE_RSI_SHORT_MIN": 73.0,
        "RANGE_MIN_STRETCH_FROM_MEAN_ATR": 1.40,
        "CONTINUATION_TOUCH_ATR": 0.30,
        "CONTINUATION_MIN_BODY_ATR": 0.38,
        "RISK_MULTIPLIER_CONTINUATION": 0.62,
        "RISK_MULTIPLIER_CONT_COMP": 0.58,
        "CONT_COMP_MIN_BODY_ATR": 0.46,
        "CONT_COMP_MIN_RANGE_ATR": 0.88,
        "CONT_COMP_MIN_VOL_RATIO": 1.04,
        "CONT_COMP_MIN_HTF_ADX": 19.0,
        "FAKEOUT_RSI_LONG_MAX": 30.0,
        "FAKEOUT_RSI_SHORT_MIN": 70.0,
        "ENABLE_CONT_COMP": 1,
        "ENABLE_FAKEOUT": 1,
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
        "POSITION_TP1_ATR_MULT": 6.4,
        "POSITION_TP1_CLOSE_FRACTION": 0.44,
        "POSITION_TRAILING_ATR_MULT": 4.5,
        "POSITION_TP1_ATR_MULT_TREND": 6.9,
        "POSITION_TP1_CLOSE_FRACTION_TREND": 0.40,
        "POSITION_BE_MIN_PROGRESS_AFTER_TP1_ATR_TREND": 0.40,
        "POSITION_TRAILING_ACTIVATION_ATR_TREND": 7.0,
        "POSITION_TRAILING_ATR_MULT_TREND": 4.8,
        "POSITION_RUNNER_ACTIVATION_ATR_AFTER_TP1_TREND": 0.30,
        "RISK_MULTIPLIER": 0.84,
        "ALT_QUALITY_MIN_SCORE": 0.42,
        "BREAKOUT_CONFIRM_BUFFER_ATR": 0.12,
        "BREAKOUT_HOLD_BUFFER_ATR": 0.06,
        "IMPULSE_BREAKOUT_MIN_BODY_ATR": 0.70,
        "IMPULSE_BREAKOUT_MIN_RANGE_ATR": 1.00,
        "IMPULSE_BREAKOUT_MIN_EXCURSION_ATR": 0.10,
        "REL_STRENGTH_MIN_RATIO": 0.999,
        "REL_STRENGTH_SHORT_MAX_RATIO": 1.001,
        "RANGE_RSI_LONG_MAX": 28.0,
        "RANGE_RSI_SHORT_MIN": 72.0,
        "RANGE_MIN_STRETCH_FROM_MEAN_ATR": 1.35,
        "CONTINUATION_TOUCH_ATR": 0.29,
        "CONTINUATION_MIN_BODY_ATR": 0.38,
        "RISK_MULTIPLIER_CONTINUATION": 0.66,
        "RISK_MULTIPLIER_CONT_COMP": 0.60,
        "CONT_COMP_MIN_BODY_ATR": 0.44,
        "CONT_COMP_MIN_RANGE_ATR": 0.86,
        "CONT_COMP_MIN_VOL_RATIO": 0.98,
        "CONT_COMP_MIN_HTF_ADX": 18.5,
        "FAKEOUT_RSI_LONG_MAX": 31.0,
        "FAKEOUT_RSI_SHORT_MIN": 69.0,
        "ENABLE_CONT_COMP": 1,
        "ENABLE_FAKEOUT": 1,
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
        "POSITION_TP1_ATR_MULT": 6.0,
        "POSITION_TP1_CLOSE_FRACTION": 0.46,
        "POSITION_TRAILING_ATR_MULT": 4.1,
        "POSITION_TP1_ATR_MULT_TREND": 6.4,
        "POSITION_TP1_CLOSE_FRACTION_TREND": 0.42,
        "POSITION_BE_MIN_PROGRESS_AFTER_TP1_ATR_TREND": 0.35,
        "POSITION_TRAILING_ACTIVATION_ATR_TREND": 6.6,
        "POSITION_TRAILING_ATR_MULT_TREND": 4.4,
        "POSITION_RUNNER_ACTIVATION_ATR_AFTER_TP1_TREND": 0.25,
        "RISK_MULTIPLIER": 0.64,
        "ALT_QUALITY_MIN_SCORE": 0.44,
        "BREAKOUT_CONFIRM_BUFFER_ATR": 0.14,
        "BREAKOUT_HOLD_BUFFER_ATR": 0.07,
        "RANGE_ENTRY_ZONE_ATR": 1.00,
        "IMPULSE_BREAKOUT_MIN_BODY_ATR": 0.76,
        "IMPULSE_BREAKOUT_MIN_RANGE_ATR": 1.08,
        "IMPULSE_BREAKOUT_MIN_EXCURSION_ATR": 0.12,
        "REL_STRENGTH_MIN_RATIO": 1.000,
        "REL_STRENGTH_SHORT_MAX_RATIO": 1.000,
        "RANGE_RSI_LONG_MAX": 27.0,
        "RANGE_RSI_SHORT_MIN": 73.0,
        "RANGE_MIN_STRETCH_FROM_MEAN_ATR": 1.45,
        "CONTINUATION_TOUCH_ATR": 0.31,
        "CONTINUATION_MIN_BODY_ATR": 0.32,
        "RISK_MULTIPLIER_CONTINUATION": 0.58,
        "RISK_MULTIPLIER_CONT_COMP": 0.56,
        "CONT_COMP_MIN_BODY_ATR": 0.48,
        "CONT_COMP_MIN_RANGE_ATR": 0.92,
        "CONT_COMP_MIN_VOL_RATIO": 1.05,
        "CONT_COMP_MIN_HTF_ADX": 19.5,
        "FAKEOUT_RSI_LONG_MAX": 29.0,
        "FAKEOUT_RSI_SHORT_MIN": 71.0,
        "ENABLE_CONT_COMP": 1,
        "ENABLE_FAKEOUT": 1,
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
HTF_MAX_DIST_FROM_EMA20_ATR = 2.5      # максимум, насколько цена может отстоять от HTF EMA20
HTF_MAX_DIST_FROM_EMA50_ATR = 3.5      # максимум, насколько цена может отстоять от HTF EMA50


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


# ===== Soft BTC regime filter tuning =====
# Делаем фильтр мягче: для альтов допускаем не только идеальное EMA20>50>200,
# но и нейтральный BTC, если ADX уже показывает направленное движение.
BTC_REGIME_SOFT_ADX_MIN = 14.0
BTC_REGIME_HARD_ADX_MIN = 20.0
BTC_REGIME_ALLOW_NEUTRAL_IF_ADX_OK = True
BTC_REGIME_MIN_SCORE = 0.68
BTC_REGIME_MIN_SCORE_LONG = 0.66
BTC_REGIME_MIN_SCORE_SHORT = 0.95

# ===== Global market regime gate (Stage 3) =====
# Дополнительный фильтр: directional-сделки (impulse/continuation)
# разрешаем только когда HTF действительно направлен, а не просто шумит.
MARKET_REGIME_DIRECTIONAL_GATE_ENABLED = True
MARKET_REGIME_DIRECTIONAL_MIN_HTF_ADX = 23.0
MARKET_REGIME_DIRECTIONAL_MIN_HTF_ATR_PCT = 0.0014
MARKET_REGIME_DIRECTIONAL_MIN_DRIFT_PCT = 0.0050
MARKET_REGIME_DIRECTIONAL_MIN_HTF_RSI_LONG = 54.0
MARKET_REGIME_DIRECTIONAL_MAX_HTF_RSI_SHORT = 46.0
MARKET_REGIME_DIRECTIONAL_BLOCK_IMPULSE_IN_TRANSITION = True
MARKET_REGIME_DIRECTIONAL_ALLOW_CONTINUATION_IN_TRANSITION = True
MARKET_REGIME_DIRECTIONAL_TRANSITION_MIN_HTF_ADX = 26.0
MARKET_REGIME_DIRECTIONAL_TRANSITION_MIN_DRIFT_PCT = 0.0065

# Этап 4: quality-of-trend / anti-chop фильтры для directional setup
TREND_QUALITY_FILTER_ENABLED = True
TREND_QUALITY_HTF_SLOPE_LOOKBACK = 8
TREND_QUALITY_MIN_HTF_EMA20_SLOPE_PCT = 0.0032
TREND_QUALITY_MIN_HTF_EMA50_SLOPE_PCT = 0.0018
TREND_QUALITY_COMBO_MIN_HTF_ADX = 26.0
TREND_QUALITY_COMBO_MIN_DRIFT_PCT = 0.0062
TREND_QUALITY_COMBO_MIN_ATR_PCT = 0.0015
CHOP_FILTER_LOOKBACK = 12
CHOP_FILTER_MAX_EMA20_CROSSES = 3
CHOP_FILTER_MAX_WICKINESS = 0.62
CHOP_FILTER_MIN_BODY_RATIO = 0.33
IMPULSE_QUALITY_MAX_WICKINESS = 0.58
IMPULSE_QUALITY_MIN_BODY_RATIO = 0.37

# ===== Market state engine =====
# trend  -> breakout
# range  -> mean reversion
# panic  -> no-trade
MARKET_STATE_TREND_ADX_MIN = 22.0
MARKET_STATE_RANGE_ADX_MAX = 20.0
MARKET_STATE_TREND_DRIFT_MIN = 0.004
MARKET_STATE_PANIC_ATR_PCT = 0.028
MARKET_STATE_PANIC_WICKINESS = 0.72

# ===== Range strategy =====
RANGE_LOOKBACK = 48
RANGE_MAX_WIDTH_PCT = 0.08
RANGE_ENTRY_ZONE_ATR = 0.80
RANGE_TARGET_BUFFER_ATR = 0.35
RANGE_RSI_LONG_MAX = 28.0
RANGE_RSI_SHORT_MIN = 72.0
RANGE_MIN_BOUNCE_BODY_ATR = 0.38
RANGE_MIN_STRETCH_FROM_MEAN_ATR = 1.45
RANGE_BOUNCE_MIN_CLOSE_POS = 0.58
RANGE_ENTRY_ADX_MAX = 20.0
RANGE_MAX_STATE_WICKINESS = 0.58
RANGE_MAX_STATE_FALSE_BREAKOUT = 0.45
RANGE_MAX_COMPRESSION_RATIO = 1.12

# ===== Breakout confirmation =====
BREAKOUT_CONFIRMATION_ENABLED = True
BREAKOUT_CONFIRM_TWO_CLOSES_FOR_ALTS = True
BREAKOUT_CONFIRM_BUFFER_ATR = 0.12
BREAKOUT_HOLD_BUFFER_ATR = 0.05

# ===== Alt quality filter =====
ALT_QUALITY_MIN_SCORE = 0.44
ALT_QUALITY_ATR_LOW_PCT = 0.004
ALT_QUALITY_ATR_HIGH_PCT = 0.03

# Impulse breakout v2: в тренде входим только по реальному импульсу, а не по касанию уровня.
IMPULSE_BREAKOUT_MIN_BODY_ATR = 0.68
IMPULSE_BREAKOUT_MIN_RANGE_ATR = 0.95
IMPULSE_BREAKOUT_MIN_EXCURSION_ATR = 0.10
IMPULSE_BREAKOUT_MIN_CLOSE_POS = 0.60
IMPULSE_BREAKOUT_MIN_ATR_EXPANSION = 0.98

# Relative strength против BTC для альтов.
REL_STRENGTH_LOOKBACK = 48
REL_STRENGTH_EMA = 20
REL_STRENGTH_MIN_RATIO = 0.998
REL_STRENGTH_MIN_SLOPE = 0.0
REL_STRENGTH_SHORT_MAX_RATIO = 1.002
REL_STRENGTH_SHORT_MIN_SLOPE = 0.0

# Transition-state: грязная промежуточная фаза между trend и range, где новые входы запрещены.
MARKET_STATE_TRANSITION_FALSE_BREAKOUT_MIN = 0.68
MARKET_STATE_TRANSITION_WICKINESS_MIN = 0.72
ALT_SHORTS_REQUIRE_STRONG_BTC_BEAR = True

# ===== BTC-specific short controls (v8) =====
BTC_SHORTS_ONLY_STRONG_BEAR = True
BTC_SHORT_MIN_HTF_ADX = 24.0
BTC_SHORT_MIN_DRIFT_PCT = 0.010
BTC_SHORT_MAX_HTF_RSI = 48.0
BTC_SHORT_MIN_BTC_SCORE = 1.05

# v9: BTC shorts are allowed mainly via continuation pullback logic.
# Non-continuation BTC shorts can be disabled independently.
BTC_DISABLE_IMPULSE_SHORT = True
BTC_DISABLE_FAKEOUT_SHORT = True
BTC_DISABLE_CONT_COMP_SHORT = True
BTC_SHORT_CONT_MIN_HTF_ADX = 17.0
BTC_SHORT_CONT_MIN_DRIFT_PCT = 0.004
BTC_SHORT_CONT_MAX_HTF_RSI = 58.0
BTC_SHORT_CONT_MIN_BTC_SCORE = 0.95


# ===== Risk tuning =====
BASE_POSITION_RISK_MULTIPLIER = 1.0
ALT_POSITION_RISK_MULTIPLIER = 0.70

# ===== Stage 5: profit expansion for existing alts =====
ALT_REL_STRENGTH_LONG_RATIO_RELAX = 0.0020
ALT_REL_STRENGTH_SHORT_RATIO_RELAX = 0.0020
ALT_REL_STRENGTH_LONG_MIN_SLOPE_RELAX = 0.0030
ALT_REL_STRENGTH_SHORT_MIN_SLOPE_RELAX = 0.0030
ALT_QUALITY_THRESHOLD_RELAX = 0.05
ALT_RSI_LONG_MIN_LOOSEN = 3.0
ALT_RSI_SHORT_MAX_LOOSEN = 3.0
ALT_STRONG_SETUP_ADX = 28.0
ALT_STRONG_SETUP_DRIFT_PCT = 0.0085
ALT_STRONG_SETUP_VOLUME_IMPULSE = 0.95
ALT_STRONG_SETUP_RS_RATIO_LONG = 1.000
ALT_STRONG_SETUP_RS_RATIO_SHORT = 1.000
ALT_STRONG_SETUP_RISK_MULT = 1.30
BTC_POSITION_RISK_MULTIPLIER = 1.18
ETH_POSITION_RISK_MULTIPLIER = 0.22
BNB_POSITION_RISK_MULTIPLIER = 0.80
SOL_POSITION_RISK_MULTIPLIER = 0.65
AVAX_POSITION_RISK_MULTIPLIER = 0.55

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
STRATEGY_VERSION = _os.getenv("STRATEGY_VERSION", "mtf_breakout_regime_range_v1")

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
POSITION_TP1_ATR_MULT = 8.0
POSITION_TP1_CLOSE_FRACTION = 0.33
POSITION_BE_TRIGGER_ATR = 3.0
POSITION_BE_OFFSET_ATR = 0.10
POSITION_BE_ONLY_AFTER_TP1 = True
POSITION_TRAILING_ACTIVATION_ATR = 8.0
POSITION_TRAILING_ATR_MULT = 4.0
POSITION_TRAILING_STEP_ATR = 0.20
POSITION_TRAILING_ONLY_AFTER_TP1 = True
POSITION_TIME_STOP_AFTER_TP1_BARS = 8
POSITION_RUNNER_STALL_BARS = 8
POSITION_RUNNER_STALL_ONLY_AFTER_TP1 = True
POSITION_RUNNER_ACTIVATION_ATR_AFTER_TP1 = 0.45
POSITION_RUNNER_ACTIVATION_ATR_AFTER_TP1_TREND = 0.55
POSITION_RUNNER_ACTIVATION_ATR_AFTER_TP1_RANGE = 0.20
POSITION_MOVE_BE_ON_TP1 = False
POSITION_BE_MIN_PROGRESS_AFTER_TP1_ATR = 0.35
POSITION_BE_MIN_PROGRESS_AFTER_TP1_ATR_TREND = 0.55
POSITION_BE_MIN_PROGRESS_AFTER_TP1_ATR_RANGE = 0.10

# Backtest realism
BACKTEST_INTRABAR_EXIT_ORDER = "conservative"
BACKTEST_SLIPPAGE_BPS = 1.0
BACKTEST_APPLY_SLIPPAGE = True


# ===== Continuation / trade-type params =====
CONTINUATION_ALLOW_IN_TRANSITION = False
CONTINUATION_TOUCH_ATR = 0.35
CONTINUATION_MIN_BODY_ATR = 0.32
CONTINUATION_MIN_CLOSE_POS = 0.55
CONTINUATION_MIN_VOL_RATIO = 0.92
CONTINUATION_REQUIRE_PREV_PULLBACK = True
CONTINUATION_RSI_LONG_MIN = 46.0
CONTINUATION_RSI_LONG_MAX = 66.0
CONTINUATION_RSI_SHORT_MIN = 34.0
CONTINUATION_RSI_SHORT_MAX = 54.0
CONTINUATION_MIN_HTF_ADX = 21.0
CONTINUATION_PULLBACK_DEPTH_ATR = 0.90
CONTINUATION_SOFT_REJECTION = 0.0

# ===== v4-style risk model =====
RISK_MULTIPLIER_IMPULSE = 1.00
RISK_MULTIPLIER_CONTINUATION = 0.40
RISK_MULTIPLIER_RANGE = 0.25

# ===== Range filters =====
# values are defined in the main range section above to avoid duplicates

# ===== v6 entries kept in code, but feature-gated in v7 =====
ENABLE_FAKEOUT = False
ENABLE_CONT_COMP = False
RISK_MULTIPLIER_FAKEOUT = 0.45
RISK_MULTIPLIER_CONT_COMP = 0.60
FAKEOUT_PIERCE_ATR = 0.16
FAKEOUT_MIN_BODY_ATR = 0.28
FAKEOUT_MIN_VOL_RATIO = 0.90
FAKEOUT_MAX_ADX = 24.0
FAKEOUT_RSI_LONG_MAX = 32.0
FAKEOUT_RSI_SHORT_MIN = 68.0
CONT_COMP_MAX_COMPRESSION_RATIO = 0.82
CONT_COMP_MAX_ATR_RATIO = 0.90
CONT_COMP_MIN_BODY_ATR = 0.42
CONT_COMP_MIN_RANGE_ATR = 0.80
CONT_COMP_MIN_VOL_RATIO = 1.02
CONT_COMP_MIN_HTF_ADX = 18.0
CONT_COMP_TOUCH_ATR = 0.45
CONT_COMP_BREAK_PREV_FACTOR = 0.15


# ===== v12 regime-based exit profiles =====
# trend profile keeps v11 style runners; range/transition exits faster.
POSITION_TP1_ATR_MULT_TREND = 8.8
POSITION_TP1_CLOSE_FRACTION_TREND = 0.30
POSITION_BE_TRIGGER_ATR_TREND = 3.0
POSITION_BE_OFFSET_ATR_TREND = 0.10
POSITION_TRAILING_ACTIVATION_ATR_TREND = 8.8
POSITION_TRAILING_ATR_MULT_TREND = 4.1
POSITION_TRAILING_STEP_ATR_TREND = 0.20

POSITION_TP1_ATR_MULT_RANGE = 5.2
POSITION_TP1_CLOSE_FRACTION_RANGE = 0.55
POSITION_BE_TRIGGER_ATR_RANGE = 0.0
POSITION_BE_OFFSET_ATR_RANGE = 0.06
POSITION_TRAILING_ACTIVATION_ATR_RANGE = 5.2
POSITION_TRAILING_ATR_MULT_RANGE = 2.5
POSITION_TRAILING_STEP_ATR_RANGE = 0.14
POSITION_TIME_STOP_BEFORE_TP1_BARS_RANGE = 18
POSITION_TIME_STOP_AFTER_TP1_BARS_RANGE = 8
POSITION_INITIAL_SL_ATR_MULT_RANGE = 4.8

POSITION_TP1_ATR_MULT_CONTINUATION = 7.2
POSITION_TP1_CLOSE_FRACTION_CONTINUATION = 0.38
POSITION_BE_TRIGGER_ATR_CONTINUATION = 0.0
POSITION_BE_OFFSET_ATR_CONTINUATION = 0.08
POSITION_TRAILING_ACTIVATION_ATR_CONTINUATION = 7.0
POSITION_TRAILING_ATR_MULT_CONTINUATION = 3.4
POSITION_TRAILING_STEP_ATR_CONTINUATION = 0.18
POSITION_RUNNER_ACTIVATION_ATR_AFTER_TP1_CONTINUATION = 0.35
POSITION_TIME_STOP_BEFORE_TP1_BARS_CONTINUATION = 24
POSITION_TIME_STOP_AFTER_TP1_BARS_CONTINUATION = 10
POSITION_INITIAL_SL_ATR_MULT_CONTINUATION = 5.0

POSITION_INITIAL_SL_ATR_MULT = ATR_SL_MULT
POSITION_INITIAL_SL_ATR_MULT_TREND = ATR_SL_MULT
POSITION_TIME_STOP_BEFORE_TP1_BARS = 0
POSITION_TIME_STOP_BEFORE_TP1_BARS_TREND = 0


# ===== Stage 6: BTC/ETH scaling + alt mean reversion =====
# Усиливаем directional-сетапы на BTC/ETH через risk scaling,
# а для SOL/BNB/AVAX добавляем отдельную mean-reversion ветку.
ENABLE_DIRECTIONAL_RISK_SCALING = True
ENABLE_SMART_DIRECTIONAL_SCALING = True
# v6.1 simple boost: BTC-only, looser thresholds, no smart scaling
DIRECTIONAL_SCALING_SYMBOLS = ["BTCUSDT"]
STRONG_SETUP_RISK_MULT = 1.30
VERY_STRONG_SETUP_RISK_MULT = 1.55
STRONG_SETUP_MIN_ADX = 22.0
VERY_STRONG_SETUP_MIN_ADX = 26.0
STRONG_SETUP_MIN_DRIFT_PCT = 0.0050
VERY_STRONG_SETUP_MIN_DRIFT_PCT = 0.0075
STRONG_SETUP_MIN_VOLUME_IMPULSE = 0.60
VERY_STRONG_SETUP_MIN_VOLUME_IMPULSE = 0.80

# Smart scaling: apply boosted risk only in cleaner/high-quality trend conditions.
SMART_SCALING_ONLY_IN_TREND = True
SMART_SCALING_ALLOW_FOR_CONTINUATION = True
SMART_SCALING_ALLOW_FOR_CONT_COMPRESSION = True
SMART_SCALING_ALLOW_FOR_IMPULSE = True
SMART_SCALING_MAX_EMA20_CROSSES = 1
SMART_SCALING_MAX_WICKINESS = 0.52
SMART_SCALING_MIN_BODY_RATIO = 0.40
SMART_SCALING_MIN_EMA20_SLOPE_PCT = 0.0038
SMART_SCALING_MIN_EMA50_SLOPE_PCT = 0.0020
SMART_SCALING_MIN_ATR_PCT = 0.0016
SMART_SCALING_SHORT_EXTRA_MIN_ADX = 2.0
SMART_SCALING_SHORT_EXTRA_MIN_DRIFT_PCT = 0.0015
SMART_SCALING_SHORT_EXTRA_MIN_IMPULSE = 0.05


V52_MEAN_REVERSION_ENABLED = True
V52_MR_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "AVAXUSDT"]
V52_MR_CORE_SYMBOLS = ["BTCUSDT", "ETHUSDT"]
V52_MR_ALLOWED_STATES = ["range", "transition"]
V52_MR_ALLOW_SHORT_CORE = False
V52_MR_ALLOW_SHORT_ALT = False
V52_MR_RISK_MULTIPLIER_CORE = 0.45
V52_MR_RISK_MULTIPLIER_ALT = 0.35
V52_MR_Z_WINDOW = 20
V52_MR_BB_STD = 2.0
V52_MR_Z_THRESHOLD = 1.8
V52_MR_DEV_ATR_THRESHOLD = 1.35
V52_MR_RSI_LONG_MAX = 35.0
V52_MR_RSI_SHORT_MIN = 65.0
V52_MR_MIN_VOL_RATIO = 0.85
V52_MR_MAX_HTF_ADX = 20.0
V52_MR_MAX_LTF_ADX = 24.0
V52_MR_MAX_HTF_EMA_SPREAD_PCT = 0.009
V52_MR_HTF_RSI_MIN = 42.0
V52_MR_HTF_RSI_MAX = 58.0
V52_MR_MIN_CLOSE_POS_LONG = 0.50
V52_MR_MAX_CLOSE_POS_SHORT = 0.50
V52_MR_MIN_REJECTION_WICK = 0.10
POSITION_INITIAL_SL_ATR_MULT_MEAN_REVERSION = 1.8
POSITION_TP1_ATR_MULT_MEAN_REVERSION = 1.8
POSITION_TP1_CLOSE_FRACTION_MEAN_REVERSION = 1.0
POSITION_BE_TRIGGER_ATR_MEAN_REVERSION = 0.0
POSITION_MOVE_BE_ON_TP1_MEAN_REVERSION = False
POSITION_TRAILING_ACTIVATION_ATR_MEAN_REVERSION = 0.0
POSITION_TRAILING_ATR_MULT_MEAN_REVERSION = 0.0
POSITION_TRAILING_STEP_ATR_MEAN_REVERSION = 0.0
POSITION_TIME_STOP_BEFORE_TP1_BARS_MEAN_REVERSION = 10
POSITION_TIME_STOP_AFTER_TP1_BARS_MEAN_REVERSION = 0
POSITION_RUNNER_STALL_BARS_MEAN_REVERSION = 0

# ===== Pullback trend strategy (Phase 1) =====
PULLBACK_TREND_ENABLED = True
PULLBACK_TREND_SYMBOLS = ["BTCUSDT", "ETHUSDT"]
PULLBACK_TREND_ALLOW_IN_TRANSITION = False
PULLBACK_RISK_MULTIPLIER = 0.75
PULLBACK_TOUCH_ATR = 0.55
PULLBACK_MAX_DEEP_TOUCH_ATR = 1.10
PULLBACK_MIN_BODY_ATR = 0.30
PULLBACK_MIN_CLOSE_POS = 0.55
PULLBACK_MIN_VOL_RATIO = 0.90
PULLBACK_MIN_HTF_ADX = 20.0
PULLBACK_RSI_LONG_MIN = 46.0
PULLBACK_RSI_LONG_MAX = 63.0
PULLBACK_RSI_SHORT_MIN = 37.0
PULLBACK_RSI_SHORT_MAX = 54.0
PULLBACK_REQUIRE_PREV_COUNTER_CANDLE = True
PULLBACK_PREV_CLOSE_POS_MAX = 0.62
PULLBACK_RECLAIM_EMA20_REQUIRED = True
PULLBACK_PRE_IMPULSE_BARS = 8
PULLBACK_PRE_IMPULSE_MIN_ATR = 1.45
PULLBACK_PRE_IMPULSE_MIN_ATR_SHORT = 1.75
PULLBACK_MAX_EMA20_CROSSES = 2
PULLBACK_MAX_AVG_WICK_RATIO = 0.46
PULLBACK_MIN_EMA20_SLOPE_PCT = 0.00055
PULLBACK_MIN_EMA50_SLOPE_PCT = 0.00035
PULLBACK_MIN_EMA20_SLOPE_PCT_SHORT = 0.00075
PULLBACK_MIN_EMA50_SLOPE_PCT_SHORT = 0.00045

# Pullback phase 3: trend continuation / exhaustion guards
PULLBACK_MAX_PRICE_TO_HTF_EMA20_PCT = 0.030
PULLBACK_MAX_PRICE_TO_HTF_EMA20_PCT_SHORT = 0.025
PULLBACK_MAX_PRE_IMPULSE_SAME_DIR_BARS = 5
PULLBACK_MAX_PRE_IMPULSE_SAME_DIR_BARS_SHORT = 4
PULLBACK_DECAY_LOOKBACK = 4
PULLBACK_MIN_MOMENTUM_DECAY_RATIO = 0.52
PULLBACK_MIN_MOMENTUM_DECAY_RATIO_SHORT = 0.62
PULLBACK_RECENT_BODY_ATR_MIN = 0.22
PULLBACK_RECENT_BODY_ATR_MIN_SHORT = 0.26

# ===== v5.3 final controls =====
V53_ETH_MR_ONLY = True
V53_ETH_MR_RISK_MULTIPLIER = 0.25
V53_MR_ALLOWED_STATES_CORE = ["range"]

# === V5.4 FINAL FIX ===
V54_ETH_MR_ONLY = True
V54_ETH_DISABLE_SHORTS = True
V54_ETH_MR_RISK_MULTIPLIER = 0.04
V54_MR_RISK_MULTIPLIER_CORE = 0.35
V54_MR_RISK_MULTIPLIER_ALT = 0.20
