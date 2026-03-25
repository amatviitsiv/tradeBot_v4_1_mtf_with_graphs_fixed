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


def _position_profile_from_values(market_state: str = "", trade_type: str = "") -> str:
    market_state = str(market_state or "").lower()
    trade_type = str(trade_type or "").lower()
    if trade_type == "alt_reversion":
        return "alt_reversion"
    if trade_type in {"continuation", "cont_compression"}:
        return "continuation"
    if market_state in {"range", "transition"}:
        return "range"
    if trade_type in {"range", "fakeout", "btc_exhaustion", "btc_exhaustion_short", "exhaustion_short"}:
        return "range"
    return "trend"


def _position_profile(pos) -> str:
    return _position_profile_from_values(
        getattr(pos, "market_state", "") if pos is not None else "",
        getattr(pos, "trade_type", "") if pos is not None else "",
    )


def _profile_cfg_float(base_name: str, default: float, pos=None, symbol: str = "") -> float:
    profile = _position_profile(pos) if pos is not None else "trend"
    prof_name = f"{base_name}_{profile.upper()}"
    try:
        if symbol:
            v = cfg.get_symbol_param(symbol, prof_name, None)
            if v is not None:
                return float(v)
        v = getattr(cfg, prof_name, None)
        if v is not None:
            return float(v)
    except Exception:
        pass
    return _cfg_float(base_name, default, symbol)


def calc_tp1_price(entry_price: float, atr: float, side: str, symbol: str = "", pos=None) -> float:
    tp1_mult = _profile_cfg_float("POSITION_TP1_ATR_MULT", _cfg_float("ATR_TP_MULT_1", 8.0, symbol), pos, symbol)
    if side == "long":
        return entry_price + tp1_mult * atr
    return entry_price - tp1_mult * atr


def calc_initial_stop_price(entry_price: float, atr: float, side: str, symbol: str = "", pos=None, trade_type: str = "", market_state: str = "") -> float:
    profile = _position_profile(pos) if pos is not None else _position_profile_from_values(market_state, trade_type)
    sl_mult = _cfg_float("POSITION_INITIAL_SL_ATR_MULT", _cfg_float("ATR_SL_MULT", 5.0, symbol), symbol)
    prof_name = f"POSITION_INITIAL_SL_ATR_MULT_{profile.upper()}"
    try:
        if symbol:
            v = cfg.get_symbol_param(symbol, prof_name, None)
            if v is not None:
                sl_mult = float(v)
            else:
                v = cfg.get_symbol_param(symbol, "POSITION_INITIAL_SL_ATR_MULT", None)
                if v is not None:
                    sl_mult = float(v)
        v = getattr(cfg, prof_name, None)
        if v is not None:
            sl_mult = float(v)
    except Exception:
        pass
    if side == "long":
        return entry_price - sl_mult * atr
    return entry_price + sl_mult * atr


def update_peak_price(pos, price: float, bar_index: int | None = None) -> None:
    peak = getattr(pos, "peak_price", None)
    if peak is None:
        pos.peak_price = float(price)
        if bar_index is not None:
            try:
                pos.peak_bar_index = int(bar_index)
            except Exception:
                pass
        return
    updated = False
    if pos.side == "long":
        new_peak = max(float(peak), float(price))
        updated = new_peak > float(peak)
        pos.peak_price = new_peak
    else:
        new_peak = min(float(peak), float(price))
        updated = new_peak < float(peak)
        pos.peak_price = new_peak
    if updated and bar_index is not None:
        try:
            pos.peak_bar_index = int(bar_index)
        except Exception:
            pass


def maybe_move_to_break_even(pos, price: float, atr: float) -> bool:
    if atr <= 0:
        return False
    symbol = getattr(pos, "symbol", "")
    if bool(getattr(cfg, "POSITION_BE_ONLY_AFTER_TP1", False)) or bool(_cfg_float("POSITION_BE_ONLY_AFTER_TP1", 0.0, symbol)):
        if not getattr(pos, "tp1_hit", False):
            return False
    trigger_atr = _profile_cfg_float("POSITION_BE_TRIGGER_ATR", 0.0, pos, symbol)
    if trigger_atr <= 0:
        return False
    be_offset_atr = _profile_cfg_float("POSITION_BE_OFFSET_ATR", 0.0, pos, symbol)
    min_progress_after_tp1_atr = _profile_cfg_float("POSITION_BE_MIN_PROGRESS_AFTER_TP1_ATR", 0.0, pos, symbol)
    moved = getattr(pos, "be_moved", False)
    if pos.side == "long":
        move_atr = (price - pos.entry_price) / atr
        if move_atr < trigger_atr:
            return False
        if getattr(pos, "tp1_hit", False) and min_progress_after_tp1_atr > 0:
            tp1_ref = float(getattr(pos, "tp1_hit_price", getattr(pos, "entry_price", price)) or price)
            if (price - tp1_ref) / atr < min_progress_after_tp1_atr:
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
        if getattr(pos, "tp1_hit", False) and min_progress_after_tp1_atr > 0:
            tp1_ref = float(getattr(pos, "tp1_hit_price", getattr(pos, "entry_price", price)) or price)
            if (tp1_ref - price) / atr < min_progress_after_tp1_atr:
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
    move_be_on_tp1 = bool(_cfg_float("POSITION_MOVE_BE_ON_TP1", 0.0, symbol))
    if move_be_on_tp1:
        be_offset_atr = _profile_cfg_float("POSITION_BE_OFFSET_ATR", 0.0, pos, symbol)
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
    pos.trail_active = False
    pos.tp1 = None
    pos.tp1_hit_price = float(price)
    update_peak_price(pos, price, getattr(pos, "tp1_bar_index", None))


