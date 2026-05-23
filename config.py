"""
Глобальные настройки бота (актуально: только фьючерсы Binance USDT-M).
Текущая конфигурация рассчитана на:

- торговлю фьючерсами USDT-M (без спотового режима),
- multi-asset: BTC, ETH,
- переключение paper / real одним флагом,
- работу стратегий:
  * MTF Breakout (H1 тренд + M15 вход).

Замечание по архитектуре:
- выбор runtime-стратегии централизован в strategies/__init__.py;
- STRATEGY_NAME оставлен как legacy-флаг для логов и обратной совместимости;
- секреты и токены должны приходить из переменных окружения, а не храниться в коде.
"""

import os as _os

def _env_str(name: str, default: str = "") -> str:
    return _os.getenv(name, default)

def _env_bool(name: str, default: bool = False) -> bool:
    raw = _os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}

def _env_int(name: str, default: int) -> int:
    try:
        return int(_os.getenv(name, str(default)))
    except Exception:
        return int(default)

def _env_float(name: str, default: float) -> float:
    try:
        return float(_os.getenv(name, str(default)))
    except Exception:
        return float(default)

STRATEGY_NAME = "mtf_breakout"
FUTURES_SYMBOLS = ["BTCUSDT"]  # v72 cleanup: active production core is BTC-only before v80 port

# Совместимые legacy-алиасы для старых мест кода.
BINANCE_API_KEY="cOzVm76AAqWwFe6vvHcoZ2wB1mNhJg01DJ9GpA5ZXq12nBpGmsJdwMoXTyRVA9Hw"
BINANCE_API_SECRET="O4o0oORj7wloy6DfeuWbcOVUy9SfV8z94gSyBQF63kHyQkPPJDXlZqYmuKwmKcfX"
API_KEY = BINANCE_API_KEY
API_SECRET = BINANCE_API_SECRET
# ===== СПИСОК ПАР ДЛЯ ТОРГОВЛИ =====

# config.py (важные куски)

INITIAL_BALANCE_USDT = 5000

# Индикаторы тренда
SMA_TREND_PERIOD = 200
EMA_FAST = 5
EMA_SLOW = 13
EMA_FAST_PERIOD = EMA_FAST
EMA_SLOW_PERIOD = EMA_SLOW
ATR_PERIOD = 14
ADX_PERIOD = 14

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
# Комиссия фьючерсов (пример: 0.04% = 0.0004)
FUTURES_FEE_RATE = 0.0004

# Риск на сделку (если захочешь считать через стоп)
RISK_PER_TRADE = 0.024                # 2.2% от equity (BTC-only stage2 selective sizing)

# ===== ФЬЮЧЕРСЫ =====
# Базовое плечо. В коде можно будет делать dynamic_leverage(equity)
FUTURES_LEVERAGE_DEFAULT = 5

# Legacy polling/logging and flat ATR/RSI thresholds removed: current runtime uses dedicated defaults and MTF/profile-specific filters.

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
        "ATR_SL_MULT": 2.8,
        "POSITION_TP1_ATR_MULT": 5.4,
        "POSITION_TP1_CLOSE_FRACTION": 0.20,
        "MARKET_REGIME_MIN_HTF_ADX": 20.0,
        "MARKET_REGIME_MIN_HTF_ATR_PCT": 0.0014,
        "MARKET_REGIME_MIN_DRIFT_PCT": 0.0045,
        "TREND_QUALITY_COMBO_MIN_HTF_ADX": 27.0,
        "TREND_QUALITY_COMBO_MIN_DRIFT_PCT": 0.0064,
        "CHOP_FILTER_MAX_EMA20_CROSSES": 3,
        "POSITION_TRAILING_ACTIVATION_ATR": 4.6,
        "POSITION_TRAILING_ATR_MULT": 3.3,
        "POSITION_TRAILING_STEP_ATR": 0.12,
        "POSITION_TP1_ATR_MULT_TREND": 6.2,
        "POSITION_TP1_CLOSE_FRACTION_TREND": 0.18,
        "POSITION_BE_OFFSET_ATR": 0.12,
        "POSITION_BE_MIN_PROGRESS_AFTER_TP1_ATR": 0.10,
        "POSITION_TRAILING_ACTIVATION_ATR_TREND": 5.0,
        "POSITION_TRAILING_ATR_MULT_TREND": 3.7,
        "POSITION_TRAILING_STEP_ATR_TREND": 0.12,
        "POSITION_RUNNER_ACTIVATION_ATR_AFTER_TP1_TREND": 0.60,
        "POSITION_PROFIT_LOCK_TRIGGER_ATR": 2.4,
        "POSITION_PROFIT_LOCK_ATR": 0.55,
        "POSITION_PROFIT_LOCK_TRIGGER_ATR_TREND": 2.8,
        "POSITION_PROFIT_LOCK_ATR_TREND": 0.85,
        "POSITION_PROFIT_LOCK_TRIGGER_ATR_CONTINUATION": 2.1,
        "POSITION_PROFIT_LOCK_ATR_CONTINUATION": 0.50,
        "POSITION_EARLY_EXIT_BARS": 10,
        "POSITION_EARLY_EXIT_MIN_PROGRESS_ATR": 0.30,
        "POSITION_EARLY_EXIT_BARS_TREND": 14,
        "POSITION_EARLY_EXIT_MIN_PROGRESS_ATR_TREND": 0.30,
        "POSITION_EARLY_EXIT_BARS_CONTINUATION": 8,
        "POSITION_EARLY_EXIT_MIN_PROGRESS_ATR_CONTINUATION": 0.25,
        "POSITION_EARLY_CUT_LOSS_ATR": 1.55,
        "POSITION_EARLY_CUT_MAX_PROGRESS_ATR": 0.20,
        "POSITION_EARLY_CUT_LOSS_ATR_TREND": 1.75,
        "POSITION_EARLY_CUT_MAX_PROGRESS_ATR_TREND": 0.25,
        "POSITION_EARLY_CUT_LOSS_ATR_CONTINUATION": 1.35,
        "POSITION_EARLY_CUT_MAX_PROGRESS_ATR_CONTINUATION": 0.15,
        "RISK_MULTIPLIER": 1.00,
        "RANGE_MAX_WIDTH_PCT": 0.10,
        "IMPULSE_BREAKOUT_MIN_BODY_ATR": 0.58,
        "IMPULSE_BREAKOUT_MIN_RANGE_ATR": 0.90,
        "IMPULSE_BREAKOUT_MIN_EXCURSION_ATR": 0.08,
        "REL_STRENGTH_MIN_RATIO": 0.998,
        "REL_STRENGTH_SHORT_MAX_RATIO": 1.002,
        "CONTINUATION_TOUCH_ATR": 0.28,
        "CONTINUATION_MIN_BODY_ATR": 0.41,
        "CONTINUATION_MIN_CLOSE_POS": 0.58,
        "CONTINUATION_MIN_HTF_ADX": 22.0,
        "CONTINUATION_MIN_VOL_RATIO": 0.94,
        "CONTINUATION_RSI_LONG_MIN": 47.0,
        "CONTINUATION_RSI_LONG_MAX": 65.0,
        "CONTINUATION_RSI_SHORT_MIN": 36.0,
        "CONTINUATION_RSI_SHORT_MAX": 53.0,
        "CONTINUATION_PULLBACK_DEPTH_ATR": 1.00,
        "CONTINUATION_REQUIRE_PREV_PULLBACK": 1,
        "CONTINUATION_STRONG_BYPASS_PREV_PULLBACK": 0,
        "RISK_MULTIPLIER_CONTINUATION": 0.72,
        "CONTINUATION_SOFT_REJECTION": 1.0,
        "BTC_IMPULSE_NO_TRADE_MIN_ADX_H": 28.0,
        "BTC_IMPULSE_ALLOWED_MARKET_STATES": ["trend"],
        "BTC_IMPULSE_REQUIRE_STRONG_SETUP": 1,
        "BTC_IMPULSE_ANTI_SPIKE_MAX_BODY_ATR": 1.10,
        "BTC_IMPULSE_ANTI_SPIKE_MAX_RANGE_ATR": 1.75,
        "BTC_IMPULSE_ANTI_SPIKE_MIN_CLOSE_POS": 0.76,
        "BTC_IMPULSE_NO_TRADE_MIN_DRIFT_PCT": 0.0070,
        "BTC_PULLBACK_NO_TRADE_MIN_ADX_H": 21.0,
        "BTC_PULLBACK_NO_TRADE_MIN_DRIFT_PCT": 0.0046,
        "BTC_CONTINUATION_NO_TRADE_MIN_ADX_H": 24.0,
        "BTC_CONTINUATION_NO_TRADE_MIN_DRIFT_PCT": 0.0058,
        "BTC_STAGE7_STRONG_TRADE_TYPES": ["impulse", "pullback"],
        "BTC_STAGE7_STRONG_MIN_ADX_H": 27.5,
        "BTC_STAGE7_STRONG_MIN_DRIFT_PCT": 0.0069,
        "BTC_STAGE7_STRONG_RISK_MULT": 1.12,
        "BTC_STAGE7_WEAK_CONTINUATION_RISK_MULT": 0.90,
        "BTC_STAGE7_WEAK_CONT_MIN_ADX_H": 27.5,
        "BTC_STAGE7_WEAK_CONT_MIN_DRIFT_PCT": 0.0070,
        "BTC_STAGE7_STRONG_EXIT_ENABLED": 1,
        "BTC_STAGE7_STRONG_EXIT_TRAIL_ACTIVATION_BONUS_ATR": 0.9,
        "BTC_STAGE7_STRONG_EXIT_TRAIL_MULT_BONUS": 0.55,
        "BTC_STAGE7_STRONG_EXIT_PROFIT_LOCK_TRIGGER_BONUS_ATR": 0.6,
        "BTC_STAGE7_STRONG_EXIT_EARLY_EXIT_BARS_BONUS": 3,
        "BTC_STAGE7_STRONG_EXIT_EARLY_EXIT_PROGRESS_RELAX_ATR": 0.10,
        "BTC_STAGE7_STRONG_EXIT_EARLY_CUT_LOSS_BONUS_ATR": 0.25,
        "BTC_RANGE_ENGINE_ENABLED": True,
        "BTC_RANGE_ALLOWED_TYPES": ["mean_reversion", "reclaim_range", "liquidity_reversal", "reaction_range", "range", "fakeout"],
        "BTC_RANGE_ALLOWED_MARKET_STATES": ["range", "flat", "chop", "transition"],
        "BTC_RANGE_MAX_ADX_H": 22.0,
        "BTC_RANGE_MAX_DRIFT_PCT": 0.0048,
        "BTC_RANGE_RISK_MULT": 0.58,
        "BTC_MR_ANTI_KNIFE_ENABLED": True,
        "BTC_MR_ANTI_KNIFE_MAX_BODY_ATR": 0.98,
        "BTC_MR_ANTI_KNIFE_MAX_NEG_PROGRESS_ATR": 0.62,
        "BTC_MR_ANTI_KNIFE_REQUIRE_GREEN_CANDLE": True,
        "BTC_LIQUIDITY_REVERSAL_ENABLED": True,
        "BTC_LIQUIDITY_REVERSAL_ALLOWED_STATES": ["range", "flat", "transition"],
        "BTC_LIQUIDITY_REVERSAL_MAX_ADX_H": 22.0,
        "BTC_LIQUIDITY_REVERSAL_MAX_DRIFT_PCT": 0.0049,
        "BTC_LIQUIDITY_REVERSAL_RISK_MULT": 0.65,
        "BTC_LIQUIDITY_REVERSAL_COOLDOWN_BARS": 48,
        "BTC_LIQUIDITY_MAX_SIGNALS_PER_DAY": 2,
        "BTC_LIQUIDITY_PYRAMID_ENABLED": True,
        "BTC_LIQUIDITY_PYRAMID_MAX_ADDS": 1,
        "BTC_LIQUIDITY_PYRAMID_RISK_FRACTION": 0.35,
        "BTC_LIQUIDITY_PYRAMID_MIN_PROGRESS_ATR": 0.22,
        "BTC_LIQUIDITY_PYRAMID_MAX_ADX_H": 22.5,
        "BTC_LIQUIDITY_PYRAMID_MAX_DRIFT_PCT": 0.0050,
        "BTC_LIQUIDITY_PYRAMID_ALLOW_AFTER_TP1": True,
        "BTC_STAGE10V2_BASIC_MR_ENABLED": True,
        "BTC_STAGE10V2_BASIC_MR_ALLOWED_STATES": ["range", "flat"],
        "BTC_STAGE10V2_BASIC_MR_MAX_ADX_H": 14.0,
        "BTC_STAGE10V2_BASIC_MR_MAX_DRIFT_PCT": 0.0024,
        "BTC_STAGE10V2_BASIC_MR_RSI_LONG_MAX": 28.5,
        "BTC_STAGE10V2_BASIC_MR_MIN_DEV_ATR": 1.25,
        "BTC_STAGE10V2_BASIC_MR_MIN_CLOSE_POS": 0.72,
        "BTC_STAGE10V2_BASIC_MR_MIN_REJECT_WICK": 0.24,
        "BTC_STAGE10V2_BASIC_MR_MAX_BODY_ATR": 0.34,
        "BTC_STAGE10V2_BASIC_MR_MAX_NEG_PROGRESS_ATR": 0.18,
        "BTC_STAGE10V2_BASIC_MR_REQUIRE_GREEN_CANDLE": True,
        "BTC_STAGE10V2_BASIC_MR_MIN_VOL_RATIO": 1.00,
        "BTC_STAGE10V2_BASIC_MR_RISK_MULT": 0.34,
        "BTC_STAGE10V2_BASIC_MR_COOLDOWN_BARS": 144,
        "FAKEOUT_PIERCE_ATR": 0.11,
        "FAKEOUT_MIN_BODY_ATR": 0.18,
        "FAKEOUT_MIN_VOL_RATIO": 0.86,
        "FAKEOUT_MAX_ADX": 22.0,
        "FAKEOUT_RSI_LONG_MAX": 38.0,
        "BTC_RECLAIM_ALLOWED_STATES": ["range", "flat"],
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
        "POSITION_TP1_ATR_MULT_RANGE": 2.0,
        "POSITION_TP1_CLOSE_FRACTION_RANGE": 0.50,
        "POSITION_TRAILING_ACTIVATION_ATR_RANGE": 3.4,
        "POSITION_TRAILING_ATR_MULT_RANGE": 2.2,
        "POSITION_TRAILING_STEP_ATR_RANGE": 0.16,
        "V7_DIRECT_BOOST_MULT": 1.75,
        "V7_DIRECT_BOOST_MIN_ADX": 25.0,
        "V7_DIRECT_BOOST_MIN_DRIFT_PCT": 0.0065,
    },
    "ETHUSDT": {
        "BREAKOUT_BUFFER_PCT": 0.0010,
        "MTF_LTF_LOOKBACK": 64,
        "BREAKOUT_VOLUME_MIN_RATIO_TO_EMA": 1.14,
        "BREAKOUT_VOLUME_MIN_RATIO_TO_MEDIAN": 1.22,
        "MTF_RSI_LONG_MIN": 52.0,
        "MTF_RSI_LONG_MAX": 82.0,
        "MTF_RSI_SHORT_MIN": 16.0,
        "MTF_RSI_SHORT_MAX": 54.0,
        "ATR_SL_MULT": 5.2,
        "POSITION_TP1_ATR_MULT": 8.0,
        "POSITION_TP1_CLOSE_FRACTION": 0.20,
        "MARKET_REGIME_MIN_HTF_ADX": 22.0,
        "MARKET_REGIME_MIN_HTF_ATR_PCT": 0.0015,
        "MARKET_REGIME_MIN_DRIFT_PCT": 0.0052,
        "MARKET_REGIME_DIRECTIONAL_MIN_HTF_ADX": 25.0,
        "MARKET_REGIME_DIRECTIONAL_MIN_HTF_ATR_PCT": 0.0015,
        "MARKET_REGIME_DIRECTIONAL_MIN_DRIFT_PCT": 0.0058,
        "MARKET_REGIME_DIRECTIONAL_MIN_HTF_RSI_LONG": 55.0,
        "MARKET_REGIME_DIRECTIONAL_TRANSITION_MIN_HTF_ADX": 28.0,
        "MARKET_REGIME_DIRECTIONAL_TRANSITION_MIN_DRIFT_PCT": 0.0070,
        "POSITION_TRAILING_ACTIVATION_ATR": 8.0,
        "POSITION_TRAILING_ATR_MULT": 5.3,
        "POSITION_TRAILING_STEP_ATR": 0.40,
        # v20 ETH exit profile: keep v18-quality entries, but take TP1 earlier and manage runners tighter.
        "POSITION_TP1_ATR_MULT_TREND": 5.4,
        "POSITION_TP1_CLOSE_FRACTION_TREND": 0.26,
        "POSITION_BE_TRIGGER_ATR_TREND": 1.45,
        "POSITION_BE_OFFSET_ATR": 0.10,
        "POSITION_BE_OFFSET_ATR_TREND": 0.10,
        "POSITION_BE_MIN_PROGRESS_AFTER_TP1_ATR": 0.28,
        "POSITION_BE_MIN_PROGRESS_AFTER_TP1_ATR_TREND": 0.28,
        "POSITION_TRAILING_ACTIVATION_ATR_TREND": 4.9,
        "POSITION_TRAILING_ATR_MULT_TREND": 3.7,
        "POSITION_TRAILING_STEP_ATR_TREND": 0.18,
        "POSITION_RUNNER_ACTIVATION_ATR_AFTER_TP1_TREND": 0.25,
        "POSITION_TIME_STOP_AFTER_TP1_BARS_TREND": 12,
        "POSITION_RUNNER_STALL_BARS_TREND": 10,
        # v22 ETH exit fine-tune: keep v20 runner/TP profile, but stop cutting valid trend trades too early.
        "POSITION_EARLY_EXIT_BARS_TREND": 24,
        "POSITION_EARLY_EXIT_MIN_PROGRESS_ATR_TREND": 0.05,
        "POSITION_EARLY_CUT_LOSS_ATR_TREND": 2.80,
        "POSITION_EARLY_CUT_MAX_PROGRESS_ATR_TREND": -0.05,
        "RISK_MULTIPLIER": 0.54,
        "BREAKOUT_HOLD_BUFFER_ATR": 0.05,
        "ALT_QUALITY_MIN_SCORE": 0.52,
        "ALT_QUALITY_THRESHOLD_RELAX": 0.00,
        "IMPULSE_BREAKOUT_MIN_BODY_ATR": 0.72,
        "IMPULSE_BREAKOUT_MIN_RANGE_ATR": 1.05,
        "IMPULSE_BREAKOUT_MIN_EXCURSION_ATR": 0.12,
        "REL_STRENGTH_MIN_RATIO": 1.0005,
        "REL_STRENGTH_SHORT_MAX_RATIO": 1.0005,
        "ALT_REL_STRENGTH_LONG_RATIO_RELAX": 0.00,
        "ALT_REL_STRENGTH_LONG_MIN_SLOPE_RELAX": 0.00,
        "RANGE_RSI_LONG_MAX": 28.0,
        "RANGE_RSI_SHORT_MIN": 72.0,
        "RANGE_MIN_STRETCH_FROM_MEAN_ATR": 1.40,
        "CONTINUATION_TOUCH_ATR": 0.29,
        "CONTINUATION_MIN_BODY_ATR": 0.44,
        "CONTINUATION_MIN_CLOSE_POS": 0.63,
        "CONTINUATION_MIN_HTF_ADX": 23.0,
        "CONTINUATION_MIN_VOL_RATIO": 1.05,
        "CONTINUATION_PULLBACK_DEPTH_ATR": 0.90,
        "RISK_MULTIPLIER_CONTINUATION": 0.40,
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
        "ALT_V1_CONT_LONG_MIN_SCORE": 0.54,
        "ALT_V1_CONT_LONG_MIN_BTC_SCORE": 1.04,
        "ALT_V1_CONT_LONG_MIN_RS_RATIO": 1.0042,
        "ALT_V2_LONG_MIN_BTC_SCORE": 1.03,
        "ALT_V2_LONG_MIN_ALT_SCORE": 0.54,
        "ALT_V2_LONG_MIN_RS_RATIO": 1.0026,
        "ALT_V2_LONG_MIN_ADX": 22.5,
        "ALT_V2_LONG_MIN_DRIFT_PCT": 0.0058,
        "ALT_V2_LONG_MIN_VOLUME_IMPULSE": 0.58,
        "TREND_QUALITY_COMBO_MIN_HTF_ADX": 28.0,
        "TREND_QUALITY_COMBO_MIN_DRIFT_PCT": 0.0068,
        "TREND_QUALITY_COMBO_MIN_ATR_PCT": 0.0016,
        "ETH_POSITION_RISK_MULTIPLIER": 0.24,
        # v23 ETH volatility breakout fallback exits: small, fast trades in non-ideal trend regimes.
        "POSITION_TP1_ATR_MULT_RANGE": 2.2,
        "POSITION_TP1_CLOSE_FRACTION_RANGE": 0.45,
        "POSITION_BE_TRIGGER_ATR_RANGE": 0.90,
        "POSITION_BE_OFFSET_ATR_RANGE": 0.05,
        "POSITION_TRAILING_ACTIVATION_ATR_RANGE": 1.55,
        "POSITION_TRAILING_ATR_MULT_RANGE": 1.35,
        "POSITION_TRAILING_STEP_ATR_RANGE": 0.12,
        "POSITION_TIME_STOP_BEFORE_TP1_BARS_RANGE": 20,
        "POSITION_TIME_STOP_AFTER_TP1_BARS_RANGE": 8,
    },
    # v27: ALT trend-only profiles. Do NOT reuse legacy range/MR logic for alts.
    "SOLUSDT": {
        "MTF_LTF_LOOKBACK": 56,
        "BREAKOUT_BUFFER_PCT": 0.0014,
        "ATR_SL_MULT": 4.8,
        "POSITION_TP1_ATR_MULT_TREND": 4.6,
        "POSITION_TP1_CLOSE_FRACTION_TREND": 0.32,
        "POSITION_BE_TRIGGER_ATR_TREND": 1.25,
        "POSITION_BE_OFFSET_ATR_TREND": 0.08,
        "POSITION_TRAILING_ACTIVATION_ATR_TREND": 3.8,
        "POSITION_TRAILING_ATR_MULT_TREND": 2.8,
        "POSITION_TRAILING_STEP_ATR_TREND": 0.16,
        "POSITION_RUNNER_ACTIVATION_ATR_AFTER_TP1_TREND": 0.18,
        "POSITION_TIME_STOP_AFTER_TP1_BARS_TREND": 8,
        "POSITION_RUNNER_STALL_BARS_TREND": 7,
        "POSITION_EARLY_EXIT_BARS_TREND": 18,
        "POSITION_EARLY_EXIT_MIN_PROGRESS_ATR_TREND": 0.12,
        "POSITION_EARLY_CUT_LOSS_ATR_TREND": 2.30,
        "POSITION_EARLY_CUT_MAX_PROGRESS_ATR_TREND": -0.02,
        "RISK_MULTIPLIER": 0.22,
    },
    "AVAXUSDT": {
        "MTF_LTF_LOOKBACK": 60,
        "BREAKOUT_BUFFER_PCT": 0.0015,
        "ATR_SL_MULT": 4.9,
        "POSITION_TP1_ATR_MULT_TREND": 4.7,
        "POSITION_TP1_CLOSE_FRACTION_TREND": 0.32,
        "POSITION_BE_TRIGGER_ATR_TREND": 1.28,
        "POSITION_BE_OFFSET_ATR_TREND": 0.08,
        "POSITION_TRAILING_ACTIVATION_ATR_TREND": 3.9,
        "POSITION_TRAILING_ATR_MULT_TREND": 2.9,
        "POSITION_TRAILING_STEP_ATR_TREND": 0.16,
        "POSITION_RUNNER_ACTIVATION_ATR_AFTER_TP1_TREND": 0.18,
        "POSITION_TIME_STOP_AFTER_TP1_BARS_TREND": 8,
        "POSITION_RUNNER_STALL_BARS_TREND": 7,
        "POSITION_EARLY_EXIT_BARS_TREND": 18,
        "POSITION_EARLY_EXIT_MIN_PROGRESS_ATR_TREND": 0.12,
        "POSITION_EARLY_CUT_LOSS_ATR_TREND": 2.35,
        "POSITION_EARLY_CUT_MAX_PROGRESS_ATR_TREND": -0.02,
        "RISK_MULTIPLIER": 0.20,
    },
    "BNBUSDT": {
        "MTF_LTF_LOOKBACK": 68,
        "BREAKOUT_BUFFER_PCT": 0.0011,
        "ATR_SL_MULT": 4.6,
        "POSITION_TP1_ATR_MULT_TREND": 4.9,
        "POSITION_TP1_CLOSE_FRACTION_TREND": 0.30,
        "POSITION_BE_TRIGGER_ATR_TREND": 1.30,
        "POSITION_BE_OFFSET_ATR_TREND": 0.08,
        "POSITION_TRAILING_ACTIVATION_ATR_TREND": 4.0,
        "POSITION_TRAILING_ATR_MULT_TREND": 3.0,
        "POSITION_TRAILING_STEP_ATR_TREND": 0.16,
        "POSITION_RUNNER_ACTIVATION_ATR_AFTER_TP1_TREND": 0.20,
        "POSITION_TIME_STOP_AFTER_TP1_BARS_TREND": 9,
        "POSITION_RUNNER_STALL_BARS_TREND": 8,
        "POSITION_EARLY_EXIT_BARS_TREND": 20,
        "POSITION_EARLY_EXIT_MIN_PROGRESS_ATR_TREND": 0.10,
        "POSITION_EARLY_CUT_LOSS_ATR_TREND": 2.40,
        "POSITION_EARLY_CUT_MAX_PROGRESS_ATR_TREND": -0.02,
        "RISK_MULTIPLIER": 0.18,
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

def get_symbol_param_bool(symbol: str, param_name: str, default: bool) -> bool:
    try:
        value = get_symbol_param(symbol, param_name, default)
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "y", "on"}
        return bool(value)
    except Exception:
        return bool(default)


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
ENTRY_COOLDOWN_AFTER_STOP_BARS = 8               # stage5: длиннее пауза после убыточного стопа в BTC-only режиме
ENTRY_COOLDOWN_STREAK_THRESHOLD = 2              # с какого подряд стопа считать серию
ENTRY_COOLDOWN_STREAK_EXTRA_BARS = 12            # stage5: длиннее пауза при серии стопов в плохом рынке
ENTRY_COOLDOWN_RESET_ON_NON_LOSS_EXIT = True     # сбрасывать серию после неубыточного/прибыльного выхода
ENTRY_COOLDOWN_BAR_SECONDS = 15 * 60             # M15 = 900 секунд

