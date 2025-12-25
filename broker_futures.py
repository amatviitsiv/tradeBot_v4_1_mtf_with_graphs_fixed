"""Реализация брокера для Binance USDT-M фьючерсов на базе python-binance AsyncClient.

Использует python-binance (AsyncClient).
Цели:
- единая точка работы с REST-фьючерсами (USDT-M),
- централизованный retry/backoff,
- проверка и нормализация количества (LOT_SIZE),
- аккуратное логирование и закрытие соединения.
"""

import asyncio
import logging
import random
from typing import Any, Dict, List, Optional

from binance import AsyncClient  # type: ignore

import config

logger = logging.getLogger(__name__)


class LiveFuturesBroker:
    """Брокер для Binance USDT-M фьючерсов на базе AsyncClient (python-binance).

    Предполагается:
    - режим USDT-M futures,
    - рыночные ордера (MARKET),
    - работа в cross-margin (или заранее настроенной марже).
    """

    def __init__(
        self,
        client: AsyncClient,
        max_retries: int = 5,
        base_delay: float = 1.0,
        max_delay: float = 8.0,
    ) -> None:
        self.client = client
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self._symbols_info: Dict[str, Dict[str, Any]] = {}

    # ====== фабричный метод ======

    @classmethod
    async def create(
        cls,
        api_key: str,
        api_secret: str,
        **kwargs: Any,
    ) -> "LiveFuturesBroker":
        """Создать AsyncClient, обернуть его в брокер и инициализировать биржевую информацию."""
        client = await AsyncClient.create(api_key, api_secret)
        broker = cls(client, **kwargs)
        await broker.init()
        return broker

    async def close(self) -> None:
        """Корректно закрыть соединение с Binance."""
        try:
            await self.client.close_connection()
        except Exception as e:  # pragma: no cover
            logger.exception("[FUTURES] error on closing client: %s", e)

    # ====== базовый вызов с retry/backoff ======

    async def _call(self, op_name: str, func, *args: Any, **kwargs: Any) -> Any:
        """Обёртка над вызовами AsyncClient с экспоненциальным backoff."""
        attempt = 0
        while True:
            attempt += 1
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                if attempt >= self.max_retries:
                    logger.exception(
                        "[FUTURES] %s failed after %s attempts: %s",
                        op_name,
                        attempt,
                        e,
                    )
                    raise
                delay = min(self.base_delay * (2 ** (attempt - 1)), self.max_delay)
                jitter = delay * 0.2 * random.random()
                sleep_for = delay + jitter
                logger.warning(
                    "[FUTURES] %s error on attempt %s/%s: %s — retry in %.2fs",
                    op_name,
                    attempt,
                    self.max_retries,
                    e,
                    sleep_for,
                )
                await asyncio.sleep(sleep_for)

    # ====== инициализация и справочная информация ======

    async def init(self) -> None:
        """Загрузить exchangeInfo и кешировать параметры символов."""
        logger.info("[FUTURES] loading futures_exchange_info (python-binance)...")
        info = await self._call("futures_exchange_info", self.client.futures_exchange_info)
        symbols = info.get("symbols", [])
        for s in symbols:
            if s.get("contractType") != "PERPETUAL":
                continue
            symbol = s["symbol"]
            filters = {f["filterType"]: f for f in s.get("filters", [])}
            lot = filters.get("LOT_SIZE", {})
            min_qty = float(lot.get("minQty", 0.0))
            step_size = float(lot.get("stepSize", 0.0))
            min_notional = 0.0
            min_notional_filter = filters.get("MIN_NOTIONAL")
            if min_notional_filter is not None:
                try:
                    min_notional = float(min_notional_filter.get("notional", 0.0))
                except Exception:
                    min_notional = 0.0
            self._symbols_info[symbol] = {
                "min_qty": min_qty,
                "step_size": step_size,
                "min_notional": min_notional,
            }
        logger.info("[FUTURES] exchangeInfo loaded for %s symbols", len(self._symbols_info))

    # ====== вспомогательные методы ======

    def _adjust_qty(self, symbol: str, qty: float) -> float:
        """Привести количество к шагу биржи (LOT_SIZE.stepSize), округляя вниз."""
        info = self._symbols_info.get(symbol)
        if not info:
            return qty
        step = info.get("step_size") or 0.0
        if step <= 0:
            return qty
        steps = int(qty / step)
        return steps * step

    # ====== баланс и позиции ======

    async def get_balance_usdt(self) -> float:
        """Получить equity/баланс USDT по фьючерсному счёту."""
        acc = await self._call("futures_account", self.client.futures_account)
        balances = acc.get("assets", [])
        for b in balances:
            if b.get("asset") == "USDT":
                for key in ("walletBalance", "availableBalance", "marginBalance"):
                    if key in b:
                        try:
                            return float(b[key])
                        except Exception:
                            continue
        return 0.0

    async def get_positions(self) -> List[Dict[str, Any]]:
        """Список открытых позиций по всем символам (ненулевой positionAmt)."""
        acc = await self._call("futures_account", self.client.futures_account)
        positions = acc.get("positions", [])
        out: List[Dict[str, Any]] = []
        for p in positions:
            try:
                qty = float(p.get("positionAmt", 0.0))
            except Exception:
                qty = 0.0
            if qty == 0.0:
                continue
            out.append(p)
        return out

    async def get_mark_price(self, symbol: str) -> Optional[float]:
        """Текущая markPrice по символу."""
        try:
            data = await self._call(
                "futures_mark_price",
                self.client.futures_mark_price,
                symbol=symbol,
            )
            if isinstance(data, list):
                data = data[0] if data else {}
            return float(data.get("markPrice", 0.0))
        except Exception as e:
            logger.error("[FUTURES] failed to get mark price for %s: %s", symbol, e)
            return None

    # ====== плечо ======

    async def set_leverage(self, symbol: str, leverage: int) -> None:
        """Установить плечо для символа."""
        try:
            await self._call(
                "futures_change_leverage",
                self.client.futures_change_leverage,
                symbol=symbol,
                leverage=leverage,
            )
            logger.info("[FUTURES] set leverage %s = %dx", symbol, leverage)
        except Exception as e:
            logger.error("[FUTURES] failed to set leverage for %s: %s", symbol, e)

    # ====== ордера ======

    async def create_market_order(
        self,
        symbol: str,
        side: str,
        qty: float,
        reduce_only: bool = False,
        position_side: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Создать рыночный ордер.

        side: "BUY" / "SELL"
        reduce_only: True для закрытия позиции
        position_side: "LONG" / "SHORT" (если включён dual-side режим)
        """
        if qty <= 0:
            raise ValueError("qty must be > 0")

        adj_qty = self._adjust_qty(symbol, qty)
        if adj_qty <= 0:
            raise ValueError(f"adjusted qty for {symbol} is zero (raw={qty})")

        params: Dict[str, Any] = {
            "symbol": symbol,
            "side": side.upper(),
            "type": "MARKET",
            "quantity": adj_qty,
        }
        if reduce_only:
            params["reduceOnly"] = True
        if position_side:
            params["positionSide"] = position_side.upper()

        logger.info("[FUTURES] creating MARKET order: %s", params)
        res = await self._call(
            "futures_create_order",
            self.client.futures_create_order,
            **params,
        )
        logger.info("[FUTURES] order result: %s", res)
        return res
