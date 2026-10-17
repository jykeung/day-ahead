"""Plan export rows (dao/prog/plan_export.py)."""

import datetime as dt

from dao.prog.plan_export import build_plan_rows


def test_rows_are_average_kw_with_signed_grid_and_battery():
    t0 = dt.datetime(2026, 10, 17, 12, 0)
    rows = build_plan_rows(
        tijd=[t0, t0 + dt.timedelta(minutes=15)],
        hour_fraction=[0.25, 0.25],
        pv_forecast_kwh=[2.0, 2.0],
        pv_kwh=[2.0, 1.5],
        import_kwh=[0.0, 0.1],
        export_kwh=[1.0, 0.0],
        battery_in_kwh=[0.6, 0.0],
        battery_out_kwh=[0.0, 0.3],
        load_kwh=[0.4, 1.9],
        soc_end=[52.04, 49.4],
        price_buy=[0.25, 0.30],
        price_sell=[0.05, -0.01],
        time_zone="Europe/Brussels",
    )
    assert rows[0] == {
        "t": "2026-10-17T12:00:00+02:00",
        "pv_forecast": 8.0,
        "pv": 8.0,
        "grid": -4.0,
        "battery": 2.4,
        "load": 1.6,
        "buy": 0.25,
        "sell": 0.05,
        "soc": 52.0,
    }
    assert rows[1]["pv"] == 6.0  # curtailed below the 8 kW forecast
    assert rows[1]["grid"] == 0.4
    assert rows[1]["battery"] == -1.2
    assert rows[1]["sell"] == -0.01


def test_partial_first_interval_and_no_battery():
    t0 = dt.datetime(2026, 10, 17, 12, 10)
    rows = build_plan_rows(
        tijd=[t0], hour_fraction=[5 / 60], pv_forecast_kwh=[0.5], pv_kwh=[0.5],
        import_kwh=[0.0], export_kwh=[0.25], battery_in_kwh=[0.0], battery_out_kwh=[0.0],
        load_kwh=[0.25], soc_end=None, price_buy=[0.2], price_sell=[0.1],
    )
    assert rows[0]["pv"] == 6.0 and rows[0]["grid"] == -3.0
    assert "soc" not in rows[0]
    assert rows[0]["t"] == "2026-10-17T12:10:00"
