"""WebSocket-менеджер для Binance USDT-M фьючерсов без зависимостей от python-binance WS.

Использует aiohttp и официальный multiplex-endpoint Binance Futures:
    wss://fstream.binance.com/stream?streams=btcusdt@kline_15m/ethusdt@kline_1h/...

Цели:
- один WebSocket на все символы и таймфреймы,
- автоматический reconnect с backoff,
- корректное завершение при остановке бота,
- доставка kline-событий в колбеки LiveRunner.
"""

import asyncio
import os
import json
import logging
from typing import Any, Awaitable, Callable, Dict, List, Optional

import aiohttp

logger = logging.getLogger(__name__)
WS_DEBUG = os.getenv("WS_DEBUG", "0") == "1"

KlineCallback = Callable[[Dict[str, Any]], Awaitable[None]]


class BinanceWSManager:
    """Управление WebSocket-подключением Binance USDT-M (один multiplex-стрим)."""

    BASE_URL = "wss://fstream.binance.com/stream"

    def __init__(
        self,
        client: Any,  # сохраняем сигнатуру, но не используем напрямую
        symbols: List[str],
        on_kline_15m: KlineCallback,
        on_kline_1h: KlineCallback,
        reconnect_delay: float = 3.0,
        max_reconnect_delay: float = 30.0,
    ) -> None:
        self._client = client
        self.symbols = symbols
        self.on_kline_15m = on_kline_15m
        self.on_kline_1h = on_kline_1h
        self.reconnect_delay = reconnect_delay
        self.max_reconnect_delay = max_reconnect_delay

        self._session: Optional[aiohttp.ClientSession] = None
        self._ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self._task: Optional[asyncio.Task] = None
        self._stopped = asyncio.Event()

    # ====== публичные методы ======

    async def start(self) -> None:
        """Запуск менеджера: создаёт задачу чтения multiplex-потока."""
        if self._task is not None:
            return
        self._stopped.clear()
        self._task = asyncio.create_task(self._run_loop(), name="binance-ws-main")

    async def stop(self) -> None:
        """Остановить WS-менеджер и закрыть соединения."""
        self._stopped.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        # закрываем WebSocket и сессию
        if self._ws is not None and not self._ws.closed:
            try:
                await self._ws.close()
            except Exception as e:  # pragma: no cover
                logger.exception("[WS] error on ws.close(): %s", e)
        self._ws = None

        if self._session is not None and not self._session.closed:
            try:
                await self._session.close()
            except Exception as e:  # pragma: no cover
                logger.exception("[WS] error on session.close(): %s", e)
        self._session = None

    # ====== внутренний цикл ======

    async def _run_loop(self) -> None:
        """Основной цикл: подключение, чтение, reconnect при ошибках."""
        delay = self.reconnect_delay
        streams = self._build_streams()
        url = self._build_url(streams)
        logger.info("[WS] multiplex URL: %s", url)

        while not self._stopped.is_set():
            try:
                if self._session is None or self._session.closed:
                    self._session = aiohttp.ClientSession()

                logger.info("[WS] connecting to Binance multiplex streams...")
                async with self._session.ws_connect(url, heartbeat=30) as ws:
                    self._ws = ws
                    logger.info("[WS] connected to Binance streams")
                    delay = self.reconnect_delay  # сброс backoff после успешного подключения

                    async for msg in ws:
                        if self._stopped.is_set():
                            break

                        if msg.type == aiohttp.WSMsgType.TEXT:
                            try:
                                data = json.loads(msg.data)
                            except Exception as e:
                                logger.warning("[WS] failed to parse message: %s", e)
                                continue
                            await self._handle_message(data)
                        elif msg.type == aiohttp.WSMsgType.ERROR:
                            logger.error("[WS] websocket error: %s", ws.exception())
                            break
                        elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.CLOSING):
                            logger.info("[WS] websocket closed by server")
                            break

            except asyncio.CancelledError:
                # нормальное завершение по stop()
                logger.info("[WS] main loop cancelled, shutting down")
                break
            except Exception as e:
                if self._stopped.is_set():
                    break
                logger.exception("[WS] error in main loop: %s", e)

            # если мы здесь — соединение оборвалось, надо переподключиться
            if self._stopped.is_set():
                break

            logger.info("[WS] reconnecting in %.1f seconds...", delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, self.max_reconnect_delay)

        logger.info("[WS] run loop finished")

    # ====== утилиты ======

    def _build_streams(self) -> List[str]:
        streams: List[str] = []
        for sym in self.symbols:
            s = sym.lower()
            streams.append(f"{s}@kline_15m")
            streams.append(f"{s}@kline_1h")
        return streams

    def _build_url(self, streams: List[str]) -> str:
        # пример: wss://fstream.binance.com/stream?streams=btcusdt@kline_15m/ethusdt@kline_1h
        stream_str = "/".join(streams)
        return f"{self.BASE_URL}?streams={stream_str}"

    async def _handle_message(self, payload: Dict[str, Any]) -> None:
        """Обработка входящего сообщения от multiplex-стрима."""
        # формат multiplex:
        # {
        #   "stream": "btcusdt@kline_15m",
        #   "data": { "e": "kline", "E": 123456789, "s": "BTCUSDT", "k": {...} }
        # }
        if WS_DEBUG:
            try:
                logger.debug("[WS][DEBUG] raw msg: %s", payload)
            except Exception:
                pass

        data = payload.get("data")
        if data is None:
            data = payload
        if not isinstance(data, dict):
            return

        # интересуют только kline события (в multiplex может прилететь что-то ещё)
        ev = data.get("e")
        if ev is not None and ev != "kline":
            return

        k = data.get("k")
        if not isinstance(k, dict):
            return

        # В некоторых ответах symbol есть только на верхнем уровне data["s"]
        if "s" not in k and "s" in data:
            k["s"] = data.get("s")

        interval = k.get("i")
        symbol = k.get("s") or data.get("s")

        # Логируем только закрытые свечи — это главный признак, что бот получает данные
        try:
            if k.get("x") and symbol and interval in ("15m", "1h"):
                close_px = k.get("c")
                logger.info("[WS] kline closed %s %s close=%s", symbol, interval, close_px)
        except Exception:
            pass

        if interval == "15m":
            await self._safe_call(self.on_kline_15m, k)
        elif interval == "1h":
            await self._safe_call(self.on_kline_1h, k)

    async def _safe_call(self, cb: KlineCallback, kline: Dict[str, Any]) -> None:
        try:
            await cb(kline)
        except Exception as e:  # pragma: no cover
            logger.exception("[WS] error in kline callback: %s", e)