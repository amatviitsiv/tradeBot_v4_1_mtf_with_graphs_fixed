"""Простой Telegram-notifier для бота.

Все настройки берутся из config.py:
- TELEGRAM_ENABLED
- TELEGRAM_BOT_TOKEN
- TELEGRAM_CHAT_ID

Если TELEGRAM_ENABLED = False или не заданы токен/чат, методы молча пишут в лог.
"""

import logging
import json
import urllib.parse
import urllib.request
from typing import Optional

import config

logger = logging.getLogger(__name__)


class TelegramNotifier:
    """Синхронный Telegram-notifier.

    Использует обычный HTTP-запрос к Telegram Bot API.
    В продакшене этого более чем достаточно, т.к. объём уведомлений небольшой.
    """

    def __init__(self) -> None:
        self.enabled: bool = bool(getattr(config, "TELEGRAM_ENABLED", False))
        self.token: Optional[str] = getattr(config, "TELEGRAM_BOT_TOKEN", None)
        self.chat_id: Optional[str] = getattr(config, "TELEGRAM_CHAT_ID", None)

        if not self.enabled:
            logger.info("[TG] telegram notifications disabled via TELEGRAM_ENABLED")
        elif not self.token or not self.chat_id:
            logger.warning("[TG] TELEGRAM_ENABLED=True, но не задан токен или chat_id")

    # ====== низкоуровневый отправитель ======

    def _send_raw(self, text: str) -> None:
        """Отправить сырое Markdown-сообщение в Telegram.

        Безопасен: при любой ошибке просто пишет в лог и не падает.
        """
        if not self.enabled:
            logger.debug("[TG] disabled, skip message: %s", text)
            return
        if not self.token or not self.chat_id:
            logger.debug("[TG] token/chat_id not set, skip message: %s", text)
            return

        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
        )

        try:
            with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
                if resp.status != 200:
                    logger.warning("[TG] non-200 response: %s", resp.status)
        except Exception as e:  # pragma: no cover
            logger.exception("[TG] failed to send telegram message: %s", e)

    # ====== базовые уведомления, которые уже использовались ранее ======

    def notify_text(self, text: str) -> None:
        """Отправить произвольный текст как есть."""
        self._send_raw(text)

    def notify_balance(self, equity: float, dd_pct: Optional[float] = None) -> None:
        if dd_pct is None:
            msg = f"*BALANCE* equity: `{equity}`"
        else:
            msg = f"*BALANCE* equity: `{equity}`, DD: `{dd_pct:.2f}%`"
        self._send_raw(msg)

    def notify_error(self, context: str, error: str) -> None:
        msg = f"*ERROR* {context}\n`{error}`"
        self._send_raw(msg)

    def notify_heartbeat(self, equity: float, open_positions_count: int) -> None:
        msg = f"*HEARTBEAT* equity: `{equity}`, open positions: `{open_positions_count}`"
        self._send_raw(msg)

    # ====== новые уведомления о сделках ======

    def notify_open_position(
        self,
        symbol: str,
        side: str,
        qty: float,
        entry_price: float,
        leverage: Optional[float] = None,
        time_str: Optional[str] = None,
    ) -> None:
        """Уведомление об открытии позиции (после исполнения ордера)."""
        side_up = side.upper()
        msg_lines = [
            "*POSITION OPENED*",
            f"Symbol: `{symbol}`",
            f"Side: *{side_up}*",
            f"Qty: `{qty}`",
            f"Entry: `{entry_price}`",
        ]
        if leverage is not None and leverage > 0:
            msg_lines.append(f"Leverage: `{leverage}x`")
        if time_str is not None:
            msg_lines.append(f"Time: `{time_str}`")
        msg = "\n".join(msg_lines)
        self._send_raw(msg)

    def notify_close_position(
        self,
        symbol: str,
        side: str,
        qty: float,
        entry_price: float,
        exit_price: float,
        pnl: float,
        roe_pct: Optional[float] = None,
        duration_str: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> None:
        """Уведомление о закрытии позиции."""
        side_up = side.upper()
        pnl_str = f"{pnl:.4f}"
        sign = "+" if pnl >= 0 else ""
        msg_lines = [
            "*POSITION CLOSED*",
            f"Symbol: `{symbol}`",
            f"Side: *{side_up}*",
            f"Qty: `{qty}`",
            f"Entry: `{entry_price}`",
            f"Exit: `{exit_price}`",
            f"PnL: `{sign}{pnl_str}`",
        ]
        if roe_pct is not None:
            msg_lines.append(f"ROE: `{roe_pct:+.2f}%`")
        if duration_str is not None:
            msg_lines.append(f"Duration: `{duration_str}`")
        if reason:
            msg_lines.append(f"Reason: `{reason}`")
        msg = "\n".join(msg_lines)
        self._send_raw(msg)

    def notify_order_error(self, symbol: str, side: str, qty: float, error: str) -> None:
        """Уведомление об ошибке при создании ордера."""
        side_up = side.upper()
        msg = (
            "*ORDER ERROR*\n"
            f"Symbol: `{symbol}`\n"
            f"Side: `{side_up}`\n"
            f"Qty: `{qty}`\n"
            f"Error: `{error}`"
        )
        self._send_raw(msg)

    def notify_bot_stopped(self, open_positions: int) -> None:
        """Уведомление о корректной остановке бота."""
        msg = (
            "*BOT STOPPED*\n"
            f"Open positions at shutdown: `{open_positions}`"
        )
        self._send_raw(msg)
