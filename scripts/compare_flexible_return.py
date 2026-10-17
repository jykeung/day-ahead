"""Run normal/early availability through the same DAO optimizer, shadow-only.

Run from dao/prog with PYTHONPATH pointing at repository root:
  python ../../scripts/compare_flexible_return.py /path/shadow-options.json
The options must configure flexible components, forecast exclusions, and a
separate shadow entity plan. Never pass the live battery-only options.
"""
import datetime as dt
from types import SimpleNamespace
import json
import sys
from dao.prog.day_ahead import DaCalc


def compare(path):
    normal=DaCalc(path)
    if normal.config is None or 'car' not in normal.config.flexible_components:
        raise ValueError('A validated joint shadow config including car is required')
    # Use validated config copies, rather than editing live add-on options.
    alternative=DaCalc(path)
    alternative.config=type(normal.config).model_validate({
        **normal.config.model_dump(by_alias=True),
        'entity flexible requirements':'sensor.dao_early_return_requirements',
        'entity plan':'sensor.dao_early_return_plan',
    })
    # Freeze HA inputs across both solves; only car availability may differ.
    original_get_state=normal.get_state
    cache={}
    def read(entity):
        if entity not in cache:
            cache[entity]=original_get_state(entity)
        return cache[entity]
    normal.get_state=read
    alternative.get_state=read
    normal_entity=normal.config.entity_flexible_requirements
    early_entity=alternative.config.entity_flexible_requirements
    current=read(normal_entity)
    proposed=read(early_entity)
    if 'car' not in proposed.attributes.get('devices', {}):
        raise ValueError('No valid earlier return to compare')
    # Both publisher sensors may have updated a minute apart. Keep every
    # baseline requirement and substitute only the hypothetical availability.
    attrs={**current.attributes,'devices':dict(current.attributes['devices'])}
    attrs['devices']['car']={**attrs['devices']['car'],
        'availability':proposed.attributes['devices']['car']['availability']}
    cache[early_entity]=SimpleNamespace(state=proposed.state,attributes=attrs)
    anchor=dt.datetime.now()
    baseline=normal.calc_optimum(planning_time=anchor)
    early=alternative.calc_optimum(planning_time=anchor)
    if not baseline or not early:
        raise ValueError('Both scenarios must solve before a comparison is published')
    result=dict(generated_at=dt.datetime.now(dt.timezone.utc).isoformat(),shadow_only=True,
                estimated_saving_eur=baseline['objective_eur']-early['objective_eur'],
                grid_cost_difference_eur=baseline['grid_cost_eur']-early['grid_cost_eur'],
                avoided_export_kwh=baseline['export_kwh']-early['export_kwh'],
                import_reduction_kwh=baseline['import_kwh']-early['import_kwh'],
                includes_estimated_prices=bool(baseline['estimated_price_intervals'] or early['estimated_price_intervals']),
                note='Same battery/grid objective and forecast horizon; earlier arrival remains hypothetical.')
    normal.set_state('sensor.dao_early_return_comparison',state=result['generated_at'],attributes=result)
    return result


if __name__=='__main__':
    print(json.dumps(compare(sys.argv[1]),indent=2))
