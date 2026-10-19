"""Solcast PV Forecast as a solar source (dao/prog/solcast.py + DaBase)."""

import datetime as dt
from types import SimpleNamespace

import pandas as pd
import pytest

from dao.prog import solcast
from dao.prog.config.models.devices.solar import SolarConfig
from dao.prog.da_base import DaBase
from dao.prog.solcast import (
    blend_periods,
    interval_energy,
    parse_periods,
    same_day_ratio,
    scale_rest_of_day,
)

TZ = "Europe/Brussels"


def _entry(start: str, kw: float, **extra) -> dict:
    return {"period_start": start, "pv_estimate": kw, **extra}


def test_parse_periods_converts_to_local_naive_and_sorts():
    periods = parse_periods(
        [
            _entry("2026-10-17T10:30:00+00:00", 2.0),
            _entry("2026-10-17T12:00:00+02:00", 1.0),
        ],
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
    assert periods == [
        (dt.datetime(2026, 10, 17, 12, 0), dt.datetime(2026, 10, 17, 12, 30), 2.0)
    ]


def test_parse_periods_deduplicates_overlapping_days_and_clips_negative():
    periods = parse_periods(
        [
            _entry("2026-10-17T12:00:00+02:00", 1.0),
            _entry("2026-10-17T12:00:00+02:00", -0.5),
        ],
        time_zone=TZ,
    )
    assert periods == [
        (dt.datetime(2026, 10, 17, 12, 0), dt.datetime(2026, 10, 17, 12, 30), 0.0)
    ]


@pytest.fixture
def half_hours():
    # 12:00-12:30 at 4 kW, 12:30-13:00 at 2 kW
    return parse_periods(
        [
            _entry("2026-10-17T12:00:00+02:00", 4.0),
            _entry("2026-10-17T12:30:00+02:00", 2.0),
        ],
        time_zone=TZ,
    )


def test_quarter_inside_a_period(half_hours):
    start = dt.datetime(2026, 10, 17, 12, 15)
    assert interval_energy(
        half_hours, start, start + dt.timedelta(minutes=15)
    ) == pytest.approx(1.0)


def test_hour_spanning_two_periods(half_hours):
    start = dt.datetime(2026, 10, 17, 12, 0)
    assert interval_energy(
        half_hours, start, start + dt.timedelta(hours=1)
    ) == pytest.approx(3.0)


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
    grid = [
        dt.datetime(2026, 10, 17, 12, 0) + dt.timedelta(minutes=15 * i)
        for i in range(len(own))
    ]
    obj.get_state = lambda entity: states[entity]
    obj.calc_solar_predictions = lambda *a, **k: pd.DataFrame(
        {"tijd": grid, "prediction": own}
    )
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
        _solar(),
        dt.datetime(2026, 10, 17, 12),
        dt.datetime(2026, 10, 17, 13, 15),
        "15min",
    )
    # four quarters from Solcast, the fifth beyond its horizon keeps the own value
    assert list(result["prediction"]) == [1.0, 1.0, 0.5, 0.5, 9.0]


def test_calc_solcast_predictions_caps_at_max_power_and_survives_missing_entity():
    state = SimpleNamespace(
        state="12.3",
        attributes={"detailedForecast": [_entry("2026-10-17T12:00:00+02:00", 10.0)]},
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
        DaBase,
        "calc_solcast_predictions",
        lambda self, *a, **k: called.append(a) or "solcast",
    )
    solar = _solar()
    assert obj.calc_solar_predictions(solar, None, None, "15min") == "solcast"
    assert len(called) == 1


def _day(kw_by_hour: dict[int, float]) -> list:
    return [
        (dt.datetime(2026, 10, 19, h), dt.datetime(2026, 10, 19, h, 30), kw)
        for h, kw in kw_by_hour.items()
    ]


def test_blend_moves_towards_cautious_and_keeps_unmatched_periods():
    base = _day({12: 4.0, 13: 2.0})
    cautious = _day({12: 1.0})
    assert blend_periods(base, cautious, 0.5) == _day({12: 2.5, 13: 2.0})
    assert blend_periods(base, cautious, 0.0) is base


