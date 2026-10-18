"""Time-of-day SOC floor for batteries ("lower limit schedule").

A battery's "lower limit" is one number for the whole planning horizon. Some
reserves only matter part of the day -- energy kept back to defend the
capacity peak during the evening cooking hours, say -- so a schedule raises
the floor inside clock windows and leaves the plain lower limit elsewhere.
Kept free of HA and MIP imports so it can be tested on its own.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable


def parse_hhmm(value: str) -> dt.time:
    """'17:30' -> time(17, 30); '24:00' is accepted as end of day."""
    hours, minutes = (int(part) for part in str(value).strip().split(":"))
    if hours == 24 and minutes == 0:
        return dt.time.max
    return dt.time(hours, minutes)


def in_window(moment: dt.datetime, start: dt.time, end: dt.time) -> bool:
    """True when the clock time of ``moment`` lies in [start, end); windows may wrap midnight."""
    t = moment.time()
    if start <= end:
        return start <= t < end
    return t >= start or t < end


def floor_at(moment: dt.datetime, base: float, windows: Iterable[tuple[dt.time, dt.time, float]]) -> float:
    """The SOC floor in force at ``moment``: the highest of the base limit and every window covering it."""
    floor = base
    for start, end, limit in windows:
        if in_window(moment, start, end):
            floor = max(floor, limit)
    return floor
