import os
import datetime as dt
import tempfile
import pytest
from pathlib import Path
import pandas as pd
from dao.prog.scenarios.loader import parse_scenario
from dao.prog.scenarios.build_snapshot import build_config,build_snapshot
from dao.prog import da_debug
from unittest.mock import patch

pytestmark = pytest.mark.skipif(not os.environ.get("DAO_RUN_SCENARIOS"), reason="set DAO_RUN_SCENARIOS=1 to solve optimizer integration")


def test_full_optimizer_carries_hourly_demand_beyond_midnight():
    s=parse_scenario({'id':'extended-horizon','description':'overnight load coverage','start':'2026-10-17 16:00','prices':{'cons':[.3]*32,'prod':[.1]*32},'config_patch':{'solar':[],'battery':[],'electric vehicle':[],'machines':[],'heating':{'heater present':False},'boiler':{'boiler present':False},'use_calc_baseload':False,'baseload':[1]*24,'entity plan':'sensor.test_plan','prices.prediction.extension':24},'expect':{'solved':True}},source_file='unit')
    cfg=build_config(s);snap=build_snapshot(s,config=cfg)
    da_debug._ensure_day_ahead_importable()
    from dao.prog.da_report import Report
    from dao.prog.day_ahead import DaCalc
    from dao.prog.plan_export import build_plan_rows
    fixed_times=pd.date_range('2026-10-17 16:00',periods=32,freq='15min')
    future_times=pd.date_range('2026-10-18 00:00',periods=24,freq='h')
    def prices(instance,start,end=None,interval='1hour',extension=0):
     times=fixed_times if not extension else future_times
     return pd.DataFrame({'time':times,'da_ex':.2,'da_cons':.3,'da_prod':.1,'datasoort':'expected'})
    def weather(instance,start=None,end=None,interval='1hour'):
     times=fixed_times if interval=='15min' else future_times
     return pd.DataFrame({'time':[int(t.timestamp()) for t in times],'tijd':times,'temp':8.,'glob_rad':0.})
    collected=[]
    def export(*args,**kwargs):
     rows=build_plan_rows(*args,**kwargs);collected.extend(rows);return rows
    with da_debug.ReplayIO(snap,solver_threads=1,png=False) as replay:
     replay._patches.set(Report,'get_price_data',prices)
     replay._patches.set(da_debug._FakeDbManager,'get_prognose_data',weather)
     with patch('dao.prog.plan_export.build_plan_rows',export):
      calc=DaCalc(str(Path(tempfile.mkdtemp())/'options.json'))
      calc.calc_optimum(_start_dt=dt.datetime(2026,10,17,16))
    assert len(collected)==56,len(collected)
    assert collected[-1]['t'].startswith('2026-10-18T23:00'),collected[-1]
    assert all(abs(r['load']-1)<.001 for r in collected),[(r['t'],r['load']) for r in collected]
    print('Verified 32 quarter-hours + 24 overnight/daytime hours, all at 1 kW house load')