# ===== Stage5: BTC no-trade / bad-market filter =====
BTC_NO_TRADE_FILTER_ENABLED = True
BTC_NO_TRADE_ALLOWED_TYPES = ["impulse", "continuation", "pullback", "mean_reversion", "reclaim_range", "liquidity_reversal", "range", "fakeout"]
BTC_NO_TRADE_BLOCKED_MARKET_STATES = ["range", "flat", "chop"]
BTC_NO_TRADE_MIN_ADX_H = 23.0
BTC_NO_TRADE_MIN_DRIFT_PCT = 0.0058
BTC_RANGE_ENGINE_ENABLED = False  # v72 cleanup: legacy range engine disabled
BTC_RANGE_ALLOWED_TYPES = ["mean_reversion", "reclaim_range", "liquidity_reversal", "reaction_range", "range", "fakeout"]
BTC_RANGE_ALLOWED_MARKET_STATES = ["range", "flat", "chop", "transition"]
BTC_RANGE_MAX_ADX_H = 22.5
BTC_RANGE_MAX_DRIFT_PCT = 0.0048
BTC_RANGE_RISK_MULT = 0.58
BTC_MR_ANTI_KNIFE_ENABLED = True
BTC_MR_ANTI_KNIFE_MAX_BODY_ATR = 0.98
BTC_MR_ANTI_KNIFE_MAX_NEG_PROGRESS_ATR = 0.62
BTC_MR_ANTI_KNIFE_REQUIRE_GREEN_CANDLE = True
BTC_RECLAIM_ALLOWED_STATES = ["range", "flat"]

BTC_CONTINUATION_NO_TRADE_MIN_ADX_H = 23.5
BTC_CONTINUATION_NO_TRADE_MIN_DRIFT_PCT = 0.0058
BTC_IMPULSE_NO_TRADE_MIN_ADX_H = 27.5
BTC_IMPULSE_NO_TRADE_MIN_DRIFT_PCT = 0.0068
BTC_PULLBACK_NO_TRADE_MIN_ADX_H = 21.5
BTC_PULLBACK_NO_TRADE_MIN_DRIFT_PCT = 0.0048
BTC_WEAK_MARKET_COOLDOWN_AFTER_STOP_BARS = 8
BTC_WEAK_MARKET_COOLDOWN_STREAK_EXTRA_BARS = 12
BTC_STAGE7_STRONG_TRADE_TYPES = ["impulse", "pullback"]
BTC_IMPULSE_ALLOWED_MARKET_STATES = ["trend"]
BTC_IMPULSE_REQUIRE_STRONG_SETUP = True
BTC_IMPULSE_ANTI_SPIKE_MAX_BODY_ATR = 1.15
BTC_IMPULSE_ANTI_SPIKE_MAX_RANGE_ATR = 1.85
BTC_IMPULSE_ANTI_SPIKE_MIN_CLOSE_POS = 0.74
BTC_STAGE7_STRONG_MIN_ADX_H = 27.0
BTC_STAGE7_STRONG_MIN_DRIFT_PCT = 0.0068
BTC_STAGE7_STRONG_RISK_MULT = 1.10
BTC_STAGE7_WEAK_CONTINUATION_RISK_MULT = 0.88
BTC_STAGE7_WEAK_CONT_MIN_ADX_H = 27.0
BTC_STAGE7_WEAK_CONT_MIN_DRIFT_PCT = 0.0068
BTC_STAGE7_STRONG_EXIT_ENABLED = True
BTC_STAGE7_STRONG_EXIT_TRAIL_ACTIVATION_BONUS_ATR = 0.8
BTC_STAGE7_STRONG_EXIT_TRAIL_MULT_BONUS = 0.45
BTC_STAGE7_STRONG_EXIT_PROFIT_LOCK_TRIGGER_BONUS_ATR = 0.5
BTC_STAGE7_STRONG_EXIT_EARLY_EXIT_BARS_BONUS = 2
BTC_STAGE7_STRONG_EXIT_EARLY_EXIT_PROGRESS_RELAX_ATR = 0.08
BTC_STAGE7_STRONG_EXIT_EARLY_CUT_LOSS_BONUS_ATR = 0.20

# ===== BTC regime filter для альтов =====
# Для альтов торгуем только в сторону старшего режима BTC.
# LONG по альтам разрешаем только если BTC HTF bullish,
# SHORT — только если BTC HTF bearish.
BTC_REGIME_FILTER_ENABLED = True
BTC_REGIME_FILTER_SYMBOL = "BTCUSDT"
BTC_REGIME_ALT_SYMBOLS = []

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
RANGE_ENTRY_ZONE_ATR = 1.15
RANGE_TARGET_BUFFER_ATR = 0.15
RANGE_RSI_LONG_MAX = 40.0
RANGE_RSI_SHORT_MIN = 72.0
RANGE_MIN_BOUNCE_BODY_ATR = 0.16
RANGE_MIN_STRETCH_FROM_MEAN_ATR = 0.70
RANGE_BOUNCE_MIN_CLOSE_POS = 0.46
RANGE_ENTRY_ADX_MAX = 28.0
RANGE_MAX_STATE_WICKINESS = 0.72
RANGE_MAX_STATE_FALSE_BREAKOUT = 0.72
RANGE_MAX_COMPRESSION_RATIO = 1.40

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
BTC_DISABLE_ALL_SHORTS = True

# Stage3 BTC profit mode: controlled pyramiding/add-on entries on strong trend continuation
BTC_LIQUIDITY_PYRAMID_ENABLED = False  # v72 cleanup: legacy liquidity pyramid disabled
BTC_LIQUIDITY_PYRAMID_MAX_ADDS = 1
BTC_LIQUIDITY_PYRAMID_RISK_FRACTION = 0.35
BTC_LIQUIDITY_PYRAMID_MIN_PROGRESS_ATR = 0.22
BTC_LIQUIDITY_PYRAMID_MAX_ADX_H = 22.5
BTC_LIQUIDITY_PYRAMID_MAX_DRIFT_PCT = 0.0050
BTC_LIQUIDITY_PYRAMID_ALLOW_AFTER_TP1 = True
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
ALT_STRONG_SETUP_RISK_MULT = 1.36

