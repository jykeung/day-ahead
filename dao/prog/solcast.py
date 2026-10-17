"""Solar forecast from the Solcast PV Forecast integration in Home Assistant.

The integration (BJReplay/ha-solcast-solar) publishes, per forecast day, a
sensor whose ``detailedForecast`` attribute lists 30-minute periods::

    {"period_start": "2026-10-17T12:00:00+02:00",
     "pv_estimate": 7.4, "pv_estimate10": 3.1, "pv_estimate90": 8.2}

Each estimate is the average AC power in kW over the period. These helpers
turn that into energy per DAO interval. They are pure functions so they can
be tested without Home Assistant.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable

import pandas as pd

# (start, end, kW) with naive local datetimes, as DAO's own interval grid uses
Period = tuple[dt.datetime, dt.datetime, float]

DEFAULT_PERIOD = dt.timedelta(minutes=30)


def _to_local_naive(value, time_zone: str | None) -> dt.datetime:
    ts = pd.Timestamp(value)
    if ts.tzinfo is not None:
        if time_zone:
            ts = ts.tz_convert(time_zone)
        ts = ts.tz_localize(None)
    return ts.to_pydatetime()


def parse_periods(
    forecasts: Iterable[dict], estimate: str = "pv_estimate", time_zone: str | None = None
) -> list[Period]:
    """Solcast forecast entries -> sorted, de-duplicated (start, end, kW).

    Entries without the estimate or a parseable period_start are skipped. A
    period ends where the next one starts, or after 30 minutes for the last.
    """
    by_start: dict[dt.datetime, float] = {}
    for entry in forecasts:
        if not isinstance(entry, dict):
            continue
        try:
            start = _to_local_naive(entry["period_start"], time_zone)
            kw = float(entry[estimate])
        except (KeyError, TypeError, ValueError):
            continue
        by_start[start] = max(kw, 0.0)
    starts = sorted(by_start)
    periods: list[Period] = []
    for i, start in enumerate(starts):
        nxt = starts[i + 1] if i + 1 < len(starts) else None
        end = nxt if nxt is not None and nxt - start <= DEFAULT_PERIOD else start + DEFAULT_PERIOD
        periods.append((start, end, by_start[start]))
    return periods


def interval_energy(periods: list[Period], start: dt.datetime, end: dt.datetime) -> float | None:
    """Energy (kWh) in [start, end), or None if the periods do not cover it.

    None lets the caller fall back to another prediction for intervals beyond
    the Solcast horizon instead of silently planning zero production.
    """
    total_s = (end - start).total_seconds()
    if total_s <= 0:
        return 0.0
    covered_s = 0.0
    kwh = 0.0
    for p_start, p_end, kw in periods:
        overlap = (min(end, p_end) - max(start, p_start)).total_seconds()
        if overlap > 0:
            covered_s += overlap
            kwh += kw * overlap / 3600
    if covered_s < total_s - 1:
        return None
    return kwh
