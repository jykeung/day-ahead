import datetime as dt
import pandas as pd
import pytest
from dao.prog.planning_horizon import align_weather_prices
from dao.prog.load_forecast import forecast_baseload


def test_late_weather_keeps_correct_prices_including_overnight_hours():
    times=pd.to_datetime(['2026-10-17 10:45','2026-10-17 11:00','2026-10-18 00:00','2026-10-18 01:00'])
    weather=pd.DataFrame({'tijd':times[1:],'temp':[12,8,7]})
    weather.index=weather['tijd']
    prices=pd.DataFrame({'time':times,'da_ex':[1,2,3,4],'da_cons':[2,3,4,5],'da_prod':[0,1,2,3]})
    result=align_weather_prices(weather,prices)
    assert result['da_ex'].tolist()==[2,3,4]
    assert result['tijd'].tolist()==list(times[1:])


def test_missing_weather_slot_does_not_shift_following_prices():
    times=pd.date_range('2026-10-17 12:00',periods=4,freq='15min')
    weather=pd.DataFrame({'tijd':times.delete(1)})
    prices=pd.DataFrame({'time':times,'da_ex':[1,2,3,4],'da_cons':[2,3,4,5],'da_prod':[0,1,2,3]})
    assert align_weather_prices(weather,prices)['da_ex'].tolist()==[1,3,4]


def test_mixed_load_grid_uses_full_hour_energy_after_published_prices():
    start=dt.datetime(2026,10,17,23,45,tzinfo=dt.timezone.utc)
    rows=[{'start':(start+dt.timedelta(minutes=15*i)).isoformat(),
           'end':(start+dt.timedelta(minutes=15*(i+1))).isoformat(),'power_kw':2}
          for i in range(5)]
    a={'generated_at':start.isoformat(),'schedule':rows}
    values,count=forecast_baseload(a,[start,start+dt.timedelta(minutes=15)],[900,3600],[.1,.1],None,start)
    assert values==[.5,2]
    assert count==2


def test_duplicate_prices_are_rejected():
    t=dt.datetime(2026,10,18)
    with pytest.raises(ValueError,match='Duplicate'):
        align_weather_prices(pd.DataFrame({'tijd':[t]}),pd.DataFrame({'time':[t,t],'da_ex':[1,2],'da_cons':[1,2],'da_prod':[1,2]}))
