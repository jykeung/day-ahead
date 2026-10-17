import datetime as dt
import pytest
from dao.prog.load_forecast import forecast_baseload

NOW = dt.datetime(2026,10,17,8,5,tzinfo=dt.timezone.utc)
START = dt.datetime(2026,10,17,10,0)


def attrs(**updates):
    value = {'generated_at': NOW.isoformat(), 'schedule': [
        {'start':'2026-10-17T10:00:00+02:00','end':'2026-10-17T10:15:00+02:00','power_kw':2},
        {'start':'2026-10-17T10:15:00+02:00','end':'2026-10-17T10:30:00+02:00','power_kw':4}]}
    value.update(updates)
    return value


def test_replaces_total_load_and_keeps_missing_intervals():
    times = [START+dt.timedelta(minutes=15*i) for i in range(3)]
    values, count = forecast_baseload(attrs(), times, 900, [.1]*3, 'Europe/Brussels', NOW)
    assert values == [.5,1,.1]
    assert count == 2
    # Partial first slot is scaled by the optimizer later, not by the reader.
    assert values[0] * (10/15) == pytest.approx(2*10/60)


def test_hourly_grid_integrates_quarters_and_requires_full_coverage():
    a=attrs();a['schedule'] += [
        {'start':'2026-10-17T10:30:00+02:00','end':'2026-10-17T11:00:00+02:00','power_kw':1}]
    assert forecast_baseload(a,[START],3600,[.1],'Europe/Brussels',NOW)==([2.0],1)
    assert forecast_baseload(attrs(),[START],3600,[.1],'Europe/Brussels',NOW)==([.1],0)


@pytest.mark.parametrize('age', [1801,-1])
def test_stale_and_future_forecasts_rejected(age):
    a=attrs(generated_at=(NOW-dt.timedelta(seconds=age)).isoformat())
    with pytest.raises(ValueError):
        forecast_baseload(a,[START],900,[.1],'Europe/Brussels',NOW)


@pytest.mark.parametrize('power', [-1,float('nan'),float('inf')])
def test_invalid_power_rejected(power):
    a=attrs();a['schedule'][0]['power_kw']=power
    with pytest.raises(ValueError):
        forecast_baseload(a,[START],900,[.1],'Europe/Brussels',NOW)


def test_overlapping_periods_rejected_instead_of_double_counted():
    a=attrs();a['schedule'].append(dict(a['schedule'][0]))
    with pytest.raises(ValueError):
        forecast_baseload(a,[START],900,[.1],'Europe/Brussels',NOW)


def test_total_load_source_cannot_double_count_native_appliances():
    from dao.prog.config.versions.v2 import ConfigurationV2
    config={'meteo source':'open-meteo','entity load forecast':'sensor.dao_load_forecast'}
    assert ConfigurationV2.model_validate(config).entity_load_forecast=='sensor.dao_load_forecast'
    with pytest.raises(ValueError,match='already includes appliances'):
        ConfigurationV2.model_validate({**config,'heating':{'heater present':True,'adjustment':'on/off'}})