def maybe_activate_trailing(pos, price: float, atr: float) -> bool:
    if atr <= 0:
        return False
    symbol = getattr(pos, "symbol", "")
    if bool(getattr(cfg, "POSITION_TRAILING_ONLY_AFTER_TP1", False)) or bool(_cfg_float("POSITION_TRAILING_ONLY_AFTER_TP1", 0.0, symbol)):
        if not getattr(pos, "tp1_hit", False):
            return False
    activation_atr = _profile_cfg_float("POSITION_TRAILING_ACTIVATION_ATR", _profile_cfg_float("POSITION_TP1_ATR_MULT", _cfg_float("ATR_TP_MULT_1", 8.0, symbol), pos, symbol), pos, symbol)
    if activation_atr <= 0:
        return False
    if getattr(pos, "trail_active", False):
        return True
    if pos.side == "long":
        move_atr = (price - pos.entry_price) / atr
    else:
        move_atr = (pos.entry_price - price) / atr
    if move_atr < activation_atr:
        return False
    if getattr(pos, "tp1_hit", False):
        extra_after_tp1_atr = _profile_cfg_float("POSITION_RUNNER_ACTIVATION_ATR_AFTER_TP1", 0.0, pos, symbol)
        if extra_after_tp1_atr > 0:
            tp1_ref = float(getattr(pos, "tp1_hit_price", getattr(pos, "entry_price", price)) or price)
            if pos.side == "long":
                runner_move_atr = (price - tp1_ref) / atr
            else:
                runner_move_atr = (tp1_ref - price) / atr
            if runner_move_atr < extra_after_tp1_atr:
                return False
    pos.trail_active = True
    return True


def update_trailing_stop(pos, atr: float) -> bool:
    if atr <= 0 or not getattr(pos, "trail_active", False):
        return False
    peak = getattr(pos, "peak_price", None)
    if peak is None:
        return False
    symbol = getattr(pos, "symbol", "")
    trail_mult = _profile_cfg_float("POSITION_TRAILING_ATR_MULT", _cfg_float("ATR_TS_MULT", 4.0, symbol), pos, symbol)
    trail_step_atr = _profile_cfg_float("POSITION_TRAILING_STEP_ATR", 0.0, pos, symbol)
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


def tp1_fraction(pos=None) -> float:
    symbol = getattr(pos, "symbol", "") if pos is not None else ""
    frac = _profile_cfg_float("POSITION_TP1_CLOSE_FRACTION", 0.5, pos, symbol)
    if frac <= 0:
        return 0.0
    if frac >= 1:
        return 1.0
    return frac



def mark_tp1_bar(pos, bar_index: int | None) -> None:
    if bar_index is None:
        return
    try:
        pos.tp1_bar_index = int(bar_index)
    except Exception:
        pass


def should_time_stop_before_tp1(pos, bar_index: int | None) -> bool:
    if bar_index is None or getattr(pos, "tp1_hit", False):
        return False
    try:
        bars_limit = int(_profile_cfg_float("POSITION_TIME_STOP_BEFORE_TP1_BARS", 0.0, pos, getattr(pos, "symbol", "")))
    except Exception:
        bars_limit = 0
    if bars_limit <= 0:
        return False
    open_bar_index = getattr(pos, "open_time", None)
    if open_bar_index is None:
        return False
    try:
        return int(bar_index) - int(float(open_bar_index)) >= bars_limit
    except Exception:
        return False


def should_time_stop_after_tp1(pos, bar_index: int | None) -> bool:
    if bar_index is None or not getattr(pos, "tp1_hit", False):
        return False
    try:
        bars_limit = int(_profile_cfg_float("POSITION_TIME_STOP_AFTER_TP1_BARS", 0.0, pos, getattr(pos, "symbol", "")))
    except Exception:
        bars_limit = 0
    if bars_limit <= 0:
        return False
    tp1_bar_index = getattr(pos, "tp1_bar_index", None)
    if tp1_bar_index is None:
        return False
    try:
        return int(bar_index) - int(tp1_bar_index) >= bars_limit
    except Exception:
        return False


def should_close_runner_on_stall(pos, bar_index: int | None) -> bool:
    if bar_index is None:
        return False
    symbol = getattr(pos, "symbol", "")
    only_after_tp1 = bool(_cfg_float("POSITION_RUNNER_STALL_ONLY_AFTER_TP1", 1.0, symbol))
    if only_after_tp1 and not getattr(pos, "tp1_hit", False):
        return False
    try:
        bars_limit = int(_profile_cfg_float("POSITION_RUNNER_STALL_BARS", 0.0, pos, symbol))
    except Exception:
        bars_limit = 0
    if bars_limit <= 0:
        return False
    peak_bar_index = getattr(pos, "peak_bar_index", None)
    if peak_bar_index is None:
        peak_bar_index = getattr(pos, "tp1_bar_index", None)
    if peak_bar_index is None:
        return False
    try:
        return int(bar_index) - int(peak_bar_index) >= bars_limit
    except Exception:
        return False