def test_same_day_ratio_replays_19_october():
    # 10:18: Solcast expected ~1.0 kWh so far, the inverter measured 0.57
    periods = _day({9: 1.0, 10: 1.0, 11: 4.0})  # 0.5 + 0.5 kWh before 10:30
    now = dt.datetime(2026, 10, 19, 10, 30)
    # half the confidence energy seen: halfway from 1 to 0.57
    assert same_day_ratio(periods, now, 0.57) == pytest.approx(1 + 0.5 * (0.57 - 1))
    assert same_day_ratio(periods, now, 0.57, confidence_kwh=1.0) == pytest.approx(0.57)


def test_same_day_ratio_is_neutral_before_sunrise_and_bounded():
    periods = _day({9: 4.0})
    assert same_day_ratio(periods, dt.datetime(2026, 10, 19, 8), 0.3) == 1.0
    now = dt.datetime(2026, 10, 19, 10)
    assert same_day_ratio(periods, now, 0.0) == pytest.approx(0.25)
    assert same_day_ratio(periods, now, 50.0) == pytest.approx(2.0)


def test_scale_rest_of_day_leaves_the_past_and_tomorrow():
    periods = _day({9: 1.0, 13: 2.0}) + [
        (dt.datetime(2026, 10, 20, 12), dt.datetime(2026, 10, 20, 12, 30), 3.0)
    ]
    scaled = scale_rest_of_day(periods, dt.datetime(2026, 10, 19, 12), 0.5)
    assert [kw for _, _, kw in scaled] == [1.0, 1.0, 3.0]


def test_calc_solcast_predictions_blends_and_corrects_today(monkeypatch):
    forecast = [
        _entry("2026-10-17T08:00:00+02:00", 4.0, pv_estimate10=2.0),
        _entry("2026-10-17T08:30:00+02:00", 4.0, pv_estimate10=2.0),
        _entry("2026-10-17T12:00:00+02:00", 8.0, pv_estimate10=4.0),
        _entry("2026-10-17T12:30:00+02:00", 8.0, pv_estimate10=4.0),
    ]
    states = {
        "sensor.solcast_today": SimpleNamespace(
            state="1", attributes={"detailedForecast": forecast}
        ),
        # midway forecast so far: 2 x 3 kW x 0.5 h = 3 kWh, measured 1.5
        "sensor.yield_today": SimpleNamespace(state="1.5", attributes={}),
    }
    monkeypatch.setattr(
        solcast, "local_now", lambda tz: dt.datetime(2026, 10, 17, 9, 0)
    )
    obj = _dabase(states, own=[0.0, 0.0])
    result = obj.calc_solcast_predictions(
        _solar(caution=0.5, **{"entity measured today": "sensor.yield_today"}),
        dt.datetime(2026, 10, 17, 12),
        dt.datetime(2026, 10, 17, 12, 30),
        "15min",
    )
    # midway 6 kW x 0.25 h = 1.5 kWh per quarter, halved by the measured ratio
    assert list(result["prediction"]) == [0.75, 0.75]


def test_correction_is_skipped_while_curtailed(monkeypatch):
    forecast = [
        _entry("2026-10-17T08:00:00+02:00", 4.0),
        _entry("2026-10-17T12:00:00+02:00", 8.0),
    ]
    states = {
        "sensor.solcast_today": SimpleNamespace(
            state="1", attributes={"detailedForecast": forecast}
        ),
        "sensor.yield_today": SimpleNamespace(state="0.1", attributes={}),
        "input_number.pv_limit": SimpleNamespace(state="0", attributes={}),
    }
    monkeypatch.setattr(
        solcast, "local_now", lambda tz: dt.datetime(2026, 10, 17, 9, 0)
    )
    solar = _solar(**{"entity measured today": "sensor.yield_today"})
    solar.entity_pv_limit = "input_number.pv_limit"
    solar.max_power = 10.0
    obj = _dabase(states, own=[0.0])
    result = obj.calc_solcast_predictions(
        solar, dt.datetime(2026, 10, 17, 12), dt.datetime(2026, 10, 17, 12, 15), "15min"
    )
    assert list(result["prediction"]) == [2.0]
