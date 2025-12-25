"""Пакет стратегий (v6.0).

В данной версии используется одна основная стратегия:
- MTFBreakoutStrategy (H1 тренд + M15 breakout).

Параметр STRATEGY_NAME в config.py больше не влияет на выбор стратегии,
но оставлен для совместимости (можно использовать как "mtf_breakout" в логах/настройках).
"""

from typing import Optional
import logging

from .base import BaseStrategy
from .mtf_breakout import MTFBreakoutStrategy

logger = logging.getLogger(__name__)

_ACTIVE_STRATEGY: Optional[BaseStrategy] = None


def get_active_strategy() -> BaseStrategy:
    """Вернуть единственную активную стратегию (MTFBreakoutStrategy)."""
    global _ACTIVE_STRATEGY
    if _ACTIVE_STRATEGY is None:
        logger.info("[STRATEGIES] Using single active strategy: MTFBreakoutStrategy (v6.0)")
        _ACTIVE_STRATEGY = MTFBreakoutStrategy()
    return _ACTIVE_STRATEGY
