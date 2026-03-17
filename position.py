import time
from dataclasses import dataclass, asdict
from typing import Optional


@dataclass
class PositionState:
    """Состояние фьючерсной позиции.

    В актуальной версии используем только фьючерсы USDT-M.
    Поле ``mode`` оставлено для совместимости со старыми состояниями, но
    в новом коде всегда должно быть "futures".

    Дополнительно поле ``side``:
    - "long"  — лонг фьючерса
    - "short" — шорт фьючерса
    """

    symbol: str
    entry_price: float
    qty: float
    notional: float

    side: str = "short"
    mode: str = "futures"
    open_time: float = None

    # Уровни управления риском
    stop_loss: Optional[float] = None
    tp1: Optional[float] = None
    tp2: Optional[float] = None

    peak_price: Optional[float] = None
    trailing_stop: Optional[float] = None
    be_moved: bool = False
    tp1_hit: bool = False
    trail_active: bool = False

    pyramid_level: int = 0
    trade_type: str = "unknown"
    market_state: str = "unknown"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "PositionState":
        """Восстановление из словаря, совместимое со старыми версиями состояния."""
        return cls(
            symbol=d["symbol"],
            entry_price=float(d["entry_price"]),
            qty=float(d["qty"]),
            notional=float(d.get("notional", float(d["entry_price"]) * float(d["qty"]))),
            side=d.get("side", "short"),
            mode=d.get("mode", "futures"),
            open_time=d.get("open_time", time.time()),
            stop_loss=d.get("stop_loss"),
            tp1=d.get("tp1"),
            tp2=d.get("tp2"),
            peak_price=d.get("peak_price"),
            trailing_stop=d.get("trailing_stop"),
            be_moved=bool(d.get("be_moved", False)),
            tp1_hit=bool(d.get("tp1_hit", False)),
            trail_active=bool(d.get("trail_active", False)),
            pyramid_level=int(d.get("pyramid_level", 0)),
            trade_type=d.get("trade_type", "unknown"),
            market_state=d.get("market_state", "unknown"),
        )