# ===== Stage 7: first alt engine cleanup =====
ALT_V1_UPGRADE_ENABLED = True
ALT_V1_CONT_LONG_MIN_SCORE = 0.50
ALT_V1_CONT_LONG_MIN_BTC_SCORE = 1.00
ALT_V1_CONT_LONG_MIN_RS_RATIO = 1.0035
ALT_V1_CONT_LONG_WEAK_RISK_MULT = 0.90
ALT_V1_CONT_SHORT_MIN_SCORE = 0.54
ALT_V1_CONT_SHORT_MIN_BTC_SCORE = 1.12
ALT_V1_CONT_SHORT_MAX_RS_RATIO = 0.9965
ALT_V1_CONT_SHORT_REQUIRE_STRONG_SETUP = True
ALT_V1_CONT_SHORT_RISK_MULT = 0.72
ALT_V1_CONT_SHORT_STRONG_RISK_MULT = 0.85

# ===== Stage 7.2: alt regime filter =====
ALT_V2_REGIME_FILTER_ENABLED = True
ALT_V2_LONG_MIN_BTC_SCORE = 1.00
ALT_V2_LONG_MIN_ALT_SCORE = 0.50
ALT_V2_LONG_MIN_RS_RATIO = 1.0025
ALT_V2_LONG_MIN_ADX = 20.0
ALT_V2_LONG_MIN_DRIFT_PCT = 0.0050
ALT_V2_LONG_MIN_VOLUME_IMPULSE = 0.55
ALT_V2_LONG_BLOCK_SOFT_PASSES = True
ALT_V2_LONG_ALLOW_TRANSITION_STRONG_SETUP = False
ALT_V2_SHORT_MIN_BTC_SCORE = 1.10
ALT_V2_SHORT_MIN_ALT_SCORE = 0.56
ALT_V2_SHORT_MAX_RS_RATIO = 0.9970
ALT_V2_SHORT_MIN_ADX = 24.0
ALT_V2_SHORT_MIN_DRIFT_PCT = 0.0065
ALT_V2_SHORT_MIN_VOLUME_IMPULSE = 0.60
ALT_V2_SHORT_BLOCK_SOFT_PASSES = True
ALT_V2_SHORT_REQUIRE_STRONG_SETUP = True
ALT_V2_SHORT_ALLOW_TRANSITION = False

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
# Legacy DD cooldown-параметры удалены: активного runtime-path для них в проекте нет.

# ===== Runtime environment / credentials =====
# Настройки окружения вычитываются из переменных среды, чтобы ключи и токены
# не лежали в коде / репозитории. Для локального запуска удобно использовать .env.

# Файл состояния (его можно переопределять, если нужно вести несколько ботов)
STATE_FILE = _env_str("BOT_STATE_FILE", "bot_state.json")

# Версия стратегии/конфига — можно использовать в логах и state
STRATEGY_VERSION = _env_str("STRATEGY_VERSION", "mtf_breakout_regime_range_v1")

# ===== Telegram-уведомления =====
# Если TELEGRAM_ENABLED=1 и заданы токен и chat_id, бот будет слать уведомления.
TELEGRAM_ENABLED = _env_bool("TELEGRAM_ENABLED", True)
TELEGRAM_BOT_TOKEN="8269222363:AAF6vM7-ydXHJjBiq42MDK4jWn5sYbIub7w"
TELEGRAM_CHAT_ID="351630680"

# ===== Protective layer (Step9) =====
# Жёсткий лимит по просадке от пика equity (0 = выключено)
HARD_MAX_DRAWDOWN_PCT = _env_float("HARD_MAX_DRAWDOWN_PCT", 0.0)

# Лимит сделок в час (по открытиям позиций); 0 = без ограничения
MAX_TRADES_PER_HOUR = _env_int("MAX_TRADES_PER_HOUR", 20)

# Минимальный интервал между повторными входами по одному и тому же символу (анти-луп), сек
MIN_REOPEN_INTERVAL_SEC = _env_int("MIN_REOPEN_INTERVAL_SEC", 300)

# Максимально допустимая "тишина" по WebSocket (сек); 0 = не проверять
WS_STALE_SECONDS = _env_int("WS_STALE_SECONDS", 900)

# Отключать ли торговлю при рассинхронизации позиций биржа/локальный стейт
POSITION_MISMATCH_DISABLE = _env_bool("POSITION_MISMATCH_DISABLE", True)

# ===== Live preload history =====
PRELOAD_HISTORY = _env_bool('PRELOAD_HISTORY', True)
PRELOAD_15M_LIMIT = _env_int('PRELOAD_15M_LIMIT', 500)
PRELOAD_1H_LIMIT  = _env_int('PRELOAD_1H_LIMIT', 200)

# ===== Step 6. Улучшенное сопровождение позиции =====
# Цель: стабильнее забирать импульс и меньше отдавать накопленную прибыль назад.
# 1) TP1 делаем ближе, чтобы чаще фиксировать часть импульса;
# 2) перевод в BE включаем раньше и с небольшим запасом на комиссии;
# 3) трейлинг ведём от лучшей достигнутой цены, а не от каждого нового close.
POSITION_TP1_ATR_MULT = 6.0
POSITION_TP1_CLOSE_FRACTION = 0.20
POSITION_BE_TRIGGER_ATR = 1.6
POSITION_BE_OFFSET_ATR = 0.10
POSITION_BE_ONLY_AFTER_TP1 = False
POSITION_TRAILING_ACTIVATION_ATR = 4.8
POSITION_TRAILING_ATR_MULT = 3.2
POSITION_TRAILING_STEP_ATR = 0.12
POSITION_TRAILING_ONLY_AFTER_TP1 = False
POSITION_TIME_STOP_AFTER_TP1_BARS = 8
POSITION_RUNNER_STALL_BARS = 8
POSITION_RUNNER_STALL_ONLY_AFTER_TP1 = True
POSITION_RUNNER_ACTIVATION_ATR_AFTER_TP1 = 0.45
POSITION_RUNNER_ACTIVATION_ATR_AFTER_TP1_TREND = 0.55
POSITION_RUNNER_ACTIVATION_ATR_AFTER_TP1_RANGE = 0.20
POSITION_MOVE_BE_ON_TP1 = True
POSITION_BE_MIN_PROGRESS_AFTER_TP1_ATR = 0.35
POSITION_BE_MIN_PROGRESS_AFTER_TP1_ATR_TREND = 0.55
POSITION_BE_MIN_PROGRESS_AFTER_TP1_ATR_RANGE = 0.10
POSITION_PROFIT_LOCK_TRIGGER_ATR = 2.8
POSITION_PROFIT_LOCK_ATR = 0.6
POSITION_PROFIT_LOCK_ONLY_AFTER_TP1 = False
POSITION_PROFIT_LOCK_TRIGGER_ATR_TREND = 3.2
POSITION_PROFIT_LOCK_ATR_TREND = 0.9
POSITION_PROFIT_LOCK_TRIGGER_ATR_RANGE = 1.2
POSITION_PROFIT_LOCK_ATR_RANGE = 0.20
POSITION_PROFIT_LOCK_TRIGGER_ATR_CONTINUATION = 2.2
POSITION_PROFIT_LOCK_ATR_CONTINUATION = 0.55
POSITION_EARLY_EXIT_ONLY_BEFORE_TP1 = True
POSITION_EARLY_EXIT_BARS = 12
POSITION_EARLY_EXIT_MIN_PROGRESS_ATR = 0.35
POSITION_EARLY_EXIT_BARS_TREND = 15
POSITION_EARLY_EXIT_MIN_PROGRESS_ATR_TREND = 0.34
POSITION_EARLY_EXIT_BARS_RANGE = 6
POSITION_EARLY_EXIT_MIN_PROGRESS_ATR_RANGE = 0.22
POSITION_EARLY_CUT_ONLY_BEFORE_TP1 = True
POSITION_EARLY_CUT_LOSS_ATR = 1.70
POSITION_EARLY_CUT_MAX_PROGRESS_ATR = 0.20
POSITION_EARLY_CUT_LOSS_ATR_TREND = 1.90
POSITION_EARLY_CUT_MAX_PROGRESS_ATR_TREND = 0.25
POSITION_EARLY_CUT_LOSS_ATR_RANGE = 0.70
POSITION_EARLY_CUT_MAX_PROGRESS_ATR_RANGE = 0.12

# Backtest realism
BACKTEST_INTRABAR_EXIT_ORDER = "conservative"
BACKTEST_SLIPPAGE_BPS = 1.0
BACKTEST_APPLY_SLIPPAGE = True

# ===== Continuation / trade-type params =====
CONTINUATION_ALLOW_IN_TRANSITION = False
CONTINUATION_TOUCH_ATR = 0.35
CONTINUATION_MIN_BODY_ATR = 0.32
CONTINUATION_MIN_CLOSE_POS = 0.58
CONTINUATION_MIN_VOL_RATIO = 0.94
CONTINUATION_REQUIRE_PREV_PULLBACK = True
CONTINUATION_STRONG_BYPASS_PREV_PULLBACK = False
CONTINUATION_RSI_LONG_MIN = 47.0
CONTINUATION_RSI_LONG_MAX = 65.0
CONTINUATION_RSI_SHORT_MIN = 34.0
CONTINUATION_RSI_SHORT_MAX = 54.0
CONTINUATION_MIN_HTF_ADX = 22.0
CONTINUATION_PULLBACK_DEPTH_ATR = 1.00
CONTINUATION_SOFT_REJECTION = 0.0

# ===== v4-style risk model =====
RISK_MULTIPLIER_IMPULSE = 1.00
RISK_MULTIPLIER_CONTINUATION = 0.78
RISK_MULTIPLIER_RANGE = 0.48

# ===== Range filters =====
# values are defined in the main range section above to avoid duplicates

# ===== v6 entries kept in code, but feature-gated in v7 =====
ENABLE_FAKEOUT = False
ENABLE_CONT_COMP = False
RISK_MULTIPLIER_FAKEOUT = 0.45
RISK_MULTIPLIER_CONT_COMP = 0.60
FAKEOUT_PIERCE_ATR = 0.14
FAKEOUT_MIN_BODY_ATR = 0.24
FAKEOUT_MIN_VOL_RATIO = 0.84
FAKEOUT_MAX_ADX = 26.0
FAKEOUT_RSI_LONG_MAX = 35.0
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
POSITION_TP1_ATR_MULT_TREND = 6.2
POSITION_TP1_CLOSE_FRACTION_TREND = 0.18
POSITION_BE_TRIGGER_ATR_TREND = 1.8
POSITION_BE_OFFSET_ATR_TREND = 0.10
POSITION_TRAILING_ACTIVATION_ATR_TREND = 5.2
POSITION_TRAILING_ATR_MULT_TREND = 3.6
POSITION_TRAILING_STEP_ATR_TREND = 0.12

POSITION_TP1_ATR_MULT_RANGE = 1.2
POSITION_TP1_CLOSE_FRACTION_RANGE = 0.85
POSITION_BE_TRIGGER_ATR_RANGE = 0.42
POSITION_BE_OFFSET_ATR_RANGE = 0.02
POSITION_TRAILING_ACTIVATION_ATR_RANGE = 1.3
POSITION_TRAILING_ATR_MULT_RANGE = 1.0
POSITION_TRAILING_STEP_ATR_RANGE = 0.06
POSITION_TIME_STOP_BEFORE_TP1_BARS_RANGE = 5
POSITION_TIME_STOP_AFTER_TP1_BARS_RANGE = 3
POSITION_INITIAL_SL_ATR_MULT_RANGE = 0.90

POSITION_RUNNER_ACTIVATION_ATR_AFTER_TP1_CONTINUATION = 0.35

POSITION_INITIAL_SL_ATR_MULT = 3.0
POSITION_INITIAL_SL_ATR_MULT_TREND = 3.0
POSITION_TIME_STOP_BEFORE_TP1_BARS = 0
POSITION_TIME_STOP_BEFORE_TP1_BARS_TREND = 0

# ===== Stage 6: BTC/ETH scaling + alt mean reversion =====
# Усиливаем directional-сетапы на BTC/ETH через risk scaling,
# а для SOL/BNB/AVAX добавляем отдельную mean-reversion ветку.
ENABLE_DIRECTIONAL_RISK_SCALING = True
ENABLE_SMART_DIRECTIONAL_SCALING = True
# v6.1 simple boost: BTC-only, looser thresholds, no smart scaling
DIRECTIONAL_SCALING_SYMBOLS = ["BTCUSDT"]
STRONG_SETUP_RISK_MULT = 1.32
VERY_STRONG_SETUP_RISK_MULT = 1.72
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

# v7 direct boost: explicit BTC long risk boost at signal generation time.
V7_DIRECT_BOOST_ENABLED = True
V7_DIRECT_BOOST_SYMBOLS = ["BTCUSDT"]
V7_DIRECT_BOOST_ALLOWED_TYPES = ["impulse", "continuation", "cont_compression"]
V7_DIRECT_BOOST_SIDE = "long"
V7_DIRECT_BOOST_MIN_ADX = 25.5
V7_DIRECT_BOOST_MIN_DRIFT_PCT = 0.0068
V7_DIRECT_BOOST_MIN_IMPULSE = 0.75
V7_DIRECT_BOOST_REQUIRES_STRONG_SETUP = True
V7_DIRECT_BOOST_MULT = 1.72

V6_ENABLE_BTC_BOOST = True
V6_BOOST_SYMBOLS = ["BTCUSDT"]
V6_BOOST_TRADE_TYPES = ["impulse", "continuation"]
V6_BOOST_MIN_HTF_ADX = 27.0
V6_BOOST_MIN_DRIFT_PCT = 0.0074
V6_BOOST_MIN_IMPULSE_SCORE = 0.90
V6_BOOST_MULT_STRONG = 1.15
V6_BOOST_MULT_VERY_STRONG = 1.20

V78_SELECTIVE_RISK_ENABLED = False  # v72 cleanup: obsolete selective risk disabled
V78_SELECTIVE_RISK_SYMBOLS = ["BTCUSDT"]
V78_SELECTIVE_RISK_ALLOWED_TYPES = ["impulse", "continuation", "cont_compression"]
V78_SELECTIVE_RISK_SIDE = "long"
V78_RISK_MILD_MULT = 0.93
V78_RISK_SEVERE_MULT = 0.84
V78_STRONG_SETUP_MILD_MULT = 0.98
V78_STRONG_SETUP_SEVERE_MULT = 0.93
V78_MILD_MARKET_STATES = ["transition"]
V78_SEVERE_MARKET_STATES = ["chop", "range", "flat"]
V78_MILD_REGIMES = []
V78_SEVERE_REGIMES = ["bear"]
V78_MILD_GATE_FRAGMENTS = ["trend_quality", "trend_not_clean", "chop"]
V78_SEVERE_GATE_FRAGMENTS = ["transition_guard_failed", "transition_rsi_guard_failed", "non_directional_market_state", "regime_mismatch"]
V78_MILD_MIN_EMA20_CROSSES = 2
V78_SEVERE_MIN_EMA20_CROSSES = 3
V78_MILD_MIN_WICKINESS = 0.50
V78_SEVERE_MIN_WICKINESS = 0.58
V78_MILD_MAX_BODY_RATIO = 0.38
V78_SEVERE_MAX_BODY_RATIO = 0.30
V78_MILD_MAX_EMA20_SLOPE_PCT = 0.0036
V78_MILD_MAX_EMA50_SLOPE_PCT = 0.0018
V78_SEVERE_MAX_EMA20_SLOPE_PCT = 0.0025
V78_SEVERE_MAX_EMA50_SLOPE_PCT = 0.0012
V78_MILD_MAX_IMPULSE_SCORE = 0.95
V78_EXTRA_HAIRCUT_IF_BOOST_WITHOUT_STRONG_SETUP = True

