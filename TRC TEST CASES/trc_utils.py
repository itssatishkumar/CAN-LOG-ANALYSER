import os
from datetime import datetime
from typing import Callable, Optional, Tuple


def progress_by_bytes(
    path: str,
    step: float = 0.5,
    start: float = 0.0,
    end: float = 100.0,
) -> Callable[[int], None]:
    try:
        total = os.path.getsize(path)
    except OSError:
        total = 0

    processed = 0
    last = -1.0
    span = max(0.0, end - start)

    def emit(consumed: int) -> None:
        nonlocal processed, last
        if not total or span <= 0:
            return
        processed += consumed
        pct = start + (processed / total) * span
        pct = end if pct > end else pct
        if pct - last >= step or pct >= end:
            last = pct
            print(f"PROGRESS {pct:.1f}", flush=True)

    return emit


def fast_parse_ts(
    date_str: str,
    time_str: str,
    ms_str: str,
) -> Tuple[datetime, float, str]:
    ms_norm = ms_str if len(ms_str) == 4 else ms_str + "0" if len(ms_str) == 3 else ms_str
    micro = int(ms_norm.ljust(6, "0")[:6])

    day = int(date_str[0:2])
    month = int(date_str[3:5])
    year = int(date_str[6:10])
    hour = int(time_str[0:2])
    minute = int(time_str[3:5])
    second = int(time_str[6:8])

    dt = datetime(year, month, day, hour, minute, second, micro)
    ts_ms = dt.timestamp() * 1000.0
    return dt, ts_ms, f"{date_str} {time_str}.{ms_norm}"


def fast_datetime_from_str(ts_raw: str) -> Optional[datetime]:
    ts_clean = ts_raw.strip()
    if " " not in ts_clean:
        return None

    if "." in ts_clean:
        base, frac = ts_clean.rsplit(".", 1)
    else:
        base, frac = ts_clean, "0000"

    if len(frac) < 3:
        frac = frac.ljust(3, "0")
    if len(frac) == 3:
        frac = frac + "0"
    elif len(frac) > 4:
        frac = frac[:4]

    try:
        date_str, time_str = base.split()
    except ValueError:
        return None

    try:
        dt, _, _ = fast_parse_ts(date_str, time_str, frac)
        return dt
    except Exception:
        return None
