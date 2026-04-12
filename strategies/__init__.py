"""Strategy registry.

The project currently exposes a single runtime strategy: MTFBreakoutStrategy.
STRATEGY_NAME is still read in a few legacy call sites and logs for backward
compatibility, but strategy selection itself is centralized here.
"""

from typing import Optional
import logging

from .base import BaseStrategy
from .mtf_breakout import MTFBreakoutStrategy

logger = logging.getLogger(__name__)

_ACTIVE_STRATEGY: Optional[BaseStrategy] = None


def get_active_strategy() -> BaseStrategy:
    """Return the singleton active strategy instance."""
    global _ACTIVE_STRATEGY
    if _ACTIVE_STRATEGY is None:
        logger.info("[STRATEGIES] Using active strategy: MTFBreakoutStrategy")
        _ACTIVE_STRATEGY = MTFBreakoutStrategy()
    return _ACTIVE_STRATEGY
