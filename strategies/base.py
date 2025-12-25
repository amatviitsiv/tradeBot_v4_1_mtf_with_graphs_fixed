import abc
from typing import Optional
import pandas as pd


class BaseStrategy(abc.ABC):
    """Базовый класс стратегии.

    Любая стратегия должна реализовывать метод ``signal``,
    который возвращает:
    - "buy"  -> сигнал на открытие/реверс LONG по фьючерсам
    - "sell" -> сигнал на открытие/реверс SHORT по фьючерсам
    - None   -> нет действия
    """

    name: str = "base"

    @abc.abstractmethod
    def signal(self, df: pd.DataFrame) -> Optional[str]:
        """Вернуть торговый сигнал по последним данным df."""
        raise NotImplementedError
