import json
import os
import logging
from typing import Dict, Optional, Any

from position import PositionState
import config

logger = logging.getLogger(__name__)


class StateManager:
    """Работа с файлом состояния бота.

    Формат файла JSON (пример):

    {
        "version": 1,
        "positions": {
            "BTCUSDT": { ... PositionState.as_dict() ... }
        },
        "balances": {
            "USDT": {
                "free": 123.45,
                "equity": 130.0,
                "update_time": 1712345678.0
            }
        },
        "equity_peak": 150.0,
        "realized_pnl": 12.34,
        "strategy_version": "mtf_breakout_prod_prep_1"
    }

    Старые файлы, где есть только блок positions, также корректно читаются.
    """  # noqa: E501

    def __init__(self, state_file: Optional[str] = None):
        self.state_file = state_file or getattr(config, "STATE_FILE", "bot_state.json")
        self.data: Dict[str, Any] = {
            "version": 1,
            "positions": {},
            "balances": {},
            "equity_peak": None,
            "realized_pnl": 0.0,
            "strategy_version": getattr(config, "STRATEGY_VERSION", "")
        }

    # ===== Базовые операции с файлом =====

    def load(self) -> None:
        """Загружает состояние с диска, если файл существует."""
        if not os.path.exists(self.state_file):
            logger.info("[STATE] no state file (%s) — starting fresh", self.state_file)
            return
        try:
            with open(self.state_file, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                # Мягко обновляем текущий словарь, не теряя новых полей по умолчанию
                self.data.update(raw)
            logger.info("[STATE] loaded state from %s", self.state_file)
        except Exception as e:
            logger.exception("[STATE] failed to load state %s: %s", self.state_file, e)

    def _atomic_write(self, payload: Dict[str, Any]) -> None:
        """Атомарная запись состояния.

        Пишем во временный файл и затем делаем os.replace.
        Это защищает от порчи файла при падении процесса.
        """
        tmp_path = f"{self.state_file}.tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self.state_file)
        except Exception as e:
            logger.exception("[STATE] failed to save state %s: %s", self.state_file, e)

    def save(self) -> None:
        """Сохраняет текущее состояние на диск."""
        self._atomic_write(self.data)
        logger.debug("[STATE] saved state to %s", self.state_file)

    # ===== Позиции =====

    def get_positions(self) -> Dict[str, PositionState]:
        """Возвращает словарь symbol -> PositionState."""
        positions = self.data.get("positions") or {}
        out: Dict[str, PositionState] = {}
        for sym, p in positions.items():
            try:
                out[sym] = PositionState.from_dict(p)
            except Exception as e:
                logger.error("[STATE] bad position for %s: %s", sym, e)
        return out

    def set_position(self, symbol: str, pos: PositionState) -> None:
        """Сохраняет/обновляет позицию по символу."""
        self.data.setdefault("positions", {})
        self.data["positions"][symbol] = pos.to_dict()
        self.save()

    def del_position(self, symbol: str) -> None:
        """Удаляет позицию по символу, если она есть."""
        if symbol in self.data.get("positions", {}):
            del self.data["positions"][symbol]
            self.save()

    # ===== Балансы и PnL =====

    def update_balance(self, asset: str, free: float, equity: Optional[float] = None, ts: Optional[float] = None) -> None:  # noqa: E501
        """Обновляет информацию о балансе одного актива (обычно USDT)."""
        self.data.setdefault("balances", {})
        self.data["balances"][asset] = {
            "free": float(free),
            "equity": float(equity) if equity is not None else None,
            "update_time": float(ts) if ts is not None else None,
        }
        self.save()

    def get_balance(self, asset: str = "USDT") -> Optional[Dict[str, float]]:
        """Возвращает словарь с данными по активу или None, если его нет."""
        balances = self.data.get("balances") or {}
        return balances.get(asset)

    def update_equity_peak(self, equity: float) -> None:
        """Обновить пик эквити (используется для расчёта текущей DD)."""
        cur_peak = self.data.get("equity_peak")
        if cur_peak is None or equity > cur_peak:
            self.data["equity_peak"] = float(equity)
            self.save()

    def add_realized_pnl(self, pnl_delta: float) -> None:
        """Увеличить накопленный реализованный PnL."""
        try:
            cur = float(self.data.get("realized_pnl", 0.0))
        except (TypeError, ValueError):
            cur = 0.0
        self.data["realized_pnl"] = cur + float(pnl_delta)
        self.save()
