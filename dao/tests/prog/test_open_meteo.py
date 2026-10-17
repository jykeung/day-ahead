"""Open-Meteo as meteo source (dao/lib/da_meteo.py + config)."""

import pytest

from dao.lib.da_meteo import open_meteo_to_frame
from dao.prog.config.versions.v0 import ConfigurationV0


def test_rows_describe_the_hour_before_each_open_meteo_timestamp():
    hourly = {
        "time": [3600, 7200, 10800],
        "shortwave_radiation": [0.0, 500.0, 250.0],
        "temperature_2m": [10.0, 11.0, 12.0],
        "wind_speed_10m": [1.0, 2.0, 3.0],
        "precipitation": [0.0, 0.4, 0.0],
    }
    df = open_meteo_to_frame(hourly)
    assert list(df["tijd"]) == [3600, 7200]
    # 500 W/m2 over the hour 3600-7200 = 180 J/cm2, temperature at its start
    assert list(df["gr"]) == [180.0, 90.0]
    assert list(df["temp"]) == [10.0, 11.0]
    assert list(df["winds"]) == [1.0, 2.0]
    assert list(df["neersl"]) == [0.4, 0.0]


def test_missing_values_are_skipped_and_empty_input_is_empty():
    hourly = {
        "time": [0, 3600, 7200],
        "shortwave_radiation": [0.0, None, 100.0],
        "temperature_2m": [5.0, 6.0, None],
        "wind_speed_10m": [None, None, None],
        "precipitation": [None, None, None],
    }
    df = open_meteo_to_frame(hourly)
    assert list(df["tijd"]) == [3600]
    assert list(df["winds"]) == [0.0]
    assert open_meteo_to_frame({}).empty


def _minimal(**extra) -> dict:
    return {
        "prices": {
            "energy taxes consumption": {"2026-01-01": 0.0},
            "energy taxes production": {"2026-01-01": 0.0},
            "cost supplier consumption": {"2026-01-01": 0.0},
            "cost supplier production": {"2026-01-01": 0.0},
            "vat consumption": {"2026-01-01": 21},
            "vat production": {"2026-01-01": 21},
            "last invoice": "2026-01-01",
        },
        **extra,
    }


def test_open_meteo_needs_no_key():
    cfg = ConfigurationV0.model_validate(_minimal(**{"meteo source": "open-meteo"}))
    assert cfg.meteo_source == "open-meteo"
    assert cfg.meteoserver_key is None


def test_meteoserver_still_requires_its_key():
    with pytest.raises(ValueError, match="meteoserver-key is required"):
        ConfigurationV0.model_validate(_minimal())