V52_MEAN_REVERSION_ENABLED = False  # v72 cleanup: legacy MR disabled
V52_MR_SYMBOLS = ["BTCUSDT"]
V52_MR_CORE_SYMBOLS = ["BTCUSDT"]
V52_MR_ALLOWED_STATES = ["range", "transition"]
V52_MR_ALLOW_SHORT_CORE = False
V52_MR_ALLOW_SHORT_ALT = False
V52_MR_RISK_MULTIPLIER_CORE = 0.45
V52_MR_RISK_MULTIPLIER_ALT = 0.35
V52_MR_Z_WINDOW = 20
V52_MR_BB_STD = 2.0
V52_MR_Z_THRESHOLD = 1.35
V52_MR_DEV_ATR_THRESHOLD = 1.35
V52_MR_RSI_LONG_MAX = 32.0
V52_MR_RSI_SHORT_MIN = 65.0
V52_MR_MIN_VOL_RATIO = 0.90
V52_MR_MAX_HTF_ADX = 19.0
V52_MR_MAX_LTF_ADX = 20.0
V52_MR_MAX_HTF_EMA_SPREAD_PCT = 0.0070
V52_MR_HTF_RSI_MIN = 38.0
V52_MR_HTF_RSI_MAX = 62.0
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
PULLBACK_TREND_SYMBOLS = ["BTCUSDT"]
PULLBACK_TREND_ALLOW_IN_TRANSITION = True
PULLBACK_TOUCH_ATR = 0.90
PULLBACK_MAX_DEEP_TOUCH_ATR = 1.55
PULLBACK_MIN_BODY_ATR = 0.16
PULLBACK_MIN_CLOSE_POS = 0.48
PULLBACK_MIN_VOL_RATIO = 0.60
PULLBACK_MIN_HTF_ADX = 16.0
PULLBACK_RSI_LONG_MIN = 46.0
PULLBACK_RSI_LONG_MAX = 63.0
PULLBACK_RSI_SHORT_MIN = 37.0
PULLBACK_RSI_SHORT_MAX = 54.0
PULLBACK_REQUIRE_PREV_COUNTER_CANDLE = False
PULLBACK_PREV_CLOSE_POS_MAX = 0.62
PULLBACK_RECLAIM_EMA20_REQUIRED = False
PULLBACK_PRE_IMPULSE_BARS = 8
PULLBACK_PRE_IMPULSE_MIN_ATR = 0.85
PULLBACK_PRE_IMPULSE_MIN_ATR_SHORT = 1.15
PULLBACK_MAX_EMA20_CROSSES = 4
PULLBACK_MAX_AVG_WICK_RATIO = 0.62
PULLBACK_MIN_EMA20_SLOPE_PCT = 0.00018
PULLBACK_MIN_EMA50_SLOPE_PCT = 0.00010
PULLBACK_MIN_EMA20_SLOPE_PCT_SHORT = 0.00028
PULLBACK_MIN_EMA50_SLOPE_PCT_SHORT = 0.00016

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

# === V5.4 FINAL FIX ===
V54_ETH_MR_ONLY = False
V54_ETH_DISABLE_SHORTS = False
V54_ETH_MR_RISK_MULTIPLIER = 0.04
V54_MR_RISK_MULTIPLIER_CORE = 0.35
V54_MR_RISK_MULTIPLIER_ALT = 0.20

# ===== V8.0 short control + alt engine upgrade =====
V80_SHORT_CONTROL_ENABLED = True
V80_SHORT_CONTROL_SYMBOLS = ["BTCUSDT"]
V80_SHORT_CONTROL_ALLOWED_TYPES = ["impulse", "continuation", "cont_compression", "pullback"]
V80_SHORT_REQUIRE_BEAR_REGIME = True
V80_SHORT_MILD_MARKET_STATES = ["transition"]
V80_SHORT_SEVERE_MARKET_STATES = ["chop", "range", "flat"]
V80_SHORT_MIN_BTC_SCORE = 1.02
V80_SHORT_MILD_MIN_BTC_SCORE = 1.08
V80_SHORT_MAX_RS_RATIO = 0.98
V80_SHORT_MILD_MIN_EMA20_CROSSES = 2
V80_SHORT_SEVERE_MIN_EMA20_CROSSES = 3
V80_SHORT_MILD_MIN_WICKINESS = 0.50
V80_SHORT_SEVERE_MIN_WICKINESS = 0.58
V80_SHORT_MILD_MAX_BODY_RATIO = 0.38
V80_SHORT_SEVERE_MAX_BODY_RATIO = 0.30
V80_SHORT_RISK_MILD_MULT = 0.92
V80_SHORT_RISK_SEVERE_MULT = 0.82
V80_SHORT_STRONG_SETUP_MILD_MULT = 0.96
V80_SHORT_STRONG_SETUP_SEVERE_MULT = 0.90

V80_ALT_ENGINE_ENABLED = False  # v82: failed ETH/SOL port disabled
V80_ALT_ENGINE_ALLOWED_TYPES = ["impulse", "continuation", "cont_compression"]
V80_ALT_MIN_BTC_SCORE = 1.02
V80_ALT_MIN_ALT_SCORE = 1.03
V80_ALT_LONG_MIN_RS_RATIO = 1.00
V80_ALT_SHORT_MAX_RS_RATIO = 1.00
V80_ALT_MIN_ADX = 21.0
V80_ALT_MIN_DRIFT_PCT = 0.0044
V80_ALT_MIN_IMPULSE_SCORE = 0.72
V80_ALT_WEAK_RISK_MULT = 0.78
V80_ALT_NORMAL_RISK_MULT = 0.88
V80_ALT_STRONG_RISK_MULT = 0.98
V80_ALT_STRONG_MIN_BTC_SCORE = 1.13
V80_ALT_STRONG_MIN_ALT_SCORE = 1.13
V80_ALT_STRONG_MIN_IMPULSE_SCORE = 0.96
V80_ALT_STRONG_MIN_ADX = 27.0
V80_ALT_STRONG_LONG_MIN_RS_RATIO = 1.040
V80_ALT_STRONG_SHORT_MAX_RS_RATIO = 0.965

V81_SHORT_RISK_ENABLED = True
V81_SHORT_RISK_SYMBOLS = ["BTCUSDT"]
V81_SHORT_RISK_ALLOWED_TYPES = ["impulse", "continuation", "cont_compression", "pullback"]
V81_SHORT_BASE_MULT = 0.88
V81_SHORT_BAD_MARKET_MULT = 0.74
V81_SHORT_WEAK_SETUP_MULT = 0.82
V81_SHORT_WEAK_IMPULSE_MAX = 0.82
V81_SHORT_WEAK_IMPULSE_MULT = 0.88
V81_SHORT_BAD_MARKET_STATES = ["chop", "flat", "range"]
V81_SHORT_REQUIRE_BEAR_REGIME = True

# v8.1.3 execution-layer global short risk reduction
V813_GLOBAL_SHORT_RISK_ENABLED = True
V813_GLOBAL_SHORT_BASE_MULT = 1.0
V813_GLOBAL_SHORT_BAD_MARKET_MULT = 0.72
V813_GLOBAL_SHORT_WEAK_SETUP_MULT = 0.90
V813_GLOBAL_SHORT_BAD_MARKET_STATES = ["chop", "flat", "range"]
V813_GLOBAL_SHORT_REQUIRE_BEAR_REGIME = True

# disable legacy duplicated execution-layer short haircut

# === v8.3 selective short suppression ===
V83_SHORT_SUPPRESSION_ENABLED = True
V83_SHORT_SUPPRESSION_SYMBOLS = ["BTCUSDT"]
V83_SHORT_SUPPRESSION_ALLOWED_TYPES = ["impulse", "continuation", "cont_compression", "pullback"]
V83_SHORT_BAD_MARKET_STATES = ["chop", "flat", "range", "transition"]
V83_SHORT_REQUIRE_BEAR_REGIME = True
V83_SHORT_MIN_BTC_SCORE = 1.12
V83_SHORT_MAX_RS_RATIO = 0.975
V83_SHORT_MAX_EMA20_CROSSES = 2
V83_SHORT_MAX_WICKINESS = 0.52
V83_SHORT_MIN_BODY_RATIO = 0.34
V83_SHORT_REQUIRE_STRONG_SETUP = True
V83_SHORT_REQUIRE_STRONG_SETUP_TYPES = ["impulse", "continuation", "cont_compression", "pullback"]

V831_SHORT_BAD_GATE_FRAGMENTS = ["transition", "regime_mismatch", "non_directional", "blocked"]
V831_SHORT_MIN_REASON_COUNT = 1

# v8.5 inline short suppression
V85_INLINE_SHORT_SUPPRESSION_ENABLED = True
V85_INLINE_SHORT_SUPPRESSION_SYMBOLS = ["BTCUSDT"]
V85_INLINE_SHORT_SUPPRESSION_ALLOWED_TYPES = ["impulse", "continuation", "cont_compression", "pullback", "fakeout", "btc_exhaustion"]
V85_SHORT_BAD_MARKET_STATES = ["chop", "flat", "range", "transition"]
V85_SHORT_REQUIRE_BEAR_REGIME = True
V85_SHORT_MIN_BTC_SCORE = 1.12
V85_SHORT_MAX_RS_RATIO = 0.975
V85_SHORT_MAX_EMA20_CROSSES = 2
V85_SHORT_MAX_WICKINESS = 0.52
V85_SHORT_MIN_BODY_RATIO = 0.34
V85_SHORT_REQUIRE_STRONG_SETUP = True
V85_SHORT_REQUIRE_STRONG_SETUP_TYPES = ["impulse", "continuation", "cont_compression", "pullback"]
V85_SHORT_BAD_GATE_FRAGMENTS = ["transition", "regime_mismatch", "non_directional"]
V85_SHORT_MIN_REASON_COUNT = 1

# v8.6 inline long suppression
V86_INLINE_LONG_SUPPRESSION_ENABLED = True
V86_INLINE_LONG_SUPPRESSION_SYMBOLS = ["BTCUSDT"]
V86_INLINE_LONG_SUPPRESSION_ALLOWED_TYPES = ["impulse", "continuation", "cont_compression", "pullback", "fakeout"]
V86_LONG_BAD_MARKET_STATES = ["chop", "flat", "range"]
V86_LONG_BAD_REGIMES = ["bear"]
V86_LONG_MIN_BTC_SCORE = 1.04
V86_LONG_MIN_RS_RATIO = 0.985
V86_LONG_MAX_EMA20_CROSSES = 3
V86_LONG_MAX_WICKINESS = 0.58
V86_LONG_MIN_BODY_RATIO = 0.30
V86_LONG_MIN_ADX = 18.0
V86_LONG_MIN_DRIFT_PCT = 0.0030
V86_LONG_MIN_IMPULSE_SCORE = 0.74
V86_LONG_BAD_GATE_FRAGMENTS = ["non_directional", "regime_mismatch"]
V86_LONG_REQUIRE_STRONG_SETUP = False
V86_LONG_REQUIRE_STRONG_SETUP_TYPES = ["continuation", "cont_compression"]
V86_LONG_MIN_REASON_COUNT = 3

# ALT trace logging
ALT_TRACE_BUILD_ENABLED = False  # v82: alt trace disabled
ALT_TRACE_STDOUT_ENABLED = False
ALT_TRACE_FILE_ENABLED = False  # v82: alt trace disabled
ALT_TRACE_FILE_PATH = "alt_trace_only.txt"
ALT_TRACE_RESET_FILE_ON_START = True
ALT_TRACE_SYMBOLS = ["ETHUSDT"]

BTC_RANGE_DEBUG_ENABLED = False  # v82: range debug disabled
BTC_RANGE_DEBUG_STDOUT_ENABLED = False
BTC_RANGE_DEBUG_FILE_ENABLED = True
BTC_RANGE_DEBUG_FILE_PATH = "btc_range_debug_trace.txt"
BTC_RANGE_DEBUG_RESET_FILE_ON_START = True
BTC_RANGE_DEBUG_SYMBOLS = ["BTCUSDT"]
BTC_RANGE_DEBUG_MAX_NO_SIGNAL_LOGS = 250

# v2.6 alt unblock
ALT_IGNORE_SESSION_FILTER = True
ALT_DISABLE_HTF_VOLATILE_DRIFTLESS_FILTER = True
ALT_DISABLE_LTF_VOLATILE_DRIFTLESS_FILTER = True
ALT_CONTINUATION_ALLOW_IN_RANGE = False
ALT_ALLOW_WEAK_BREAKOUT_VOLUME = True

ALT_NEAR_TRIGGER_ALLOW = True
ALT_ENTRY_TRIGGER_TOLERANCE_PCT = 0.0035
ALT_ENTRY_RSI_PAD = 6.0
ALT_NEAR_TRIGGER_RISK_MULT = 0.80
# v2.8 final alt entry execution fix


# v17 moderate-alt trade-type filter
ALT_CONTINUATION_DISABLE_IN_TRANSITION = True


# v18 ALT rebuild: only momentum-long paths for selected alts.


# v21 regime-aware long sizing: preserve strong-trend upside while protecting mid/weak conditions
V21_REGIME_AWARE_ENABLED = True
V21_REGIME_AWARE_SYMBOLS = ["BTCUSDT"]
V21_REGIME_AWARE_TYPES = ["impulse", "continuation"]
V21_BTC_BOOST_MIN_ADX = 28.0
V21_BTC_BOOST_MIN_DRIFT_PCT = 0.0078
V21_BTC_BOOST_MIN_IMPULSE = 0.92
V21_BTC_IMPULSE_BOOST_MULT = 1.08
V21_BTC_CONT_BOOST_MULT = 1.04
V21_BTC_TRANSITION_CONT_MULT = 0.88
V21_BTC_TRANSITION_IMPULSE_MULT = 0.94
V21_BTC_CONT_SOFT_MIN_ADX = 24.0
V21_BTC_CONT_SOFT_MIN_DRIFT_PCT = 0.0062
V21_BTC_CONT_SOFT_HAIRCUT = 0.90
V21_ETH_BOOST_MIN_ADX = 24.0
V21_ETH_BOOST_MIN_DRIFT_PCT = 0.0058
V21_ETH_TREND_BOOST_MULT = 1.02
V21_ETH_WEAK_REGIME_MULT = 0.84
V21_ETH_SOFT_MIN_ADX = 22.5
V21_ETH_SOFT_MIN_DRIFT_PCT = 0.0054
V21_ETH_SOFT_HAIRCUT = 0.90


# v22 dual-strategy: keep trend engine for trend markets and add a non-trend long engine
# for BTC/ETH in range/transition conditions.
V22_DUAL_STRATEGY_ENABLED = True
V22_DUAL_STRATEGY_SYMBOLS = ["BTCUSDT"]
V22_NON_TREND_STATES = ["range", "transition"]
V22_MR_LONG_RISK_MULT = 0.82
V22_RECLAIM_MAX_HTF_ADX = 24.0
V22_RECLAIM_MAX_DRIFT_PCT = 0.0060
V22_RECLAIM_MIN_VOL_RATIO = 0.95
V22_RECLAIM_MIN_BODY_ATR = 0.18
V22_RECLAIM_MIN_CLOSE_POS = 0.58
V22_RECLAIM_MAX_WICKINESS = 0.70
V22_RECLAIM_MAX_FALSE_BREAKOUT = 0.60
V22_RECLAIM_MIN_EMA20_RECLAIM_PCT = 0.0004
V22_RECLAIM_RSI_MIN = 42.0
V22_RECLAIM_RSI_MAX = 58.0
V22_RECLAIM_HTF_RSI_MIN = 46.0
V22_RECLAIM_TRANSITION_MULT = 0.78
V22_RECLAIM_RISK_MULTIPLIER_BTC = 0.30
V22_RECLAIM_RISK_MULTIPLIER_ETH = 0.12
V22_ENGINE_MAX_HTF_ADX = 20.5
V22_ENGINE_MAX_DRIFT_PCT = 0.0044
V22_MR_ENABLED = True
V22_BTC_MR_ENABLED = True
V22_ETH_MR_ENABLED = False
V22_MR_ALLOWED_STATES = ["range"]
V22_RECLAIM_MAX_HTF_ADX_BTC = 18.0
V22_RECLAIM_MAX_HTF_ADX_ETH = 18.0
V22_RECLAIM_MAX_DRIFT_PCT_BTC = 0.0034
V22_RECLAIM_MAX_DRIFT_PCT_ETH = 0.0038
V22_RECLAIM_MIN_VOL_RATIO_BTC = 1.00
V22_RECLAIM_MIN_VOL_RATIO_ETH = 1.02
V22_RECLAIM_MIN_BODY_ATR_BTC = 0.24
V22_RECLAIM_MIN_BODY_ATR_ETH = 0.24
V22_RECLAIM_MIN_CLOSE_POS_BTC = 0.62
V22_RECLAIM_MIN_CLOSE_POS_ETH = 0.64
V22_RECLAIM_MAX_WICKINESS_BTC = 0.64
V22_RECLAIM_MAX_WICKINESS_ETH = 0.56
V22_RECLAIM_MAX_FALSE_BREAKOUT_BTC = 0.54
V22_RECLAIM_MAX_FALSE_BREAKOUT_ETH = 0.42
V22_RECLAIM_MIN_EMA20_RECLAIM_PCT_BTC = 0.0003
V22_RECLAIM_MIN_EMA20_RECLAIM_PCT_ETH = 0.0012
V22_RECLAIM_RSI_MIN_BTC = 40.0
V22_RECLAIM_RSI_MAX_BTC = 62.0
V22_RECLAIM_RSI_MIN_ETH = 45.0
V22_RECLAIM_RSI_MAX_ETH = 55.0
V22_RECLAIM_HTF_RSI_MIN_BTC = 44.0
V22_RECLAIM_HTF_RSI_MIN_ETH = 50.0

