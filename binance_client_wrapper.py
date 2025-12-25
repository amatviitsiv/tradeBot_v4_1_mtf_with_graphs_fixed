"""Обёртка над python-binance с retry/backoff для REST-запросов.

Этот модуль НЕ тянет за собой никакой конкретной логики стратегии — только
надёжный вызов методов клиента Binance.
"""

import asyncio
import logging
import random
from typing import Any, Callable, TypeVar, Awaitable, Optional

try:
    from binance.exceptions import BinanceAPIException, BinanceRequestException
except Exception:  # pragma: no cover - на этапе бэктеста библиотека может быть не установлена
    BinanceAPIException = Exception  # type: ignore
    BinanceRequestException = Exception  # type: ignore

logger = logging.getLogger(__name__)

T = TypeVar("T")


class BinanceClientWrapper:
    """Асинхронная обёртка над синхронным python-binance-клиентом.

    Используется простой экспоненциальный backoff и разделение "временных" и
    "фатальных" ошибок.
    """

    def __init__(
        self,
        client: Any,
        max_retries: int = 5,
        base_delay: float = 1.0,
        max_delay: float = 10.0,
    ) -> None:
        self.client = client
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay

    async def call(self, func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """Вызывает метод клиента с retry/backoff.

        func — это обычно client.futures_... или client.get_...
        """
        attempt = 0
        while True:
            attempt += 1
            try:
                return func(*args, **kwargs)
            except (BinanceRequestException, BinanceAPIException) as e:  # type: ignore[misc]
                if attempt > self.max_retries:
                    logger.exception("[BINANCE] giving up after %s attempts: %s", attempt - 1, e)
                    raise

                delay = min(self.base_delay * 2 ** (attempt - 1), self.max_delay)
                jitter = delay * 0.1 * random.random()
                sleep_for = delay + jitter
                logger.warning(
                    "[BINANCE] error on attempt %s/%s: %s — retrying in %.2fs",
                    attempt,
                    self.max_retries,
                    e,
                    sleep_for,
                )
                await asyncio.sleep(sleep_for)
            except Exception as e:  # неизвестная ошибка — пробрасываем сразу
                logger.exception("[BINANCE] unexpected error: %s", e)
                raise
