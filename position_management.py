import config as cfg


def _cfg_float(name: str, default: float, symbol: str = "") -> float:
    try:
        return float(cfg.get_symbol_param(symbol, name, getattr(cfg, name, default)))
    except Exception:
        return float(default)


def _cfg_int(name: str, default: int) -> int:
    try:
        return int(getattr(cfg, name, default))
    except Exception:
        return int(default)


def calc_tp1_price(entry_price: float, atr: float, side: str, symbol: str = "") -> float:
    tp1_mult = _cfg_float("POSITION_TP1_ATR_MULT", _cfg_float("ATR_TP_MULT_1", 8.0, symbol), symbol)
    if side == "long":
        return entry_price + tp1_mult * atr
    return entry_price - tp1_mult * atr


def update_peak_price(pos, price: float) -> None:
    peak = getattr(pos, "peak_price", None)
    if peak is None:
        pos.peak_price = float(price)
        return
    if pos.side == "long":
        pos.peak_price = max(float(peak), float(price))
    else:
        pos.peak_price = min(float(peak), float(price))


def maybe_move_to_break_even(pos, price: float, atr: float) -> bool:
    if atr <= 0:
        return False
    symbol = getattr(pos, "symbol", "")
    if bool(getattr(cfg, "POSITION_BE_ONLY_AFTER_TP1", False)) or bool(_cfg_float("POSITION_BE_ONLY_AFTER_TP1", 0.0, symbol)):
        if not getattr(pos, "tp1_hit", False):
            return False
    trigger_atr = _cfg_float("POSITION_BE_TRIGGER_ATR", 0.0, symbol)
    if trigger_atr <= 0:
        return False
    be_offset_atr = _cfg_float("POSITION_BE_OFFSET_ATR", 0.0, symbol)
    moved = getattr(pos, "be_moved", False)
    if pos.side == "long":
        move_atr = (price - pos.entry_price) / atr
        if move_atr < trigger_atr:
            return False
        be_stop = pos.entry_price + be_offset_atr * atr
        if moved and pos.stop_loss is not None and pos.stop_loss >= be_stop:
            return False
        if pos.stop_loss is None or be_stop > pos.stop_loss:
            pos.stop_loss = be_stop
            pos.be_moved = True
            return True
    else:
        move_atr = (pos.entry_price - price) / atr
        if move_atr < trigger_atr:
            return False
        be_stop = pos.entry_price - be_offset_atr * atr
        if moved and pos.stop_loss is not None and pos.stop_loss <= be_stop:
            return False
        if pos.stop_loss is None or be_stop < pos.stop_loss:
            pos.stop_loss = be_stop
            pos.be_moved = True
            return True
    return False


def should_take_tp1(pos, price: float) -> bool:
    return pos.tp1 is not None and ((pos.side == "long" and price >= pos.tp1) or (pos.side == "short" and price <= pos.tp1))


def on_tp1_hit(pos, price: float, atr: float) -> None:
    if atr <= 0:
        atr = 0.0
    symbol = getattr(pos, "symbol", "")
    be_offset_atr = _cfg_float("POSITION_BE_OFFSET_ATR", 0.0, symbol)
    if pos.side == "long":
        be_stop = pos.entry_price + be_offset_atr * atr
        if pos.stop_loss is None or be_stop > pos.stop_loss:
            pos.stop_loss = be_stop
    else:
        be_stop = pos.entry_price - be_offset_atr * atr
        if pos.stop_loss is None or be_stop < pos.stop_loss:
            pos.stop_loss = be_stop
    pos.be_moved = True
    pos.tp1_hit = True
    pos.trail_active = True
    pos.tp1 = None
    update_peak_price(pos, price)


def maybe_activate_trailing(pos, price: float, atr: float) -> bool:
    if atr <= 0:
        return False
    symbol = getattr(pos, "symbol", "")
    if bool(getattr(cfg, "POSITION_TRAILING_ONLY_AFTER_TP1", False)) or bool(_cfg_float("POSITION_TRAILING_ONLY_AFTER_TP1", 0.0, symbol)):
        if not getattr(pos, "tp1_hit", False):
            return False
    activation_atr = _cfg_float("POSITION_TRAILING_ACTIVATION_ATR", _cfg_float("POSITION_TP1_ATR_MULT", _cfg_float("ATR_TP_MULT_1", 8.0, symbol), symbol), symbol)
    if activation_atr <= 0:
        return False
    if getattr(pos, "trail_active", False):
        return True
    if pos.side == "long":
        move_atr = (price - pos.entry_price) / atr
    else:
        move_atr = (pos.entry_price - price) / atr
    if move_atr >= activation_atr:
        pos.trail_active = True
        return True
    return False


def update_trailing_stop(pos, atr: float) -> bool:
    if atr <= 0 or not getattr(pos, "trail_active", False):
        return False
    peak = getattr(pos, "peak_price", None)
    if peak is None:
        return False
    symbol = getattr(pos, "symbol", "")
    trail_mult = _cfg_float("POSITION_TRAILING_ATR_MULT", _cfg_float("ATR_TS_MULT", 4.0, symbol), symbol)
    trail_step_atr = _cfg_float("POSITION_TRAILING_STEP_ATR", 0.0)
    if pos.side == "long":
        candidate = float(peak) - trail_mult * atr
        if pos.stop_loss is not None:
            candidate = max(candidate, float(pos.stop_loss))
        if pos.trailing_stop is None or candidate > pos.trailing_stop + trail_step_atr * atr:
            pos.trailing_stop = candidate
            if pos.stop_loss is None or candidate > pos.stop_loss:
                pos.stop_loss = candidate
            return True
    else:
        candidate = float(peak) + trail_mult * atr
        if pos.stop_loss is not None:
            candidate = min(candidate, float(pos.stop_loss))
        if pos.trailing_stop is None or candidate < pos.trailing_stop - trail_step_atr * atr:
            pos.trailing_stop = candidate
            if pos.stop_loss is None or candidate < pos.stop_loss:
                pos.stop_loss = candidate
            return True
    return False


def should_close_on_trailing(pos, price: float) -> bool:
    ts = getattr(pos, "trailing_stop", None)
    if ts is None:
        return False
    if pos.side == "long":
        return price <= ts
    return price >= ts


def tp1_fraction() -> float:
    frac = _cfg_float("POSITION_TP1_CLOSE_FRACTION", 0.5)
    if frac <= 0:
        return 0.0
    if frac >= 1:
        return 0.99
    return frac
