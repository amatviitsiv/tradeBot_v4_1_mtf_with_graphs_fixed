"""Compatibility adapter over the strategy registry.

Legacy call sites still import signal_from_indicators(...). The actual strategy
instance is resolved by strategies.get_active_strategy().
"""

from typing import Optional

import pandas as pd

from strategies import get_active_strategy


def signal_from_indicators(df: pd.DataFrame) -> Optional[str]:
    """Return a trading signal using the currently active strategy."""
    return get_active_strategy().signal(df)
