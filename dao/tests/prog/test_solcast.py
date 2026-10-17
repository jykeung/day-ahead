"""Solcast PV Forecast as a solar source (dao/prog/solcast.py + DaBase)."""

import datetime as dt
from types import SimpleNamespace

import pandas as pd
import pytest

from dao.prog.config.models.devices.solar import SolarConfig
from dao.prog.da_base import DaBase
from dao.prog.solcast import interval_energy, parse_periods

TZ = "Europe/Brussels"


def _entry(start: str, kw: float, **extra) -> dict:
    return {"period_start": start, "pv_estimate": kw, **extra}


def test_parse_periods_converts_to_local_naive_and_sorts():
    periods = parse_periods(
        [_entry("2026-10-17T10:30:00+00:00", 2.0), _entry("2026-10-17T12:00:00+02:00", 1.0)],
        time_zone=TZ,
    )
    assert periods == [
        (dt.datetime(2026, 10, 17, 12, 0), dt.datetime(2026, 10, 17, 12, 30), 1.0),
        (dt.datetime(2026, 10, 17, 12, 30), dt.datetime(2026, 10, 17, 13, 0), 2.0),
    ]


def test_parse_periods_picks_estimate_and_skips_bad_entries():
    periods = parse_periods(
        [
            _entry("2026-10-17T12:00:00+02:00", 5.0, pv_estimate10=2.0),
            {"period_start": "garbage", "pv_estimate10": 1.0},
            {"pv_estimate10": 1.0},
            "not a dict",
        ],
        estimate="pv_estimate10",
        time_zone=TZ,
    )
    assert periods == [(dt.datetime(2026, 10, 17, 12, 0), dt.datetime(2026, 10, 17, 12, 30), 2.0)]


def test_parse_periods_deduplicates_overlapping_days_and_clips_negative():
    periods = parse_periods(
        [_entry("2026-10-17T12:00:00+02:00", 1.0), _entry("2026-10-17T12:00:00+02:00", -0.5)],
        time_zone=TZ,
    )
    assert periods == [(dt.datetime(2026, 10, 17, 12, 0), dt.datetime(2026, 10, 17, 12, 30), 0.0)]


@pytest.fixture
def half_hours():
    # 12:00-12:30 at 4 kW, 12:30-13:00 at 2 kW
    return parse_periods(
        [_entry("2026-10-17T12:00:00+02:00", 4.0), _entry("2026-10-17T12:30:00+02:00", 2.0)],
        time_zone=TZ,
    )


def test_quarter_inside_a_period(half_hours):
    start = dt.datetime(2026, 10, 17, 12, 15)
    assert interval_energy(half_hours, start, start + dt.timedelta(minutes=15)) == pytest.approx(1.0)


def test_hour_spanning_two_periods(half_hours):
    start = dt.datetime(2026, 10, 17, 12, 0)
    assert interval_energy(half_hours, start, start + dt.timedelta(hours=1)) == pytest.approx(3.0)


def test_uncovered_or_partly_covered_interval_is_none(half_hours):
    start = dt.datetime(2026, 10, 17, 13, 0)
    assert interval_energy(half_hours, start, start + dt.timedelta(minutes=15)) is None
    start = dt.datetime(2026, 10, 17, 12, 45)
    assert interval_energy(half_hours, start, start + dt.timedelta(minutes=30)) is None


def _solar(**solcast) -> SolarConfig:
    return SolarConfig.model_validate(
        {
            "name": "Huawei",
            "tilt": 44,
            "orientation": 0,
            "capacity": 12.2,
            "yield": 0.9,
            "solcast": {"entities": "sensor.solcast_today", **solcast},
        }
    )


def _dabase(states: dict, own: list[float]) -> DaBase:
    obj = DaBase.__new__(DaBase)
    obj.interval_s = 900
    obj.time_zone = TZ
    grid = [dt.datetime(2026, 10, 17, 12, 0) + dt.timedelta(minutes=15 * i) for i in range(len(own))]
    obj.get_state = lambda entity: states[entity]
    obj.calc_solar_predictions = lambda *a, **k: pd.DataFrame({"tijd": grid, "prediction": own})
    return obj


def test_calc_solcast_predictions_overrides_covered_intervals_only():
    state = SimpleNamespace(
        state="12.3",
        attributes={
            "detailedForecast": [
                _entry("2026-10-17T12:00:00+02:00", 4.0),
                _entry("2026-10-17T12:30:00+02:00", 2.0),
            ]
        },
    )
    obj = _dabase({"sensor.solcast_today": state}, own=[9.0, 9.0, 9.0, 9.0, 9.0])
    result = obj.calc_solcast_predictions(
        _solar(), dt.datetime(2026, 10, 17, 12), dt.datetime(2026, 10, 17, 13, 15), "15min"
    )
    # four quarters from Solcast, the fifth beyond its horizon keeps the own value
    assert list(result["prediction"]) == [1.0, 1.0, 0.5, 0.5, 9.0]


def test_calc_solcast_predictions_caps_at_max_power_and_survives_missing_entity():
    state = SimpleNamespace(
        state="12.3", attributes={"detailedForecast": [_entry("2026-10-17T12:00:00+02:00", 10.0)]}
    )
    solar = _solar(entities=["sensor.solcast_today", "sensor.missing"])
    solar.max_power = 8.0
    states = {"sensor.solcast_today": state}

    def get_state(entity):
        if entity not in states:
            raise KeyError(entity)
        return states[entity]

    obj = _dabase(states, own=[0.0, 0.0])
    obj.get_state = get_state
    result = obj.calc_solcast_predictions(
        solar, dt.datetime(2026, 10, 17, 12), dt.datetime(2026, 10, 17, 12, 30), "15min"
    )
    assert list(result["prediction"]) == [2.0, 2.0]


def test_calc_solar_predictions_dispatches_to_solcast_only_when_configured(monkeypatch):
    obj = DaBase.__new__(DaBase)
    called = []
    monkeypatch.setattr(
        DaBase, "calc_solcast_predictions", lambda self, *a, **k: called.append(a) or "solcast"
    )
    solar = _solar()
    assert obj.calc_solar_predictions(solar, None, None, "15min") == "solcast"
    assert len(called) == 1
