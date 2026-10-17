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


def test_native_component_is_replaced_not_added_twice():
    a=attrs()
    for row in a['schedule']:
        row['space_heating']=.5
        row['car']=1.0
    value,count=forecast_baseload(a,[START],900,[.1],'Europe/Brussels',NOW,
                                  excluded_components=['space_heating','car'])
    assert count==1 and value==[.125]


@pytest.mark.parametrize('value', [-1, float('nan'), float('inf'), 3])
def test_invalid_or_excess_native_components_are_rejected(value):
    a=attrs();a['schedule'][0]['car']=value
    with pytest.raises(ValueError):
        forecast_baseload(a,[START],900,[.1],'Europe/Brussels',NOW,excluded_components=['car'])


def test_missing_native_component_is_rejected():
    with pytest.raises(KeyError):
        forecast_baseload(attrs(),[START],900,[.1],'Europe/Brussels',NOW,excluded_components=['car'])


def test_native_exclusions_must_match_enabled_models_exactly():
    from dao.prog.config.versions.v2 import ConfigurationV2
    config={'meteo source':'open-meteo','entity load forecast':'sensor.dao_load_forecast',
            'heating':{'heater present':True,'adjustment':'on/off'}}
    result=ConfigurationV2.model_validate({**config,'load forecast excludes':['space_heating']})
    assert result.load_forecast_excludes==['space_heating']
    for excluded in [[],['car'],['space_heating','car'],['space_heating','space_heating']]:
        with pytest.raises(ValueError):ConfigurationV2.model_validate({**config,'load forecast excludes':excluded})
    with pytest.raises(ValueError):ConfigurationV2.model_validate({'meteo source':'open-meteo','load forecast excludes':['car']})


def test_native_machine_components_are_explicit_and_unique():
    from dao.prog.config.versions.v2 import ConfigurationV2
    machine={'name':'Dehumidifier','programs':[{'name':'off','power':[0]}],
             'entity start window':'input_datetime.test_start','entity end window':'input_datetime.test_end',
             'entity selected program':'input_select.test_program',
             'entity calculated start':'input_datetime.test_calculated_start',
             'entity calculated end':'input_datetime.test_calculated_end'}
    base={'meteo source':'open-meteo','entity load forecast':'sensor.dao_load_forecast','machines':[machine]}
    with pytest.raises(ValueError,match='forecast component'):ConfigurationV2.model_validate(base)
    defined={**machine,'forecast component':'dehumidifier'}
    result=ConfigurationV2.model_validate({**base,'machines':[defined],'load forecast excludes':['dehumidifier']})
    assert result.machines[0].forecast_component=='dehumidifier'
    with pytest.raises(ValueError,match='multiple native models'):
        ConfigurationV2.model_validate({**base,'machines':[defined,{**defined,'name':'Second'}],
                                        'load forecast excludes':['dehumidifier']})
