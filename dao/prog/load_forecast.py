"""Replace baseline demand with a read-only HA forecast of total house load.

Rows are explicit, non-overlapping [start, end) intervals with power_kw.
Full interval energy is returned: the optimizer applies its first-interval
fraction later, exactly once. Missing/stale coverage retains the baseline.
"""
from __future__ import annotations

import datetime as dt
import math
from zoneinfo import ZoneInfo


def forecast_baseload(attributes, times, interval_seconds, fallback, time_zone, now,
                      excluded_components=()):
    """Return (interval kWh, number covered); never add a total-load forecast twice."""
    result = list(fallback)
    generated = dt.datetime.fromisoformat(attributes['generated_at'])
    if generated.tzinfo is None or now.tzinfo is None:
        raise ValueError('Forecast timestamps must include a timezone')
    age = (now - generated).total_seconds()
    if not 0 <= age <= 1800:
        raise ValueError('Load forecast is stale or dated in the future')
    periods = []
    for row in attributes['schedule']:
        start = dt.datetime.fromisoformat(row['start'])
        end = dt.datetime.fromisoformat(row['end'])
        power = float(row['power_kw'])
        if start.tzinfo is None or end.tzinfo is None or end <= start:
            raise ValueError('Invalid forecast interval')
        if not math.isfinite(power) or power < 0:
            raise ValueError('Invalid forecast power')
        removed = 0.0
        for component in excluded_components:
            value = float(row[component])
            if not math.isfinite(value) or value < 0:
                raise ValueError(f'Invalid forecast component: {component}')
            removed += value
        if removed > power + 0.0001:
            raise ValueError('Forecast components exceed total demand')
        power = max(0.0, power - removed)
        periods.append((start.timestamp(), end.timestamp(), power))
    periods.sort()
    if any(b[0] < a[1] for a, b in zip(periods, periods[1:])):
        raise ValueError('Overlapping load forecast intervals')
    covered = 0
    zone = ZoneInfo(time_zone) if time_zone else now.tzinfo
    widths = ([interval_seconds] * len(times) if isinstance(interval_seconds, (int, float))
              else list(interval_seconds))
    if len(widths) != len(times) or any(width <= 0 for width in widths):
        raise ValueError("Invalid forecast interval durations")
    for i, value in enumerate(times):
        interval_seconds = widths[i]
        start = value.replace(tzinfo=zone).timestamp() if value.tzinfo is None else value.timestamp()
        end = start + interval_seconds
        seconds = energy = 0.0
        for p_start, p_end, power in periods:
            overlap = max(0, min(end, p_end) - max(start, p_start))
            seconds += overlap
            energy += power * overlap / 3600
        if abs(seconds - interval_seconds) < 1:
            result[i] = energy
            covered += 1
    return result, covered
