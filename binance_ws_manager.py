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
import time
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
        self._last_msg_ts: float = 0.0
        self._raw_msg_count: int = 0
        self._kline_msg_count: int = 0
        self._closed_kline_msg_count: int = 0
        self._last_raw_log_ts: float = 0.0
        self._last_stream_log_ts: Dict[str, float] = {}
        # Logs non-closed kline updates at most once per stream per N seconds.
        # Set WS_KLINE_UPDATE_LOG_SECONDS=0 to disable.
        try:
            self._update_log_interval_sec = float(os.getenv("WS_KLINE_UPDATE_LOG_SECONDS", "60") or 0)
        except Exception:
            self._update_log_interval_sec = 60.0
        try:
            # If no raw WS frame is received for this long, log it and force a reconnect.
            # Binance kline streams normally send updates frequently, so silence means
            # the consumer is stuck or the connection is half-open.
            self._receive_timeout_sec = float(os.getenv("WS_RECEIVE_TIMEOUT_SECONDS", "90") or 0)
        except Exception:
            self._receive_timeout_sec = 90.0

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

                    while not self._stopped.is_set():
                        try:
                            if self._receive_timeout_sec and self._receive_timeout_sec > 0:
                                msg = await ws.receive(timeout=self._receive_timeout_sec)
                            else:
                                msg = await ws.receive()
                        except asyncio.TimeoutError:
                            logger.warning(
                                "[WS] receive timeout: no raw frames for %.1fs, forcing reconnect",
                                self._receive_timeout_sec,
                            )
                            break

                        if msg.type == aiohttp.WSMsgType.TEXT:
                            try:
                                data = json.loads(msg.data)
                            except Exception as e:
                                logger.warning("[WS] failed to parse message: %s", e)
                                continue
                            await self._handle_message(data)
                        elif msg.type == aiohttp.WSMsgType.BINARY:
                            try:
                                data = json.loads(msg.data.decode("utf-8"))
                            except Exception as e:
                                logger.warning("[WS] failed to parse binary message: %s", e)
                                continue
                            await self._handle_message(data)
                        elif msg.type == aiohttp.WSMsgType.ERROR:
                            logger.error("[WS] websocket error: %s", ws.exception())
                            break
                        elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.CLOSING, aiohttp.WSMsgType.CLOSE):
                            logger.info("[WS] websocket closed by server")
                            break
                        elif msg.type in (aiohttp.WSMsgType.PING, aiohttp.WSMsgType.PONG):
                            continue
                        else:
                            logger.debug("[WS] ignored message type: %s", msg.type)

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

    def _normalize_kline_payload(self, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Return Binance kline dict from either raw or multiplex payload.

        Binance multiplex frames look like:
            {"stream": "btcusdt@kline_15m", "data": {"e": "kline", "k": {...}}}
        Raw stream frames look like:
            {"e": "kline", "k": {...}}
        This helper also tolerates a direct kline dict during tests/fallback.
        """
        if not isinstance(payload, dict):
            return None

        data = payload.get("data")
        if data is None:
            data = payload
        if not isinstance(data, dict):
            return None

        ev = data.get("e")
        if ev is not None and ev != "kline":
            return None

        k = data.get("k")
        if not isinstance(k, dict):
            # Some internal tests/fallbacks may pass the kline dict directly.
            if {"t", "i", "s"}.issubset(set(data.keys())):
                k = data
            else:
                return None

        if "s" not in k and "s" in data:
            k["s"] = data.get("s")
        return k

    async def _handle_message(self, payload: Dict[str, Any]) -> None:
        """Обработка входящего сообщения от multiplex/raw kline stream."""
        now = time.time()
        self._last_msg_ts = now
        self._raw_msg_count += 1
        if WS_DEBUG:
            try:
                logger.debug("[WS][DEBUG] raw msg: %s", payload)
            except Exception:
                pass
        if now - self._last_raw_log_ts >= 60.0:
            self._last_raw_log_ts = now
            logger.info("[WS] raw frames received=%s kline=%s closed=%s", self._raw_msg_count, self._kline_msg_count, self._closed_kline_msg_count)

        k = self._normalize_kline_payload(payload)
        if not isinstance(k, dict):
            return
        self._kline_msg_count += 1

        interval = k.get("i")
        symbol = k.get("s")

        # Production visibility: log closed candles always, and non-closed updates
        # periodically so a silent callback/closed-candle issue is visible in live logs.
        try:
            self._last_msg_ts = time.time()
            if symbol and interval in ("15m", "1h"):
                close_px = k.get("c")
                is_closed = bool(k.get("x"))
                if is_closed:
                    self._closed_kline_msg_count += 1
                    logger.info(
                        "[WS] kline CLOSED %s %s open_time=%s close=%s",
                        symbol, interval, k.get("t"), close_px,
                    )
                elif self._update_log_interval_sec > 0:
                    stream_key = f"{symbol}:{interval}"
                    now = time.time()
                    last = self._last_stream_log_ts.get(stream_key, 0.0)
                    if now - last >= self._update_log_interval_sec:
                        self._last_stream_log_ts[stream_key] = now
                        logger.info(
                            "[WS] kline update %s %s closed=false open_time=%s close=%s",
                            symbol, interval, k.get("t"), close_px,
                        )
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