# v23 selective non-trend guards
V23_MR_MAX_HTF_ADX_BTC = 21.5
V23_MR_MAX_HTF_ADX_ETH = 15.5
V23_MR_MAX_DRIFT_PCT_BTC = 0.0048
V23_MR_MAX_DRIFT_PCT_ETH = 0.0028
V23_MR_MAX_VOL_RATIO_BTC = 1.14
V23_MR_MAX_VOL_RATIO_ETH = 1.02
V23_MR_MAX_BODY_ATR = 0.50
V23_MR_RISK_MULT_BTC = 0.58
V23_MR_RISK_MULT_ETH = 0.80
V23_ENGINE_MAX_VOL_RATIO_BTC = 1.12
V23_ENGINE_MAX_VOL_RATIO_ETH = 1.05
V23_ENGINE_MAX_BODY_ATR_BTC = 0.58
V23_ENGINE_MAX_BODY_ATR_ETH = 0.48
V23_ENGINE_MAX_CLOSE_POS_BTC = 0.88
V23_ENGINE_MAX_CLOSE_POS_ETH = 0.82


# V24 BTC profit engine
V24_PROFIT_ENGINE_ENABLED = True
V24_PROFIT_ENGINE_SYMBOLS = ["BTCUSDT"]
V24_PROFIT_ENGINE_TYPES = ["impulse", "continuation"]
V24_STRONG_MIN_ADX = 27.0
V24_STRONG_MIN_DRIFT_PCT = 0.0070
V24_STRONG_MIN_IMPULSE = 0.86
V24_STRONG_MULT = 1.10
V24_VERY_STRONG_MIN_ADX = 30.0
V24_VERY_STRONG_MIN_DRIFT_PCT = 0.0082
V24_VERY_STRONG_MIN_IMPULSE = 0.96
V24_VERY_STRONG_MULT = 1.18
V24_CONT_CAP_MULT = 1.14
V24_WEAK_CONT_MAX_ADX = 23.0
V24_WEAK_CONT_MAX_DRIFT_PCT = 0.0058
V24_WEAK_CONT_MAX_IMPULSE = 0.78
V24_WEAK_CONT_HAIRCUT = 0.92


# === V25 Position Sizing Engine ===
V25_POSITION_SIZING_ENABLED = True
V25_POSITION_SIZING_SYMBOLS = ["BTCUSDT"]
V25_MIN_RISK_PER_TRADE = 0.0045
V25_MAX_RISK_PER_TRADE = 0.0280  # base cap; V70 can override for approved BTC pullbacks
V25_BTC_VERY_STRONG_MIN_EXEC_MULT = 2.30
V25_BTC_VERY_STRONG_RISK_MULT = 1.55
V25_BTC_STRONG_MIN_EXEC_MULT = 1.75
V25_BTC_STRONG_RISK_MULT = 1.32
V25_BTC_VERY_STRONG_MIN_IMPULSE = 0.92
V25_BTC_STRONG_MIN_IMPULSE = 0.82
V25_BTC_STRONG_CONT_MIN_EXEC_MULT = 2.00
V25_BTC_STRONG_CONT_MIN_IMPULSE = 0.88
V25_BTC_STRONG_CONT_RISK_MULT = 1.18
V25_BTC_WEAK_MAX_EXEC_MULT = 1.05
V25_BTC_WEAK_MIN_IMPULSE = 0.72
V25_BTC_WEAK_RISK_MULT = 0.30
V25_ETH_BASE_RISK_MULT = 0.40
V25_ETH_STRONG_RISK_MULT = 0.55
V25_ETH_STRONG_MIN_EXEC_MULT = 1.90
V25_DD_MILD_PCT = 5.0
V25_DD_MILD_MULT = 0.86
V25_DD_SEVERE_PCT = 10.0
V25_DD_SEVERE_MULT = 0.68
V26_BTC_ONLY_AGGRESSIVE_MODE = True
V26_BTC_ONLY_SYMBOLS = ["BTCUSDT"]

V26_1_SMART_AGGRESSIVE_MODE = True

# ===== Stage8.2: range engine diagnostics =====
BACKTEST_INCLUDE_TRADE_DIAGNOSTICS = True

# --- Stage10 v2: controlled BTC MR fallback ---
BTC_LIQUIDITY_REVERSAL_ENABLED = True
BTC_LIQUIDITY_REVERSAL_ALLOWED_STATES = ["range", "flat", "transition"]
BTC_LIQUIDITY_REVERSAL_MAX_ADX_H = 22.0
BTC_LIQUIDITY_REVERSAL_MAX_DRIFT_PCT = 0.0049
BTC_LIQUIDITY_REVERSAL_RISK_MULT = 0.65
BTC_LIQUIDITY_REVERSAL_COOLDOWN_BARS = 48
BTC_LIQUIDITY_MAX_SIGNALS_PER_DAY = 2

BTC_STAGE10V2_BASIC_MR_ENABLED = True
BTC_STAGE10V2_BASIC_MR_ALLOWED_STATES = ["range", "flat"]

# ===== BTC Separate Range Engine v1 =====
BTC_RANGE_ENGINE_V1_ENABLED = True
BTC_RANGE_ENGINE_V1_ALLOWED_MARKET_STATES = ["range", "flat", "chop", "transition"]
BTC_RANGE_ENGINE_V1_ALLOWED_RANGE_REGIMES = ["quiet_range", "liquidity_sweep_range", "transition_range", "volatile_range"]
BTC_RANGE_ENGINE_V1_ALLOWED_SETUPS = ["reaction_range"]
BTC_RANGE_ENGINE_V1_COOLDOWN_BARS = 14
BTC_RANGE_ENGINE_V1_RANGE_BOUNCE_RISK_MULT = 0.18
BTC_RANGE_ENGINE_V1_LIQUIDITY_REVERSAL_RISK_MULT = 0.055
BTC_RANGE_ENGINE_V1_RECLAIM_RISK_MULT = 0.030
BTC_RANGE_ENGINE_V1_QUIET_ADX_MAX = 16.0
BTC_RANGE_ENGINE_V1_QUIET_DRIFT_MAX = 0.0026
BTC_RANGE_ENGINE_V1_QUIET_WICKINESS_MAX = 0.54
BTC_RANGE_ENGINE_V1_SWEEP_FALSE_BREAKOUT_MIN = 0.24
BTC_RANGE_ENGINE_V1_SWEEP_WICKINESS_MIN = 0.46
BTC_RANGE_ENGINE_V1_VOLATILE_ADX_MAX = 20.5
BTC_RANGE_ENGINE_V1_VOLATILE_WIDTH_MIN = 0.018
BTC_RANGE_ENGINE_V1_VOLATILE_COMPRESSION_MAX = 1.18
BTC_RANGE_ENGINE_V1_RECLAIM_FLUSH_LOOKBACK = 6
BTC_RANGE_ENGINE_V1_RECLAIM_MIN_FLUSH_ATR = 0.48
BTC_RANGE_ENGINE_V1_RECLAIM_MIN_BODY_ATR = 0.24
BTC_RANGE_ENGINE_V1_RECLAIM_MIN_VOL_RATIO = 0.92
BTC_RANGE_ENGINE_V1_RECLAIM_LONG_RSI_MAX = 46.0
BTC_RANGE_ENGINE_V1_RECLAIM_SHORT_RSI_MIN = 54.0
BTC_RANGE_ENGINE_V1_RECLAIM_MAX_DIST_TO_EMA20_ATR = 0.90
BTC_RANGE_ENGINE_V1_RECLAIM_LONG_CLOSE_POS_MIN = 0.56
BTC_RANGE_ENGINE_V1_RECLAIM_SHORT_CLOSE_POS_MIN = 0.56
BTC_RANGE_ENGINE_V1_ALLOW_SHORTS = True
BTC_RANGE_ENGINE_V1_BYPASS_BTC_SHORT_BLOCK = True
BTC_RANGE_ENGINE_V1_BLOCK_IN_STRONG_TREND = True
BTC_RANGE_ENGINE_V1_MAX_MARKET_STATE_DRIFT_PCT = 0.0160
BTC_RANGE_ENGINE_V1_MAX_MARKET_STATE_ADX = 28.0
BTC_RANGE_ENGINE_V1_STRONG_TREND_ADX_MIN = 26.0
BTC_RANGE_ENGINE_V1_STRONG_TREND_DRIFT_MIN = 0.0110
BTC_RANGE_ENGINE_V1_REQUIRE_SIDE_AWAY_FROM_EMA20 = False
BTC_RANGE_ENGINE_V1_MIN_RANGE_WIDTH_PCT = 0.010
BTC_RANGE_ENGINE_V1_MAX_RANGE_WIDTH_PCT = 0.045
BTC_RANGE_ENGINE_V1_MIN_DISTANCE_TO_RANGE_MID_ATR = 0.12
BTC_RANGE_ENGINE_V1_MIN_DISTANCE_TO_EMA20_ATR = 0.00
BTC_RANGE_ENGINE_V1_MAX_DISTANCE_TO_EMA20_ATR = 2.40
BTC_RANGE_ENGINE_V1_MAX_FALSE_BREAKOUT_RATIO_FOR_BOUNCE = 0.30
BTC_RANGE_ENGINE_V1_SIMPLE_SWEEP_PIERCE_ATR = 0.10
BTC_RANGE_ENGINE_V1_SIMPLE_SWEEP_RECLAIM_ATR = 0.08
BTC_RANGE_ENGINE_V1_SIMPLE_SWEEP_MIN_BODY_ATR = 0.10
BTC_RANGE_ENGINE_V1_SIMPLE_SWEEP_LONG_RSI_MAX = 52.0
BTC_RANGE_ENGINE_V1_SIMPLE_SWEEP_SHORT_RSI_MIN = 48.0
BTC_RANGE_ENGINE_V1_SIMPLE_SWEEP_REQUIRE_PREV_CLOSE_OUTSIDE = True
BTC_RANGE_ENGINE_V1_SIMPLE_SWEEP_MIN_PREV_CLOSE_OUTSIDE_ATR = 0.04
BTC_RANGE_ENGINE_V1_SIMPLE_SWEEP_REQUIRE_PREV_DIRECTION = True
BTC_RANGE_ENGINE_V1_LIQUIDITY_MIN_INSIDE_RANGE_ATR = 0.08
BTC_RANGE_ENGINE_V1_LIQUIDITY_LONG_CLOSE_POS_MIN = 0.56
BTC_RANGE_ENGINE_V1_LIQUIDITY_SHORT_CLOSE_POS_MIN = 0.56
BTC_RANGE_ENGINE_V1_LIQUIDITY_MAX_DRIFT_PCT = 0.0105
BTC_RANGE_ENGINE_V1_SHORT_FILTER_ADX_MAX = 18.0
BTC_RANGE_ENGINE_V1_SHORT_FILTER_DRIFT_MAX = 0.0080
BTC_RANGE_ENGINE_V1_SOFT_RANGE_RISK_MULT = 0.030
BTC_RANGE_ENGINE_V1_SCALP_EDGE_ZONE_PCT = 0.20
BTC_RANGE_ENGINE_V1_SCALP_MIN_BODY_ATR = 0.00
BTC_RANGE_ENGINE_V1_SCALP_LONG_RSI_MAX = 58.0
BTC_RANGE_ENGINE_V1_SCALP_SHORT_RSI_MIN = 42.0
BTC_RANGE_ENGINE_V1_SCALP_MAX_DRIFT_PCT = 0.0160
BTC_RANGE_ENGINE_V1_SCALP_ALLOWED_REGIMES = ["quiet_range", "liquidity_sweep_range", "transition_range", "volatile_range"]
BTC_RANGE_ENGINE_V1_SCALP_CONFIRM_PREV_DIRECTION = False
BTC_RANGE_ENGINE_V1_REACTION_EDGE_ZONE_PCT = 0.16
BTC_RANGE_ENGINE_V1_REACTION_MIN_BODY_ATR = 0.12
BTC_RANGE_ENGINE_V1_REACTION_RECLAIM_ATR = 0.08
BTC_RANGE_ENGINE_V1_REACTION_LONG_CLOSE_POS_MIN = 0.62
BTC_RANGE_ENGINE_V1_REACTION_SHORT_CLOSE_POS_MIN = 0.62
BTC_RANGE_ENGINE_V1_REACTION_MAX_DRIFT_PCT = 0.0120
BTC_RANGE_ENGINE_V1_REACTION_REQUIRE_PREV_OPPOSITE = True
BTC_RANGE_ENGINE_V4_DISABLE_LEGACY_BTC_RANGE_FALLBACK = True
BTC_STAGE10V2_BASIC_MR_MAX_ADX_H = 14.0
BTC_STAGE10V2_BASIC_MR_MAX_DRIFT_PCT = 0.0024
BTC_STAGE10V2_BASIC_MR_RSI_LONG_MAX = 28.5
BTC_STAGE10V2_BASIC_MR_MIN_DEV_ATR = 1.25
BTC_STAGE10V2_BASIC_MR_MIN_CLOSE_POS = 0.72
BTC_STAGE10V2_BASIC_MR_MIN_REJECT_WICK = 0.24
BTC_STAGE10V2_BASIC_MR_MAX_BODY_ATR = 0.34
BTC_STAGE10V2_BASIC_MR_MAX_NEG_PROGRESS_ATR = 0.18
BTC_STAGE10V2_BASIC_MR_REQUIRE_GREEN_CANDLE = True
BTC_STAGE10V2_BASIC_MR_MIN_VOL_RATIO = 1.00
BTC_STAGE10V2_BASIC_MR_RISK_MULT = 0.34
BTC_STAGE10V2_BASIC_MR_COOLDOWN_BARS = 144


BTC_RANGE_ENGINE_V1_REACTION_REQUIRE_STRUCTURE_SHIFT = True
BTC_RANGE_ENGINE_V1_REACTION_BREAK_PREV_EXTREME_ATR = 0.02
BTC_RANGE_ENGINE_V1_REACTION_HL_BUFFER_ATR = 0.03
BTC_RANGE_ENGINE_V1_REACTION_ALLOWED_REGIMES = ["quiet_range", "liquidity_sweep_range", "transition_range"]


# ===== V14 multi-asset split: BTC trend-only + isolated ETH liquidity engine =====
V14_MULTI_ASSET_SPLIT_ENABLED = False  # v82 BTC-only cleanup
V14_BTC_TREND_ONLY = True
V14_ETH_LIQUIDITY_ENGINE_ENABLED = False  # v82 BTC-only cleanup
V14_ETH_DISABLE_LEGACY_NON_TREND = True
V14_ETH_DISABLE_LEGACY_TREND = True
V14_ETH_ENGINE_SYMBOLS = []  # v82: alt engines removed from active path
V14_ETH_ALLOWED_MARKET_STATES = ["range", "transition"]
V14_ETH_MAX_ADX = 35.0
V14_ETH_MAX_DRIFT_PCT = 0.0250
V14_ETH_MIN_RANGE_WIDTH_PCT = 0.008
V14_ETH_MAX_RANGE_WIDTH_PCT = 0.060
V14_ETH_EDGE_ZONE_PCT = 0.28
V14_ETH_RECLAIM_ATR = 0.06
V14_ETH_MIN_BODY_ATR = 0.06
V14_ETH_LONG_RSI_MAX = 62.0
V14_ETH_SHORT_RSI_MIN = 38.0
V14_ETH_RISK_MULT = 0.05
V14_ETH_SHORT_RISK_MULT = 0.05
V14_ETH_COOLDOWN_BARS = 10
V14_ETH_REQUIRE_PREV_OPPOSITE_CANDLE = True
V14_ETH_REQUIRE_BREAK_PREV_EXTREME = True
V14_ETH_BREAK_PREV_EXTREME_ATR = 0.00
V14_ETH_HL_BUFFER_ATR = 0.02
V14_ETH_DEBUG_ENABLED = True
V14_ETH_DEBUG_STDOUT_ENABLED = False
V14_ETH_DEBUG_FILE_ENABLED = True
V14_ETH_DEBUG_FILE_PATH = "eth_liquidity_debug_trace.txt"
V14_ETH_DEBUG_RESET_FILE_ON_START = True

