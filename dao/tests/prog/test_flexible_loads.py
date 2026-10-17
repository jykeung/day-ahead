from datetime import datetime, timedelta, timezone
import pytest
from mip import Model, CBC, MINIMIZE, OptimizationStatus, xsum
from dao.prog.flexible_loads import add_flexible_loads, validate_payload

T = datetime(2026,10,19,10,tzinfo=timezone.utc)

def solve(devices, n=8, solar=None, prices=None, battery=False):
    m=Model(sense=MINIMIZE,solver_name=CBC);m.verbose=0
    starts=[T+timedelta(hours=i) for i in range(n)]
    energy,states=add_flexible_loads(m,starts,[1.]*n,devices)
    imports=[m.add_var(lb=0) for _ in starts]
    exports=[m.add_var(lb=0) for _ in starts]
    pv=solar or [0.]*n;prices=prices or [.3]*n
    b=[m.add_var(lb=0,ub=4 if battery else 0) for _ in range(n+1)]
    m+=b[0]==0;m+=b[-1]==0
    for i in range(n):
        m+=b[i+1]-b[i]<=2;m+=b[i]-b[i+1]<=2
        m+=imports[i]+pv[i]==exports[i]+xsum(v[i] for v in energy.values())+b[i+1]-b[i]
    m.objective=xsum(imports[i]*prices[i]-exports[i]*.01 for i in range(n))
    status=m.optimize()
    return m,status,energy,states,b

def car(return_hour=0):
    return dict(power_kw=3,capacity_kwh=40,initial_kwh=10,reserve_kwh=4,efficiency=.9,
      availability=[dict(start=(T+timedelta(hours=return_hour)).isoformat(),end=(T+timedelta(hours=8)).isoformat())],
      trips=[],targets=[dict(at=(T+timedelta(hours=8)).isoformat(),target_kwh=18)])

def test_car_uses_solar_with_battery_in_same_balance_and_early_return_saves():
    early=solve({'car':car(0)},solar=[4,4,4,0,0,0,0,0],battery=True)
    late=solve({'car':car(5)},solar=[4,4,4,0,0,0,0,0],battery=True)
    assert early[1]==late[1]==OptimizationStatus.OPTIMAL
    assert early[0].objective_value < late[0].objective_value
    assert early[3]['car'][-1].x==pytest.approx(18)
    assert all(v.x==pytest.approx(0) for v in late[2]['car'][:5])

def test_commute_withdrawal_reserve_and_full_trip():
    spec=car();spec['initial_kwh']=20
    spec['trips']=[dict(departure=(T+timedelta(hours=2)).isoformat(),energy_kwh=40*82/270)]
    spec['availability']=[dict(start=T.isoformat(),end=(T+timedelta(hours=2)).isoformat()),
                         dict(start=(T+timedelta(hours=5)).isoformat(),end=(T+timedelta(hours=20)).isoformat())]
    spec['targets']=[dict(at=(T+timedelta(hours=20)).isoformat(),target_kwh=40)]
    m,status,e,s,b=solve({'car':spec},n=20)
    assert status==OptimizationStatus.OPTIMAL
    assert s['car'][2].x>=4+40*82/270-1e-6
    assert s['car'][-1].x==pytest.approx(40)
    assert all(v.x==0 for v in e['car'][2:5])

def water():
    return dict(power_kw=2,minimum_c=40,maximum_c=55,initial_c=50,volume_l=200,cop=3,
                cooling_c_per_h=.1,draws=[])

def test_tank_can_skip_two_days():
    spec=water();spec['cooling_c_per_h']=.05
    m,status,e,s,b=solve({'hot_water':spec},n=48)
    assert status==OptimizationStatus.OPTIMAL
    assert sum(v.x for v in e['hot_water'])==pytest.approx(0)

def test_shower_is_supplied_before_event_not_after():
    spec=water();spec['initial_c']=42
    spec['draws']=[dict(at=(T+timedelta(hours=4)).isoformat(),thermal_kwh=1)]
    m,status,e,s,b=solve({'hot_water':spec},solar=[0,3,0,0,0,0,0,0])
    assert status==OptimizationStatus.OPTIMAL
    assert sum(v.x for v in e['hot_water'][:4])>0
    assert s['hot_water'][4].x - 1/(200*4.186/3600)>=40-1e-6

def test_humidity_max_and_stop_without_daily_runtime():
    spec=dict(power_kw=.2,maximum_percent=60,stop_percent=50,initial_percent=55,
              rise_percent_per_h=1,removal_percent_per_h=4)
    m,status,e,s,b=solve({'dehumidifier':spec},n=12,solar=[.2]*3+[0]*9)
    assert status==OptimizationStatus.OPTIMAL
    assert max(v.x for v in s['dehumidifier'])<=60+1e-6
    assert min(v.x for v in s['dehumidifier'])>=50-1e-6
    assert 0<sum(v.x for v in e['dehumidifier'])<12*.2

def test_stale_or_incomplete_requirements_rejected():
    with pytest.raises(ValueError,match='stale'):
        validate_payload(dict(generated_at=(T-timedelta(hours=1)).isoformat(),devices={}),[],T)
    with pytest.raises(ValueError,match='match'):
        validate_payload(dict(generated_at=T.isoformat(),devices={}),['car'],T)


def test_shadow_config_requires_separate_plan_and_exact_forecast_components():
    from dao.prog.config.versions.v2 import ConfigurationV2
    config={'meteo source':'open-meteo','entity load forecast':'sensor.dao_load_forecast',
            'entity flexible requirements':'sensor.dao_appliance_requirements',
            'flexible components':['car'],'load forecast excludes':['car'],
            'entity plan':'sensor.dao_appliance_shadow_plan'}
    assert ConfigurationV2.model_validate(config).flexible_components==['car']
    for overrides in [{'entity plan':'sensor.dao_plan'}, {'load forecast excludes':[]},
                      {'entity flexible requirements':None}, {'flexible components':['unknown']},
                      {'entity load forecast':None}]:
        with pytest.raises(ValueError):ConfigurationV2.model_validate({**config,**overrides})
