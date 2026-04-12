from __future__ import annotations

import pandas as pd


def extract_bar_timestamp(df: pd.DataFrame):
    """Пытается достать timestamp последней свечи из open_time или DatetimeIndex."""
    try:
        last = df.iloc[-1]
        if "open_time" in df.columns:
            raw = last.get("open_time")
            ts = pd.to_datetime(raw, utc=True, unit="ms")
            if pd.isna(ts):
                ts = pd.to_datetime(raw, utc=True)
            if not pd.isna(ts):
                return ts
    except Exception:
        pass

    try:
        idx = df.index[-1]
        ts = pd.to_datetime(idx, utc=True)
        if not pd.isna(ts):
            return ts
    except Exception:
        pass
    return None


def is_allowed_trading_time(cfg, df: pd.DataFrame, timestamp_extractor=extract_bar_timestamp) -> tuple[bool, dict]:
    """Фильтр торговых часов. Использует время закрытой LTF-свечи."""
    try:
        enabled = bool(getattr(cfg, "SESSION_TIME_FILTER_ENABLED", False))
        if not enabled:
            return True, {"enabled": False}

        windows = getattr(cfg, "SESSION_ALLOWED_WINDOWS", [(0, 24)]) or [(0, 24)]
        timezone_name = str(getattr(cfg, "SESSION_TIME_FILTER_TIMEZONE", "UTC") or "UTC")
        ts = timestamp_extractor(df)
        if ts is None or pd.isna(ts):
            return True, {"enabled": True, "skipped": "no_timestamp"}

        if timezone_name and timezone_name.upper() != "UTC":
            try:
                ts = ts.tz_convert(timezone_name)
            except Exception:
                pass

        hour = int(ts.hour)
        minute = int(ts.minute)

        for start_hour, end_hour in windows:
            start_hour = int(start_hour)
            end_hour = int(end_hour)
            if start_hour == end_hour:
                return True, {"enabled": True, "hour": hour, "minute": minute, "windows": windows}
            if start_hour < end_hour:
                if start_hour <= hour < end_hour:
                    return True, {"enabled": True, "hour": hour, "minute": minute, "windows": windows}
            else:
                if hour >= start_hour or hour < end_hour:
                    return True, {"enabled": True, "hour": hour, "minute": minute, "windows": windows}

        return False, {
            "reason": "outside_allowed_session",
            "hour": hour,
            "minute": minute,
            "timezone": timezone_name,
            "windows": windows,
        }
    except Exception as exc:
        return False, {"reason": "session_filter_exception", "error": str(exc)}