# --- V15 ETH liquidity trap + momentum confirmation ---
V15_ETH_LIQUIDITY_MOMENTUM_ENABLED = True
V15_ETH_TRADE_TYPE = "eth_liquidity_momentum"
V15_ETH_MIN_MOMENTUM_BODY_ATR = 0.32
V15_ETH_MIN_MOMENTUM_RANGE_ATR = 0.55
V15_ETH_REQUIRE_CLOSE_THROUGH_PREV_EXTREME = True
V15_ETH_CLOSE_THROUGH_PREV_EXTREME_ATR = 0.02
V15_ETH_SHORT_ADX_MAX = 28.0
V15_ETH_SHORT_DRIFT_MAX = 0.0200
V15_ETH_SHORT_RISK_MULT = 0.035
V15_ETH_LONG_RISK_MULT = 0.045
V15_ETH_COOLDOWN_BARS = 16
# --- V16 ETH liquidity trap + delayed momentum confirmation ---
V16_ETH_TRADE_TYPE = "eth_liquidity_momentum_confirmed"
V16_ETH_MAX_ADX = 35.0
V16_ETH_MAX_DRIFT_PCT = 0.0250
V16_ETH_EDGE_ZONE_PCT = 0.24
V16_ETH_RECLAIM_ATR = 0.06
V16_ETH_REQUIRE_PREV_OPPOSITE_CANDLE = True
V16_ETH_HL_BUFFER_ATR = 0.02
V16_ETH_MIN_MOMENTUM_BODY_ATR = 0.45
V16_ETH_MIN_MOMENTUM_RANGE_ATR = 0.62
V16_ETH_REQUIRE_CLOSE_THROUGH_PREV_EXTREME = True
V16_ETH_CLOSE_THROUGH_PREV_EXTREME_ATR = 0.03
V16_ETH_MAX_CONFIRM_PULLBACK_ATR = 0.28
V16_ETH_MIN_CONFIRM_PROGRESS_ATR = -0.04
V16_ETH_REJECT_OPPOSITE_CONFIRM_CANDLE = True
V16_ETH_LONG_RSI_MAX = 64.0
V16_ETH_SHORT_RSI_MIN = 42.0
V16_ETH_SHORT_ADX_MAX = 25.0
V16_ETH_SHORT_DRIFT_MAX = 0.0160
V16_ETH_LONG_RISK_MULT = 0.040
V16_ETH_SHORT_RISK_MULT = 0.025
V16_ETH_COOLDOWN_BARS = 20

# --- V17 ETH hybrid: liquidity in range + separate trend momentum in trend ---
V17_ETH_HYBRID_ENABLED = True
V17_ETH_TREND_ENGINE_ENABLED = True
V17_ETH_TREND_TRADE_TYPE = "eth_trend_momentum"
V17_ETH_TREND_ALLOWED_MARKET_STATES = ["trend"]
V17_ETH_TREND_MIN_ADX = 24.0
V17_ETH_TREND_MIN_DRIFT_PCT = 0.0100
V17_ETH_TREND_MAX_DRIFT_PCT = 0.0700
V17_ETH_TREND_BREAKOUT_BUFFER_ATR = 0.05
V17_ETH_TREND_MIN_BODY_ATR = 0.22
V17_ETH_TREND_MIN_RANGE_ATR = 0.45
V17_ETH_TREND_REQUIRE_REGIME_ALIGNMENT = True
V17_ETH_TREND_ALLOW_LONG = True
V17_ETH_TREND_ALLOW_SHORT = True
V17_ETH_TREND_LONG_RISK_MULT = 0.040
V17_ETH_TREND_SHORT_RISK_MULT = 0.030
V17_ETH_TREND_COOLDOWN_BARS = 12
V17_ETH_LIQUIDITY_COOLDOWN_BARS = 20
V17_ETH_USE_SEPARATE_TREND_COOLDOWN = True

# --- V18 ETH trend-only: remove liquidity noise, strengthen ETH momentum ---
V18_ETH_TREND_ONLY = True
V18_ETH_TREND_TRADE_TYPE = "eth_trend_momentum"
V18_ETH_TREND_MIN_ADX = 24.0
V18_ETH_TREND_MIN_DRIFT_PCT = 0.0120
V18_ETH_TREND_MAX_DRIFT_PCT = 0.0750
V18_ETH_TREND_BREAKOUT_BUFFER_ATR = 0.06
V18_ETH_TREND_MIN_BODY_ATR = 0.30
V18_ETH_TREND_MIN_RANGE_ATR = 0.55
V18_ETH_TREND_REQUIRE_REGIME_ALIGNMENT = True
V18_ETH_TREND_ALLOW_LONG = True
V18_ETH_TREND_ALLOW_SHORT = True
V18_ETH_TREND_LONG_RISK_MULT = 0.042
V18_ETH_TREND_SHORT_RISK_MULT = 0.024
V18_ETH_TREND_SHORT_MIN_ADX = 30.0
V18_ETH_TREND_SHORT_MIN_DRIFT_PCT = 0.0180
V18_ETH_TREND_SHORT_MIN_BODY_ATR = 0.34
V18_ETH_TREND_COOLDOWN_BARS = 14
V18_ETH_DISABLE_LIQUIDITY_LAYER = True

# ===== v20 ETH exit tuning =====
# Entry logic stays v18-quality. These marker params are for version traceability;
# actual exit overrides are in SYMBOL_PARAM_OVERRIDES["ETHUSDT"] so BTC exits stay untouched.
V20_ETH_EXIT_ENGINE_ENABLED = True
V20_ETH_BASE_VERSION = "v18_eth_trend_only"
V20_ETH_TP1_ATR_MULT_TREND = 5.4
V20_ETH_TP1_CLOSE_FRACTION_TREND = 0.26
V20_ETH_TRAILING_ACTIVATION_ATR_TREND = 4.9
V20_ETH_TRAILING_ATR_MULT_TREND = 3.7
V20_ETH_RUNNER_STALL_BARS_TREND = 10

# ===== v22 ETH exit de-noise =====
# Built on v20/v18-quality entries. BTC remains untouched.
# Goal: reduce negative early_cut_loss / weak_trade_exit without changing entry filters.
V22_ETH_EXIT_DENOISE_ENABLED = True
V22_ETH_BASE_VERSION = "v20_eth_exit_engine"
V22_ETH_TREND_ONLY = True
V22_ETH_EARLY_EXIT_BARS_TREND = 24
V22_ETH_EARLY_EXIT_MIN_PROGRESS_ATR_TREND = 0.05
V22_ETH_EARLY_CUT_LOSS_ATR_TREND = 2.80
V22_ETH_EARLY_CUT_MAX_PROGRESS_ATR_TREND = -0.05
V22_ETH_KEEP_PYRAMID_DISABLED = True

# ===== v23 ETH volatility breakout fallback =====
# Built on v22. ETH trend engine remains primary; this small-risk fallback is used
# when trend-only logic is silent in range/transition/weak-trend conditions.
V23_ETH_VOL_BREAKOUT_ENABLED = False
V23_ETH_VOL_BREAKOUT_TRADE_TYPE = "eth_vol_breakout"
V23_ETH_VOL_BREAKOUT_ALLOWED_MARKET_STATES = ["range", "transition", "flat", "trend"]
V23_ETH_VOL_BREAKOUT_ALLOW_AFTER_TREND_MISS = True
V23_ETH_VOL_BREAKOUT_MIN_RECENT_BARS = 24
V23_ETH_VOL_BREAKOUT_MIN_ADX = 14.0
V23_ETH_VOL_BREAKOUT_MAX_ADX = 42.0
V23_ETH_VOL_BREAKOUT_MAX_DRIFT_PCT = 0.055
V23_ETH_VOL_BREAKOUT_MIN_BODY_ATR = 0.24
V23_ETH_VOL_BREAKOUT_MIN_RANGE_ATR = 0.42
V23_ETH_VOL_BREAKOUT_MIN_BOX_WIDTH_PCT = 0.0045
V23_ETH_VOL_BREAKOUT_MAX_BOX_WIDTH_PCT = 0.085
V23_ETH_VOL_BREAKOUT_BUFFER_ATR = 0.035
V23_ETH_VOL_BREAKOUT_LONG_MIN_CLOSE_POS = 0.62
V23_ETH_VOL_BREAKOUT_SHORT_MAX_CLOSE_POS = 0.38
V23_ETH_VOL_BREAKOUT_REQUIRE_REGIME_ALIGNMENT = False
V23_ETH_VOL_BREAKOUT_ALLOW_LONG = True
V23_ETH_VOL_BREAKOUT_ALLOW_SHORT = True
V23_ETH_VOL_BREAKOUT_SHORT_MIN_ADX = 18.0
V23_ETH_VOL_BREAKOUT_SHORT_MIN_DRIFT_PCT = 0.0060
V23_ETH_VOL_BREAKOUT_LONG_RISK_MULT = 0.020
V23_ETH_VOL_BREAKOUT_SHORT_RISK_MULT = 0.014

# ===== v24 ETH clean breakout trigger =====
# Built on v23 idea, but breakout is no longer a noisy default fallback.
# It is a rare, strict volatility-expansion trigger. BTC remains untouched.
V24_ETH_CLEAN_BREAKOUT_ENABLED = False
V24_ETH_BASE_VERSION = "v22_eth_exit_denoise_plus_v23_breakout_cleanup"
V24_ETH_VOL_BREAKOUT_TRADE_TYPE = "eth_vol_breakout"
V24_ETH_VOL_BREAKOUT_ALLOWED_MARKET_STATES = ["range", "transition", "flat"]
V24_ETH_VOL_BREAKOUT_ALLOW_AFTER_TREND_MISS = False
V24_ETH_VOL_BREAKOUT_MIN_RECENT_BARS = 48
V24_ETH_VOL_BREAKOUT_MIN_ADX = 18.0
V24_ETH_VOL_BREAKOUT_MAX_ADX = 38.0
V24_ETH_VOL_BREAKOUT_MAX_DRIFT_PCT = 0.035
V24_ETH_VOL_BREAKOUT_MIN_BODY_ATR = 0.72
V24_ETH_VOL_BREAKOUT_MIN_RANGE_ATR = 0.95
V24_ETH_VOL_BREAKOUT_MIN_BOX_WIDTH_PCT = 0.0080
V24_ETH_VOL_BREAKOUT_MAX_BOX_WIDTH_PCT = 0.055
V24_ETH_VOL_BREAKOUT_BUFFER_ATR = 0.16
V24_ETH_VOL_BREAKOUT_LONG_MIN_CLOSE_POS = 0.78
V24_ETH_VOL_BREAKOUT_SHORT_MAX_CLOSE_POS = 0.22
V24_ETH_VOL_BREAKOUT_REQUIRE_PREV_INSIDE_BOX = True
V24_ETH_VOL_BREAKOUT_REQUIRE_REGIME_ALIGNMENT = False
V24_ETH_VOL_BREAKOUT_REQUIRE_VOLUME_SPIKE = True
V24_ETH_VOL_BREAKOUT_VOLUME_LOOKBACK = 24
V24_ETH_VOL_BREAKOUT_MIN_VOLUME_RATIO = 1.15
V24_ETH_VOL_BREAKOUT_ALLOW_LONG = True
V24_ETH_VOL_BREAKOUT_ALLOW_SHORT = True
V24_ETH_VOL_BREAKOUT_SHORT_MIN_ADX = 24.0
V24_ETH_VOL_BREAKOUT_SHORT_MIN_DRIFT_PCT = 0.0140
V24_ETH_VOL_BREAKOUT_SHORT_MIN_BODY_ATR = 0.86
V24_ETH_VOL_BREAKOUT_LONG_RISK_MULT = 0.012
V24_ETH_VOL_BREAKOUT_SHORT_RISK_MULT = 0.008

# ===== v25 ETH pre-breakout squeeze trigger =====
# Built on v24/v22. BTC remains untouched.
# Goal: add a real non-trend edge by requiring compression BEFORE the breakout,
# instead of chasing a large candle after the move is already extended.
V25_ETH_PRE_BREAKOUT_ENABLED = False
V25_ETH_BASE_VERSION = "v22_eth_exit_denoise_plus_v25_pre_breakout_squeeze"
V25_ETH_VOL_BREAKOUT_TRADE_TYPE = "eth_pre_breakout"
V25_ETH_VOL_BREAKOUT_ALLOWED_MARKET_STATES = ["range", "transition", "flat"]
V25_ETH_VOL_BREAKOUT_ALLOW_AFTER_TREND_MISS = False
V25_ETH_VOL_BREAKOUT_MIN_RECENT_BARS = 60
V25_ETH_VOL_BREAKOUT_SQUEEZE_LOOKBACK = 18
V25_ETH_VOL_BREAKOUT_COMPRESSION_LOOKBACK = 12
V25_ETH_VOL_BREAKOUT_MAX_COMPRESSION_RATIO = 0.82
V25_ETH_VOL_BREAKOUT_MIN_SQUEEZE_WIDTH_PCT = 0.0035
V25_ETH_VOL_BREAKOUT_MAX_SQUEEZE_WIDTH_PCT = 0.0300
V25_ETH_VOL_BREAKOUT_MIN_ADX = 14.0
V25_ETH_VOL_BREAKOUT_MAX_ADX = 34.0
V25_ETH_VOL_BREAKOUT_MAX_DRIFT_PCT = 0.030
V25_ETH_VOL_BREAKOUT_MIN_BODY_ATR = 0.42
V25_ETH_VOL_BREAKOUT_MIN_RANGE_ATR = 0.58
V25_ETH_VOL_BREAKOUT_MIN_BOX_WIDTH_PCT = 0.0035
V25_ETH_VOL_BREAKOUT_MAX_BOX_WIDTH_PCT = 0.0300
V25_ETH_VOL_BREAKOUT_BUFFER_ATR = 0.045
V25_ETH_VOL_BREAKOUT_MAX_EXTENSION_ATR = 0.62
V25_ETH_VOL_BREAKOUT_LONG_MIN_CLOSE_POS = 0.66
V25_ETH_VOL_BREAKOUT_SHORT_MAX_CLOSE_POS = 0.34
V25_ETH_VOL_BREAKOUT_REQUIRE_PREV_INSIDE_BOX = True
V25_ETH_VOL_BREAKOUT_REQUIRE_REGIME_ALIGNMENT = False
V25_ETH_VOL_BREAKOUT_REQUIRE_VOLUME_SPIKE = True
V25_ETH_VOL_BREAKOUT_VOLUME_LOOKBACK = 24
V25_ETH_VOL_BREAKOUT_MIN_VOLUME_RATIO = 1.05
V25_ETH_VOL_BREAKOUT_ALLOW_LONG = True
V25_ETH_VOL_BREAKOUT_ALLOW_SHORT = True
V25_ETH_VOL_BREAKOUT_SHORT_MIN_ADX = 20.0
V25_ETH_VOL_BREAKOUT_SHORT_MIN_DRIFT_PCT = 0.0100
V25_ETH_VOL_BREAKOUT_SHORT_MIN_BODY_ATR = 0.52
V25_ETH_VOL_BREAKOUT_LONG_RISK_MULT = 0.010
V25_ETH_VOL_BREAKOUT_SHORT_RISK_MULT = 0.006

