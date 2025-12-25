"""Адаптер над плагинной системой стратегий.

Раньше здесь была "жёстко захардкоженная" логика EMA+MACD.
Теперь она вынесена в strategies/ema_macd.py, а этот модуль
просто проксирует вызовы, чтобы не ломать существующий код.
"""

from typing import Optional

import pandas as pd

from strategies import get_active_strategy


def signal_from_indicators(df: pd.DataFrame) -> Optional[str]:
    """Вернуть торговый сигнал по DataFrame с индикаторами.

    Совместимо по сигнатуре с прошлой версией:
    - вход: DataFrame c колонками индикаторов
    - выход: "buy" / "sell" / None
    """
    strategy = get_active_strategy()
    return strategy.signal(df)
