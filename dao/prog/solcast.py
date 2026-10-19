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
    forecasts: Iterable[dict],
    estimate: str = "pv_estimate",
    time_zone: str | None = None,
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
        end = (
            nxt
            if nxt is not None and nxt - start <= DEFAULT_PERIOD
            else start + DEFAULT_PERIOD
        )
        periods.append((start, end, by_start[start]))
    return periods


def interval_energy(
    periods: list[Period], start: dt.datetime, end: dt.datetime
) -> float | None:
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


def blend_periods(
    base: list[Period], cautious: list[Period], caution: float
) -> list[Period]:
    """Move each period from ``base`` towards ``cautious`` by ``caution`` (0-1).

    With base = P50 and cautious = P10, 0.5 plans midway between them: storing
    solar that turns out not to be needed costs only the round-trip loss, a
    grey day the plan did not expect costs the full buy price.
    """
    if caution <= 0:
        return base
    low = {start: kw for start, _, kw in cautious}
    return [
        (start, end, kw + caution * (low[start] - kw) if start in low else kw)
        for start, end, kw in base
    ]


def _energy_between(
    periods: list[Period], start: dt.datetime, end: dt.datetime
) -> float:
    return sum(
        kw * max(0.0, (min(end, p_end) - max(start, p_start)).total_seconds()) / 3600
        for p_start, p_end, kw in periods
    )


def same_day_ratio(
    periods: list[Period],
    now: dt.datetime,
    measured_kwh: float,
    confidence_kwh: float = 2.0,
    bounds: tuple[float, float] = (0.25, 2.0),
) -> float:
    """Measured / forecast energy since midnight, eased in as evidence grows.

    Solcast updates a few times a day from weather models and satellites; the
    inverter knows how the day is really going. Early in the morning a few
    hundred Wh say little, so the ratio moves from 1 towards the measured one
    as the forecast energy so far approaches ``confidence_kwh``.
    """
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    expected = _energy_between(periods, day_start, now)
    if expected < 0.05:
        return 1.0
    raw = min(max(measured_kwh / expected, bounds[0]), bounds[1])
    weight = min(1.0, expected / confidence_kwh)
    return 1.0 + weight * (raw - 1.0)


def scale_rest_of_day(
    periods: list[Period], now: dt.datetime, ratio: float
) -> list[Period]:
    """Scale the periods from ``now`` until midnight; other days stay as forecast."""
    if ratio == 1.0:
        return periods
    day_end = now.replace(hour=0, minute=0, second=0, microsecond=0) + dt.timedelta(
        days=1
    )
    return [
        (start, end, kw * ratio if end > now and start < day_end else kw)
        for start, end, kw in periods
    ]


def local_now(time_zone: str | None) -> dt.datetime:
    if time_zone:
        return pd.Timestamp.now(tz=time_zone).tz_localize(None).to_pydatetime()
    return dt.datetime.now()
