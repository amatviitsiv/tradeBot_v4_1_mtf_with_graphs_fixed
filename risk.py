import config as cfg
from utils import round_down


class RiskManager:
    """Риск-менеджер для фьючерсных позиций.

    Главные задачи:
    * нормировать размер позиции по минимальному notional и шагу количества
    * считать размер позиции исходя из % риска на сделку и дистанции до стопа
    * ограничивать позицию плечом (leverage)
    """

    def __init__(self):
        # Минимальный допустимый номинал ордера (ограничение биржи)
        self.min_notional = float(getattr(cfg, "MIN_NOTIONAL_USDT", 5.0))
        # Шаг количества контрактов
        self.qty_step = float(getattr(cfg, "QTY_STEP", 0.0001))

    # ------------------------------------------------------------------
    def calc_size(self, notional: float, price: float):
        """Рассчитать (notional, qty) по желаемому notional.

        Это универсальный метод-нормализатор.
        - гарантирует min_notional
        - округляет qty по шагу
        - возвращает согласованные notional и qty

        Возвращает (notional, qty). Если размер слишком мал — (0.0, 0.0).
        """
        if price <= 0 or notional <= 0:
            return 0.0, 0.0

        # Минимальный размер по notional
        notional = max(float(notional), self.min_notional)

        qty = notional / price
        qty = round_down(qty, self.qty_step)
        if qty <= 0:
            return 0.0, 0.0

        notional = qty * price
        if notional < self.min_notional:
            return 0.0, 0.0

        return float(notional), float(qty)

    # ------------------------------------------------------------------
    def futures_notional_by_leverage(self, balance_usdt: float, leverage: int) -> float:
        """Максимальный номинал позиции по балансу и плечу.

        Пример: equity=5000, leverage=5 -> max_notional = 25_000.
        """
        if balance_usdt <= 0 or leverage <= 0:
            return 0.0
        return float(balance_usdt) * float(leverage)

    # ------------------------------------------------------------------
    def calc_futures_size_from_risk(
        self,
        equity: float,
        price: float,
        stop_distance_pct: float,
        risk_per_trade: float = None,
        leverage: int = None,
    ):
        """Рассчитать размер фьючерсной позиции из % риска и расстояния до стопа.

        :param equity:       текущая equity (баланс + плавающий PnL)
        :param price:        текущая цена входа
        :param stop_distance_pct: расстояние до стопа в %% от цены (напр. 0.8 означает 0.8%%)
        :param risk_per_trade: доля equity на сделку (по умолчанию cfg.RISK_PER_TRADE)
        :param leverage:     используемое плечо (по умолчанию cfg.FUTURES_LEVERAGE_DEFAULT)

        Возвращает (notional, qty).
        """
        if risk_per_trade is None:
            risk_per_trade = float(getattr(cfg, "RISK_PER_TRADE", 0.01))
        if leverage is None:
            leverage = int(getattr(cfg, "FUTURES_LEVERAGE_DEFAULT", 5))

        if (
            equity <= 0
            or price <= 0
            or stop_distance_pct <= 0
            or risk_per_trade <= 0
            or leverage <= 0
        ):
            return 0.0, 0.0

        # Сколько денег готовы потерять в худшем случае
        risk_amount = equity * risk_per_trade

        # Notional по риску: risk_amount = notional * stop_distance_pct / 100
        notional_by_risk = risk_amount * 100.0 / stop_distance_pct

        # Ограничение по плечу
        max_notional_by_lev = self.futures_notional_by_leverage(equity, leverage)

        desired_notional = min(notional_by_risk, max_notional_by_lev)

        return self.calc_size(desired_notional, price)