# ===== v26 ETH liquidity breakout trigger =====
# Built on v25/v22. BTC remains untouched.
# Goal: avoid first-breakout traps by requiring: compression box -> opposite-side sweep/reclaim -> real breakout.
V26_ETH_LIQUIDITY_BREAKOUT_ENABLED = False
V26_ETH_BASE_VERSION = "v22_eth_exit_denoise_plus_v26_liquidity_breakout"
V26_ETH_VOL_BREAKOUT_TRADE_TYPE = "eth_liquidity_breakout"
V26_ETH_VOL_BREAKOUT_ALLOWED_MARKET_STATES = ["range", "transition", "flat"]
V26_ETH_VOL_BREAKOUT_ALLOW_AFTER_TREND_MISS = False
V26_ETH_VOL_BREAKOUT_MIN_RECENT_BARS = 72
V26_ETH_VOL_BREAKOUT_SQUEEZE_LOOKBACK = 20
V26_ETH_VOL_BREAKOUT_COMPRESSION_LOOKBACK = 14
V26_ETH_VOL_BREAKOUT_MAX_COMPRESSION_RATIO = 0.88
V26_ETH_VOL_BREAKOUT_MIN_SQUEEZE_WIDTH_PCT = 0.0035
V26_ETH_VOL_BREAKOUT_MAX_SQUEEZE_WIDTH_PCT = 0.0340
V26_ETH_VOL_BREAKOUT_MIN_ADX = 13.0
V26_ETH_VOL_BREAKOUT_MAX_ADX = 36.0
V26_ETH_VOL_BREAKOUT_MAX_DRIFT_PCT = 0.034
V26_ETH_VOL_BREAKOUT_MIN_BODY_ATR = 0.34
V26_ETH_VOL_BREAKOUT_MIN_RANGE_ATR = 0.50
V26_ETH_VOL_BREAKOUT_MIN_BOX_WIDTH_PCT = 0.0035
V26_ETH_VOL_BREAKOUT_MAX_BOX_WIDTH_PCT = 0.0340
V26_ETH_VOL_BREAKOUT_BUFFER_ATR = 0.035
V26_ETH_VOL_BREAKOUT_MAX_EXTENSION_ATR = 0.54
V26_ETH_VOL_BREAKOUT_LONG_MIN_CLOSE_POS = 0.58
V26_ETH_VOL_BREAKOUT_SHORT_MAX_CLOSE_POS = 0.42
V26_ETH_VOL_BREAKOUT_REQUIRE_PREV_INSIDE_BOX = True
V26_ETH_VOL_BREAKOUT_REQUIRE_REGIME_ALIGNMENT = False
V26_ETH_VOL_BREAKOUT_REQUIRE_VOLUME_SPIKE = True
V26_ETH_VOL_BREAKOUT_VOLUME_LOOKBACK = 24
V26_ETH_VOL_BREAKOUT_MIN_VOLUME_RATIO = 1.02
V26_ETH_VOL_BREAKOUT_ALLOW_LONG = True
V26_ETH_VOL_BREAKOUT_ALLOW_SHORT = True
V26_ETH_VOL_BREAKOUT_SHORT_MIN_ADX = 19.0
V26_ETH_VOL_BREAKOUT_SHORT_MIN_DRIFT_PCT = 0.0080
V26_ETH_VOL_BREAKOUT_SHORT_MIN_BODY_ATR = 0.44
V26_ETH_VOL_BREAKOUT_LONG_RISK_MULT = 0.010
V26_ETH_VOL_BREAKOUT_SHORT_RISK_MULT = 0.006
V26_ETH_LIQUIDITY_SWEEP_LOOKBACK = 10
V26_ETH_LIQUIDITY_SWEEP_MIN_BARS_AGO = 1
V26_ETH_LIQUIDITY_SWEEP_MAX_BARS_AGO = 8
V26_ETH_LIQUIDITY_SWEEP_BUFFER_ATR = 0.035
V26_ETH_LIQUIDITY_REQUIRE_OPPOSITE_SWEEP = True
V26_ETH_LIQUIDITY_REQUIRE_SWEEP_CLOSE_BACK_INSIDE = True
V26_ETH_LIQUIDITY_MAX_POST_SWEEP_RETEST_ATR = 0.18


# ===== v27 Multi-asset trend expansion =====
# Scale the only proven edge: trend/momentum. Do not enable legacy range/MR for alts.
V27_MULTI_ASSET_TREND_ENABLED = False  # v82 BTC-only cleanup
V27_ALT_TREND_SYMBOLS = []  # v82: alt trend disabled
V27_ALT_TREND_TRADE_TYPE = "alt_trend_momentum"
V27_ALT_TREND_ALLOWED_MARKET_STATES = ["trend"]
V27_ALT_TREND_MIN_ADX = 29.0
V27_ALT_TREND_MIN_DRIFT_PCT = 0.0180
V27_ALT_TREND_MAX_DRIFT_PCT = 0.0950
V27_ALT_TREND_BREAKOUT_BUFFER_ATR = 0.075
V27_ALT_TREND_MIN_BODY_ATR = 0.42
V27_ALT_TREND_MIN_RANGE_ATR = 0.72
V27_ALT_TREND_REQUIRE_REGIME_ALIGNMENT = True
V27_ALT_TREND_ALLOW_LONG = True
V27_ALT_TREND_ALLOW_SHORT = True
V27_ALT_TREND_LONG_RISK_MULT = 0.020
V27_ALT_TREND_SHORT_RISK_MULT = 0.012
V27_ALT_TREND_SHORT_MIN_ADX = 34.0
V27_ALT_TREND_SHORT_MIN_DRIFT_PCT = 0.0260
V27_ALT_TREND_SHORT_MIN_BODY_ATR = 0.52
V27_ALT_TREND_COOLDOWN_BARS = 24
V27_DISABLE_ETH_BREAKOUT_LAYERS = True
V27_DISABLE_ALT_LEGACY_NON_TREND = True
V27_MAX_CONCURRENT_ALT_POSITIONS = 1


# === v28 CONTROLLED MICRO RANGE ENGINE ===
# Small-risk activity layer for quiet non-trend markets. This is intentionally separate
# from the old legacy range engine and must not affect BTC trend logic.
# ======================================================
# V39 - BTC pullback scale engine
# ======================================================
# Production goal: stop adding low-edge ETH/ALT/micro/range streams and scale the
# only confirmed edge from v38: BTC pullback. Non-BTC symbols are disabled by
# default for v39 testing/live routing.
V39_BTC_SCALE_ENGINE_ENABLED = True
V39_PRODUCTION_SYMBOLS = ["BTCUSDT"]
V39_DISABLED_SYMBOLS = ["ETHUSDT", "SOLUSDT", "AVAXUSDT", "BNBUSDT"]

# Keep old routing flags hard-disabled. They remain referenced by legacy code via
# getattr defaults, but should not create entries in v39.
V28_MICRO_ENGINE_ENABLED = False
V29_ASSET_SELECTION_ENABLED = False
V30_EXPAND_TREND_ENABLED = False
V31_RESET_STRATEGY_STATE_PER_BACKTEST = True
V31_PORTFOLIO_FIX_ENABLED = True
V32_SMART_ROTATION_ENABLED = False
V32_DISABLED_SYMBOLS = V39_DISABLED_SYMBOLS
V32_FORCE_DISABLE_MICRO_RANGE = True
V32_FORCE_DISABLE_EXPANDED_TREND = True
V36_PULLBACK_ENGINE_ENABLED = False
V37_PULLBACK_ONLY_ENABLED = False
V37_BTC_PULLBACK_ONLY_ENABLED = True
V37_BTC_PULLBACK_ONLY_SYMBOLS = ["BTCUSDT"]
V38_RELAXED_PULLBACK_ENABLED = False
V38_RELAXED_BTC_PULLBACK_ENABLED = True

# BTC pullback frequency/quality. v38 proved relaxed pullback can trade every year,
# but weak exits/early cuts eat too much. v39 keeps the relaxed pullback zone but
# scales only confirmed BTC pullbacks.
V39_BTC_PULLBACK_BASE_RISK_MULT = 1.30
V39_BTC_PULLBACK_STRONG_RISK_MULT = 2.10
V39_BTC_PULLBACK_ELITE_RISK_MULT = 2.70
V39_BTC_PULLBACK_MAX_RISK_MULT = 3.00
V39_BTC_PULLBACK_STRONG_ADX = 26.0
V39_BTC_PULLBACK_ELITE_ADX = 32.0
V39_BTC_PULLBACK_STRONG_PRE_IMPULSE_ATR = 1.40
V39_BTC_PULLBACK_ELITE_PRE_IMPULSE_ATR = 2.20
V39_BTC_PULLBACK_MIN_CLOSE_POS_STRONG = 0.56

# BTC-only pyramid: add only to pullback winners after real progress, not to noise.
BTC_PYRAMIDING_ENABLED = True
BTC_PYRAMID_ALLOWED_TRADE_TYPES = ["pullback"]
BTC_PYRAMID_MAX_ADDS = 2
BTC_PYRAMID_REQUIRE_STRONG_SETUP = False
BTC_PYRAMID_MIN_ADX_H = 23.0
BTC_PYRAMID_MIN_DRIFT = 0.0008
BTC_PYRAMID_MIN_PROGRESS_ATR = 0.75
BTC_PYRAMID_RISK_FRACTION = 0.38
BTC_PYRAMID_ALLOW_AFTER_TP1 = True

# Slightly larger base BTC allocation. Real leverage is still controlled by exchange
# and risk sizing; this only scales the confirmed BTC pullback edge.
BTC_POSITION_RISK_MULTIPLIER = 1.65
PULLBACK_RISK_MULTIPLIER = 1.00

# ======================================================
# V40 - HOLD WINNERS for BTC pullback
# ======================================================
# v39 proved BTC pullback edge, but weak_trade_exit / early_cut_loss removed too
# much open trend value. v40 changes only exit/holding behaviour: keep BTC
# pullback winners alive, use wider trailing, and avoid premature weak exits.
V40_HOLD_WINNERS_ENABLED = False
V40_HOLD_WINNERS_SYMBOLS = ["BTCUSDT"]
V40_HOLD_WINNERS_TRADE_TYPES = ["pullback"]
V40_SKIP_WEAK_EXIT_AFTER_MFE_ATR = 0.55
V40_SKIP_WEAK_EXIT_IF_CURRENT_PROGRESS_ATR = -0.35
V40_SKIP_EARLY_CUT_AFTER_MFE_ATR = 0.85
V40_EARLY_CUT_MIN_ADVERSE_ATR = 2.55
V40_EARLY_CUT_MAX_PROGRESS_ATR = -0.20
V40_DISABLE_TIME_STOP_BEFORE_TP1 = True
V40_MIN_BARS_BEFORE_WEAK_EXIT = 48
V40_MIN_BARS_BEFORE_EARLY_CUT = 10

# BTC pullback exit profile: hold winners longer; close smaller TP1 fraction,
# activate runner via trailing instead of weak/time exits.
POSITION_RUNNER_STALL_BARS_CONTINUATION = 72
POSITION_INITIAL_SL_ATR_MULT_CONTINUATION = 2.35

# ======================================================
# V41 - ASYMMETRIC EXIT for BTC pullback
# ======================================================
# Keep v39/v40 BTC pullback entry + scaling, but restore risk control:
# - winners are still held via trailing/runner
# - losers are cut earlier before they become full stop losses
V41_ASYM_EXIT_ENABLED = False
V41_ASYM_EXIT_SYMBOLS = ["BTCUSDT"]
V41_ASYM_EXIT_TRADE_TYPES = ["pullback"]

# Do not weak-exit real winners; allow weak exit for failed entries.
V41_SKIP_WEAK_EXIT_AFTER_MFE_ATR = 1.20
V41_SKIP_WEAK_EXIT_IF_CURRENT_PROGRESS_ATR = 0.15
V41_MIN_BARS_BEFORE_WEAK_EXIT = 22

# Cut failed pullbacks earlier, but only before TP1 and only when adverse.
V41_SKIP_EARLY_CUT_AFTER_MFE_ATR = 1.60
V41_EARLY_CUT_MIN_ADVERSE_ATR = 1.25
V41_EARLY_CUT_MAX_PROGRESS_ATR = -0.35
V41_DISABLE_TIME_STOP_BEFORE_TP1 = False

# Asymmetric BTC pullback profile: preserve large winners, restore smaller losses.
POSITION_TP1_ATR_MULT_CONTINUATION = 5.80
POSITION_TP1_CLOSE_FRACTION_CONTINUATION = 0.22
POSITION_BE_TRIGGER_ATR_CONTINUATION = 1.30
POSITION_BE_OFFSET_ATR_CONTINUATION = 0.04
POSITION_TRAILING_ACTIVATION_ATR_CONTINUATION = 2.55
POSITION_TRAILING_ATR_MULT_CONTINUATION = 2.35
POSITION_TRAILING_STEP_ATR_CONTINUATION = 0.18
POSITION_TIME_STOP_BEFORE_TP1_BARS_CONTINUATION = 44
POSITION_TIME_STOP_AFTER_TP1_BARS_CONTINUATION = 72

# V42 - SMART EARLY EXIT for BTC pullback
# Goal: keep V39 scaling, but cut only true failed pullbacks early.
V42_SMART_EARLY_EXIT_ENABLED = True
V42_SMART_EARLY_EXIT_SYMBOLS = ["BTCUSDT"]
V42_SMART_EARLY_EXIT_TRADE_TYPES = ["pullback"]

# Weak exit: only for trades that never produced useful MFE/current progress.
V42_SKIP_WEAK_EXIT_AFTER_MFE_ATR = 0.80
V42_SKIP_WEAK_EXIT_IF_CURRENT_PROGRESS_ATR = 0.00
V42_MIN_BARS_BEFORE_WEAK_EXIT = 28
V42_WEAK_EXIT_MIN_PROGRESS_ATR = -0.35

# Early cut: earlier for true losers, but disabled once trade has shown life.
V42_SKIP_EARLY_CUT_AFTER_MFE_ATR = 0.65
V42_SKIP_EARLY_CUT_IF_CURRENT_PROGRESS_ATR = -0.05
V42_EARLY_CUT_MIN_ADVERSE_ATR = 0.85
V42_EARLY_CUT_MAX_PROGRESS_ATR = -0.20
V42_DISABLE_TIME_STOP_BEFORE_TP1 = False

POSITION_EARLY_EXIT_BARS_CONTINUATION = 22
POSITION_EARLY_EXIT_MIN_PROGRESS_ATR_CONTINUATION = -0.45
POSITION_EARLY_CUT_LOSS_ATR_CONTINUATION = 1.25
POSITION_EARLY_CUT_MAX_PROGRESS_ATR_CONTINUATION = -0.35


# ======================================================
# V43 - BTC PULLBACK REGIME FILTER
# ======================================================
# v42 showed BTC pullback edge, but 2025-like regimes create false pullbacks.
# This gate does not change entries/exits/scaling; it only decides whether the
# BTC pullback engine is allowed to create a signal in the current HTF regime.
V43_REGIME_FILTER_ENABLED = True
V43_REGIME_FILTER_SYMBOLS = ["BTCUSDT"]
V43_REGIME_FILTER_TRADE_TYPES = ["pullback"]

# Main quality gate. Keep it strict enough to avoid dead/choppy regimes, but not
# so strict that the system returns to 0 trades.
V43_MIN_HTF_ADX = 20.0
V43_MIN_HTF_ATR_PCT = 0.0018
V43_MIN_DRIFT_PCT = 0.0035
V43_MIN_EMA20_SLOPE_PCT = 0.00055
V43_MIN_EMA50_SLOPE_PCT = 0.00018
V43_REQUIRE_HTF_EMA_ALIGNMENT = True
V43_REQUIRE_CLOSE_ABOVE_HTF_EMA50_LONG = True
V43_BLOCK_TRANSITION_IF_WEAK = True
V43_TRANSITION_MIN_ADX = 24.0
V43_TRANSITION_MIN_DRIFT_PCT = 0.0050

# Add-ons/pyramids should be stricter than the initial pullback.
V43_STRICT_ADDON_FILTER = True
V43_ADDON_MIN_HTF_ADX = 24.0
V43_ADDON_MIN_DRIFT_PCT = 0.0050
V43_ADDON_MIN_EMA20_SLOPE_PCT = 0.00075



# =============================================================
# V52 - BTC CANDLE MICROSTRUCTURE ENGINE
# =============================================================
# OHLCV-only gate for BTC pullback. V51 funding/proxy filtering killed
# good 2023 trades, so V52 does not depend on external liquidity data.
# It scores how clean the candle structure is before/at the pullback.
V52_CANDLE_MICROSTRUCTURE_ENABLED = True
V52_CANDLE_MICROSTRUCTURE_SYMBOLS = ["BTCUSDT"]
V52_CANDLE_MICROSTRUCTURE_TRADE_TYPES = ["pullback"]
V52_MIN_SCORE = 0.52
V52_MIN_CLOSE_POS = 0.42
V52_MAX_UPPER_WICK_ATR = 1.10
V52_MAX_FAILED_BREAKOUTS_12 = 3
V52_MIN_EMA20_HOLD_RATIO_8 = 0.50
V52_MIN_BODY_ATR_CONFIRM = -0.25
V52_MAX_ADVERSE_BODY_ATR = 1.15
V52_REQUIRE_NOT_HEAVY_DISTRIBUTION = True
V52_VOLUME_SPIKE_MAX = 4.20
V52_COMPRESSION_BONUS_ENABLED = True
V52_DEBUG_META = False

