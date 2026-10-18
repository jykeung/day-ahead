import datetime as dt

from dao.prog.soc_floor import floor_at, in_window, parse_hhmm

EVENING = (parse_hhmm("17:30"), parse_hhmm("21:00"), 20.0)


def at(hhmm: str) -> dt.datetime:
    h, m = map(int, hhmm.split(":"))
    return dt.datetime(2026, 10, 18, h, m)


def test_parse_accepts_end_of_day_and_seconds():
    assert parse_hhmm("07:05") == dt.time(7, 5)
    assert parse_hhmm("18:00:00") == dt.time(18, 0)
    assert parse_hhmm("24:00") == dt.time.max


def test_window_is_half_open():
    start, end, _ = EVENING
    assert not in_window(at("17:15"), start, end)
    assert in_window(at("17:30"), start, end)
    assert in_window(at("20:45"), start, end)
    assert not in_window(at("21:00"), start, end)


def test_window_wraps_midnight():
    start, end = parse_hhmm("22:00"), parse_hhmm("06:00")
    assert in_window(at("23:30"), start, end)
    assert in_window(at("03:00"), start, end)
    assert not in_window(at("06:00"), start, end)
    assert not in_window(at("12:00"), start, end)


def test_floor_takes_highest_covering_limit():
    windows = [EVENING, (parse_hhmm("19:00"), parse_hhmm("20:00"), 30.0)]
    assert floor_at(at("12:00"), 15, windows) == 15
    assert floor_at(at("18:00"), 15, windows) == 20
    assert floor_at(at("19:30"), 15, windows) == 30


def test_window_never_lowers_the_base_limit():
    assert floor_at(at("18:00"), 25, [EVENING]) == 25


def test_window_config_takes_clock_times_or_entities():
    import pytest
    from dao.prog.config.models.devices.battery import SocFloorWindow

    w = SocFloorWindow.model_validate({"from": "input_datetime.floor_start", "to": "21:00", "limit": 20})
    assert w.start.resolve(lambda eid: "18:30:00") == "18:30:00"
    assert w.end.resolve(lambda eid: None) == "21:00"
    with pytest.raises(ValueError):
        SocFloorWindow.model_validate({"from": "6pm", "to": "21:00", "limit": 20})
