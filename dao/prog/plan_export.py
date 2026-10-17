"""The optimized plan as rows for a Home Assistant entity attribute.

Dashboards can chart a list of row dicts directly (one row per interval),
so after each optimization DAO can publish its whole plan - not just the
first interval it acts on - on a single entity. Powers are average kW over
the interval (energy / interval hours), so 15-minute and hourly plans read
the same way. Pure function: no HA, no model.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence


def _kw(kwh: float, hours: float) -> float:
    return round(kwh / hours, 3) if hours > 0 else 0.0


def build_plan_rows(
    tijd: Sequence[dt.datetime],
    hour_fraction: Sequence[float],
    pv_forecast_kwh: Sequence[float],
    pv_kwh: Sequence[float],
    import_kwh: Sequence[float],
    export_kwh: Sequence[float],
    battery_in_kwh: Sequence[float],
    battery_out_kwh: Sequence[float],
    load_kwh: Sequence[float],
    soc_end: Sequence[float] | None,
    price_buy: Sequence[float],
    price_sell: Sequence[float],
    time_zone: str | None = None,
) -> list[dict]:
    """One dict per interval.

    t            interval start, ISO 8601 with UTC offset
    pv_forecast  PV forecast before optimization (kW)
    pv           planned PV after curtailment (kW)
    grid         + import / - export (kW)
    battery      + charging / - discharging, AC side (kW)
    load         consumption excluding the battery (kW)
    soc          planned state of charge at the end of the interval (%)
    buy, sell    consumption and feed-in tariff (EUR/kWh)
    """
    import pandas as pd

    rows = []
    for u, start in enumerate(tijd):
        hours = hour_fraction[u]
        ts = pd.Timestamp(start)
        if ts.tzinfo is None and time_zone:
            ts = ts.tz_localize(time_zone, ambiguous="NaT", nonexistent="shift_forward")
        row = {
            "t": ts.isoformat() if ts is not pd.NaT else pd.Timestamp(start).isoformat(),
            "pv_forecast": _kw(pv_forecast_kwh[u], hours),
            "pv": _kw(pv_kwh[u], hours),
            "grid": _kw(import_kwh[u] - export_kwh[u], hours),
            "battery": _kw(battery_in_kwh[u] - battery_out_kwh[u], hours),
            "load": _kw(load_kwh[u], hours),
            "buy": round(float(price_buy[u]), 5),
            "sell": round(float(price_sell[u]), 5),
        }
        if soc_end is not None:
            row["soc"] = round(float(soc_end[u]), 1)
        rows.append(row)
    return rows