# =============================================================
# V53 - BTC LOSS CONTAINMENT ENGINE
# =============================================================
# Keep V52 entry/microstructure intact. This layer only reduces the average
# loss of failed BTC pullbacks by tightening protection after confirmation and
# cutting dead trades before they reach a full large stop.
V53_LOSS_CONTAINMENT_ENABLED = True
V53_LOSS_CONTAINMENT_SYMBOLS = ["BTCUSDT"]
V53_LOSS_CONTAINMENT_TRADE_TYPES = ["pullback"]

# Earlier protection after the trade shows life.
V53_BE_TRIGGER_ATR = 1.05
V53_BE_OFFSET_ATR = 0.10
V53_PROFIT_LOCK_TRIGGER_ATR = 1.65
V53_PROFIT_LOCK_ATR = 0.35

# Tighter runner/trailing for failed continuations, but still wide enough for trend winners.
V53_TRAILING_ACTIVATION_ATR = 2.10
V53_TRAILING_ATR_MULT = 2.15
V53_TRAILING_STEP_ATR = 0.12

# Failed-continuation containment before TP1.
V53_EARLY_CUT_MIN_ADVERSE_ATR = 0.78
V53_EARLY_CUT_MAX_MFE_ATR = 0.55
V53_EARLY_CUT_MAX_PROGRESS_ATR = -0.25
V53_WEAK_EXIT_MIN_BARS = 18
V53_WEAK_EXIT_MAX_MFE_ATR = 0.70
V53_WEAK_EXIT_MIN_PROGRESS_ATR = -0.12
V53_TIME_STOP_BEFORE_TP1_BARS = 34
V53_TIME_STOP_BEFORE_TP1_MAX_MFE_ATR = 0.65
V53_TIME_STOP_BEFORE_TP1_MAX_PROGRESS_ATR = 0.10


# ======================================================
# V60 - BTC SHORT MICROSTRUCTURE ENGINE
# ======================================================
# Adds a real, isolated short engine without enabling legacy BTC shorts.
# BTC_DISABLE_ALL_SHORTS remains True; V60 bypasses that block only for
# V60-approved BTC pullback shorts.
V60_SHORT_ENGINE_ENABLED = True
V60_SHORT_ENGINE_SYMBOLS = ["BTCUSDT"]
V60_SHORT_TRADE_TYPE = "pullback"
V60_SHORT_RISK_MULT = 0.92

# Bearish microstructure gate. Uses OHLCV only.
V60_MIN_SCORE = 0.56
V60_MAX_CLOSE_POS = 0.58          # lower close position is more bearish
V60_MIN_UPPER_WICK_ATR = 0.10     # rejection from above
V60_MAX_LOWER_WICK_ATR = 1.25
V60_MIN_EMA20_REJECT_RATIO_8 = 0.45
V60_MAX_FAILED_RECLAIMS_12 = 3
V60_MIN_BODY_ATR_CONFIRM = -0.35  # allow mild green, prefer red
V60_MIN_EMA20_DOWNSLOPE_8 = -0.0002
V60_REQUIRE_BEAR_EMA_STACK = False
V60_COMPRESSION_BONUS_ENABLED = True
V60_DEBUG_META = False


# ======================================================
# V60.1 - SHORT ENGINE DEBUG / ACTIVATION AUDIT
# ======================================================
# Diagnostic only: does not change signals. Shows where BTC short path is
# blocked: regime, pullback candidate, BTC context, V43, V60 gate, regime gate,
# trend quality, short risk stack, or final execution.
V60_1_SHORT_DEBUG_ENABLED = False
V60_1_SHORT_DEBUG_TOP_REASONS = 12
V60_1_SHORT_DEBUG_PRINT_EACH_REJECT = False

# V60.2 - REAL SHORT ENABLE / LEGACY GATE BYPASS
# Allows only V60-approved BTC pullback shorts to bypass old BTC short blockers.
V60_2_REAL_SHORT_ENABLE = True
V60_2_BYPASS_LEGACY_BTC_SHORT_GATE = True
V60_2_BYPASS_LEGACY_DIRECTIONAL_GATES = True
V60_2_BYPASS_LEGACY_SHORT_RISK_STACK = True

# ============================================================
# V61 - FREQUENCY EXPANSION
# Slightly widens already-working V52/V60 microstructure gates.
# It does NOT add new strategies and does NOT bypass loss containment.
# ============================================================
V61_FREQUENCY_EXPANSION_ENABLED = True
V61_SYMBOLS = ["BTCUSDT"]

# Long pullback acceptance: tiny relaxation only.
V61_LONG_MIN_SCORE = 0.48
V61_LONG_MIN_CLOSE_POS = 0.38
V61_LONG_MAX_UPPER_WICK_ATR = 1.28
V61_LONG_MAX_FAILED_BREAKOUTS_12 = 4
V61_LONG_MIN_EMA20_HOLD_RATIO_8 = 0.45
V61_LONG_MIN_BODY_ATR_CONFIRM = -0.38

# Short pullback acceptance: tiny relaxation only.
V61_SHORT_MIN_SCORE = 0.50
V61_SHORT_MAX_CLOSE_POS = 0.64
V61_SHORT_MIN_UPPER_WICK_ATR = 0.06
V61_SHORT_MAX_LOWER_WICK_ATR = 1.38
V61_SHORT_MIN_EMA20_REJECT_RATIO_8 = 0.38
V61_SHORT_MAX_FAILED_RECLAIMS_12 = 4
V61_SHORT_MIN_BODY_ATR_CONFIRM = -0.18
V61_SHORT_MIN_EMA20_DOWNSLOPE_8 = 0.0004

# Safety caps: avoid turning this into noisy trading.
V61_KEEP_HEAVY_DISTRIBUTION_BLOCK = True
V61_KEEP_REGIME_GATE = True
V61_KEEP_LOSS_CONTAINMENT = True



# ==============================================================================
# V62 - SIGNAL RANKING ENGINE
# ==============================================================================
# V61 expanded the candidate pool, but some added trades diluted PF. V62 keeps
# V61's wider discovery gates, then ranks each already-approved setup by candle
# quality and only lets higher-ranked setups reach execution. This is still
# OHLCV-only and does not change exits/position management.
V62_SIGNAL_RANKING_ENABLED = True
V62_SYMBOLS = ["BTCUSDT"]

# Long ranking: preserve the proven V52 long edge while avoiding weak expanded
# continuation behavior.
V62_LONG_MIN_RANK_SCORE = 0.60
V62_LONG_MIN_SCORE = 0.54
V62_LONG_MIN_CLOSE_POS = 0.42
V62_LONG_MAX_UPPER_WICK_ATR = 1.15
V62_LONG_MAX_FAILED_BREAKOUTS_12 = 3
V62_LONG_MIN_EMA20_HOLD_RATIO_8 = 0.50

# Short ranking: V61 increased short frequency, but quality diluted in 2024.
# Require stronger rejection/reclaim failure profile before execution.
V62_SHORT_MIN_RANK_SCORE = 0.64
V62_SHORT_MIN_SCORE = 0.58
V62_SHORT_MAX_CLOSE_POS = 0.58
V62_SHORT_MIN_UPPER_WICK_ATR = 0.10
V62_SHORT_MIN_EMA20_REJECT_RATIO_8 = 0.45
V62_SHORT_MAX_FAILED_RECLAIMS_12 = 3
V62_SHORT_MAX_EMA20_SLOPE_8 = 0.0000
V62_SHORT_MAX_LOWER_WICK_ATR = 1.25

# Debug metadata only; no noisy per-trade printing.
V62_DEBUG_META = False


# V70 - AGGRESSIVE RISK PROFILE
# Purpose: scale the already-stable BTC pullback long/short core without changing signals.
# This is applied in position_sizing_engine.py, after V25 sizing, so it affects
# real qty/notional in both backtest and live.
V70_AGGRESSIVE_RISK_PROFILE_ENABLED = True
V70_SYMBOLS = ["BTCUSDT"]
V70_TRADE_TYPES = ["pullback"]
V70_APPLY_TO_LONG = True
V70_APPLY_TO_SHORT = True

# Base multiplier for all approved BTC pullback trades.
V70_BASE_RISK_MULT = 1.85

# Optional extra boost for cleaner setups. Kept modest to avoid overfitting.
V70_STRONG_SCORE = 0.72
V70_STRONG_EXTRA_MULT = 1.10
V70_ELITE_SCORE = 0.86
V70_ELITE_EXTRA_MULT = 1.18

# Safety caps. With 5x leverage, tight-stop trades may still be leverage-capped.
V70_MAX_RISK_PER_TRADE = 0.055
V70_MIN_RISK_PER_TRADE = 0.0045
V70_MAX_EFFECTIVE_MULT = 2.35

# Reduce aggression during drawdown.
V70_DD_MILD_PCT = 7.0
V70_DD_MILD_MULT = 0.82
V70_DD_SEVERE_PCT = 11.0
V70_DD_SEVERE_MULT = 0.62

# Do not boost obviously dirty setups even if they passed the signal gate.
V70_MAX_FAILED_BREAKOUTS = 3
V70_MAX_VOL_RATIO = 4.5
V70_MAX_UPPER_WICK_ATR_LONG = 1.35
V70_MAX_LOWER_WICK_ATR_SHORT = 1.35


# V71 - PROJECT CLEANUP / REFACTOR
V71_PROJECT_CLEANUP_ENABLED = True
V71_ACTIVE_CORE = "BTC_V52_V53_V60_V61_V62_V70"


# ===== v72 project deep cleanup =====
# Active core before v80: BTC-only OHLCV microstructure system.
# Legacy non-trend/range/MR/ETH-liquidity engines are disabled from signal flow.
V72_PROJECT_CLEANUP_ENABLED = True
V72_ACTIVE_CORE = "BTC_V52_V53_V60_V61_V62_V70"
V72_ENABLE_LEGACY_NON_TREND_ENGINES = False
V72_ENABLE_LEGACY_ETH_LIQUIDITY_ENGINE = False
V72_ENABLE_LEGACY_BTC_RANGE_ENGINE = False
V72_KEEP_BACKTEST_DIAGNOSTICS = False
V72_BTC_ONLY_UNTIL_V80 = True


# ============================================================
# V82 - BTC-ONLY CLEANUP + QUALITY-WEIGHTED RISK
# ============================================================
# ETH/SOL v80 port was removed from the active path: it added many low-edge
# trades and degraded PF/DD. V82 keeps only the proven BTC continuation core.
V82_BTC_ONLY_CLEANUP_ENABLED = True
V82_DISABLED_ALT_SYMBOLS = ["ETHUSDT", "SOLUSDT", "AVAXUSDT", "BNBUSDT"]

# Risk is now reduced for weaker approved BTC pullbacks instead of applying
# the same aggressive V70 size to every accepted signal. Strong/elite BTC
# signals are left unchanged.
V82_BTC_QUALITY_WEIGHTED_RISK_ENABLED = True
V82_SYMBOLS = ["BTCUSDT"]
V82_TRADE_TYPES = ["pullback"]
V82_LOW_SCORE_CUTOFF = 0.58
V82_LOW_SCORE_RISK_MULT = 0.72
V82_MID_SCORE_CUTOFF = 0.68
V82_MID_SCORE_RISK_MULT = 0.88
V82_CHOPPY_MICRO_RISK_MULT = 0.82
V82_MAX_FAILED_BREAKOUTS_FOR_FULL_RISK = 2
V82_MAX_BAD_WICK_ATR_FOR_FULL_RISK = 1.05


# ============================================================
# V84 - BTC TREND PROFIT MAXIMIZER
# ============================================================
# Keep v82 BTC-only signal/sizing baseline, but let strong BTC continuation
# winners breathe more after the trade has proved itself. This changes only
# exit management for approved BTC pullback trades; entries, filters and
# alt paths are untouched.
V84_TREND_PROFIT_MAXIMIZER_ENABLED = False
V84_SYMBOLS = ["BTCUSDT"]
V84_TRADE_TYPES = ["pullback"]
V84_MIN_SCORE = 0.68
V84_STRONG_SCORE = 0.78
V84_MIN_MFE_ATR = 1.15

# Delay trailing activation slightly for high-quality setups, but only after
# the position has already moved in our favor.
V84_TRAILING_ACTIVATION_BONUS_ATR = 0.35
V84_STRONG_TRAILING_ACTIVATION_BONUS_ATR = 0.65

# Loosen trailing distance on strong winners so continuation moves are not
# clipped by normal volatility noise.
V84_TRAILING_MULT_BONUS = 0.35
V84_STRONG_TRAILING_MULT_BONUS = 0.70
V84_TRAILING_STEP_MULT = 1.15
V84_STRONG_TRAILING_STEP_MULT = 1.35

# Protect proven winners from early/weak exits and runner stall.
V84_SKIP_WEAK_EXIT_AFTER_MFE_ATR = 0.95
V84_SKIP_EARLY_CUT_AFTER_MFE_ATR = 0.75
V84_RUNNER_STALL_BARS_BONUS = 10
V84_STRONG_RUNNER_STALL_BARS_BONUS = 18


# V85 - BTC ADAPTIVE EXIT PERSONALITY
# Uses the stable v82 BTC-only engine as the base and switches exit behavior
# per position. Trend-runner mode keeps the v82 personality; defensive mode
# applies limited v84-like protection only when the signal is weaker/choppier.
V85_ADAPTIVE_EXIT_PERSONALITY_ENABLED = True
V85_SYMBOLS = ["BTCUSDT"]
V85_TRADE_TYPES = ["pullback"]
V85_TREND_SCORE = 0.82
V85_DEFENSIVE_SCORE = 0.72
V85_MIN_MFE_ATR = 1.05

# Trend mode: mostly v82 behavior, with only a small runner allowance.
V85_TREND_TRAILING_ACTIVATION_BONUS_ATR = 0.00
V85_TREND_TRAILING_MULT_BONUS = 0.12
V85_TREND_TRAILING_STEP_MULT = 1.08
V85_TREND_SKIP_WEAK_EXIT_AFTER_MFE_ATR = 0.90
V85_TREND_SKIP_EARLY_CUT_AFTER_MFE_ATR = 0.72
V85_TREND_RUNNER_STALL_BARS_BONUS = 8

# Defensive mode: stabilizer personality for weaker/choppier accepted trades.
V85_DEF_TRAILING_ACTIVATION_BONUS_ATR = 0.22
V85_DEF_TRAILING_MULT_BONUS = 0.30
V85_DEF_TRAILING_STEP_MULT = 1.12
V85_DEF_SKIP_WEAK_EXIT_AFTER_MFE_ATR = 1.15
V85_DEF_SKIP_EARLY_CUT_AFTER_MFE_ATR = 0.88
V85_DEF_RUNNER_STALL_BARS_BONUS = 6

# ===== V89 production hardening: execution protection + timeframe preload audit =====
V89_EXECUTION_PROTECTION_ENABLED = True
V89_EXCHANGE_POSITION_SYNC_ENABLED = True
V89_MIN_ORDER_INTERVAL_SEC = 20.0
V89_MAX_SIGNAL_AGE_SEC = 1200.0
V89_EXCHANGE_POSITION_CACHE_TTL_SEC = 10.0

# Live preload/readiness minimums. Keep these conservative and non-alpha.
V89_MIN_PRELOAD_15M_ROWS = 220
V89_MIN_PRELOAD_1H_ROWS = 80
V89_MIN_READY_15M_ROWS = 200
V89_MIN_READY_1H_ROWS = 50

# Backtest preload validation. These should not affect results when data files are complete.
V89_BACKTEST_MIN_15M_ROWS = 220
V89_BACKTEST_MIN_1H_ROWS = 80

# ===== V89.2 live WebSocket heartbeat / stale candle watchdog =====
V89_2_WS_MONITOR_INTERVAL_SEC = 60.0
V89_2_WS_STALE_15M_SEC = 20 * 60.0
V89_2_WS_STALE_1H_SEC = 75 * 60.0


# ===== V89.3 live WebSocket consumer + REST fallback =====
V89_3_WS_RECEIVE_TIMEOUT_SEC = 90.0
V89_3_REST_KLINE_FALLBACK_ENABLED = True


# ===== V89.4 live WS multiplex parser + active REST poll fallback =====
V89_4_REST_KLINE_POLL_ENABLED = True
V89_4_REST_KLINE_POLL_INTERVAL_SEC = 60.0
