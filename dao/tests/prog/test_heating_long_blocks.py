"""Hermetic solver regression: hours must not become quarter-hour intervals."""
import itertools
import pytest
from test_scenarios import _solver_ready
from dao.prog.scenarios.loader import parse_scenario
from dao.prog.scenarios import runner

@pytest.mark.skipif(not _solver_ready(), reason="requires DAO_RUN_SCENARIOS=1 and mip")
@pytest.mark.parametrize("hours", [4, 6, 8])
def test_on_off_long_block(hours, monkeypatch):
    observed = []
    original = runner.run_case_checks
    def capture(expect, ctx):
        observed.extend(v for _, v in sorted(ctx.mv.items("hp_on")))
        return original(expect, ctx)
    monkeypatch.setattr(runner, "run_case_checks", capture)
    scenario = parse_scenario({
        "id": f"on-off-{hours}-hours", "description": "Long on/off heating block",
        "start": "2026-01-14 00:00",
        "prices": {"cons": [0.4] * 8 + [0.1] * 8 + [0.4] * 8},
        "temp": [10.0] * 24,
        "states": {"binary_sensor.heatpump_heating": "on"},
        "config_patch": {"heating.adjustment": "on/off",
                         "heating.min_run_length": hours,
                         "heating.degree_days_factor.value": 0.5},
        "expect": {"solved": True},
    }, source_file="long-block-test")
    result = runner.run_scenario(scenario)
    assert result.ok, result.failures
    assert observed, "The actual solver heating variables must be captured"
    runs = [len(list(g)) for on, g in itertools.groupby(v > 0.5 for v in observed) if on]
    assert runs == [hours * 4], runs
    assert all(v < 0.5 for v in observed[:32] + observed[64:])
