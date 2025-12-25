"""Абстрактные интерфейсы брокеров.

В актуальной версии проекта торгуем ТОЛЬКО фьючерсами USDT-M.
Этот модуль описывает минимальный контракт фьючерсного брокера.
"""

from abc import ABC, abstractmethod
from typing import Dict

from position import PositionState


class AbstractFuturesBroker(ABC):
    """Минимальный интерфейс фьючерсного брокера."""

    @abstractmethod
    async def init(self) -> None:
        ...

    @abstractmethod
    async def set_leverage(self, symbol: str, leverage: int):
        ...

    @abstractmethod
    async def create_market_order(
        self,
        symbol: str,
        side: str,
        qty: float,
        price: float,
        reduce_only: bool = False,
    ):
        ...

    @abstractmethod
    async def get_open_positions(self) -> Dict[str, PositionState]:
        ...

    @abstractmethod
    async def update_balance(self) -> Dict[str, float]:
        ...
