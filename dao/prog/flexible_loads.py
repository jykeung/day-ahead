"""Shadow appliance constraints in DAO's existing battery/grid optimization.

Inputs are explicit requirements, not actuator commands. All energy variables
are AC kWh per interval; timestamps are absolute and timezone aware.
"""
from datetime import datetime, timedelta, timezone
from math import isfinite
from zoneinfo import ZoneInfo
from mip import BINARY, xsum


def number(data, key, low=0, high=float('inf')):
    value = float(data[key])
    if not isfinite(value) or not low <= value <= high:
        raise ValueError(f'Invalid {key}')
    return value


def instant(value):
    value = datetime.fromisoformat(value) if isinstance(value, str) else value
    if value.tzinfo is None:
        raise ValueError('Requirements timestamps must include timezone')
    return value.astimezone(timezone.utc)


def validate_payload(attributes, components, now):
    age = (instant(now) - instant(attributes['generated_at'])).total_seconds()
    if not 0 <= age <= 600:
        raise ValueError('Appliance requirements stale')
    devices = attributes['devices']
    if not set(components) <= set(devices):
        raise ValueError('Requirements must match configured flexible components')
    return {key: devices[key] for key in components}


def add_flexible_loads(model, starts, hours, devices, time_zone='Europe/Brussels'):
    """Return consumption/state variables; caller includes consumption in balance.

    Withdrawal/departure deadlines inside a slot are conservatively enforced at
    its start. Charging is allowed only for slots entirely inside availability.
    No daily reheating or fixed dehumidifier runtime is required.
    """
    starts = [instant(t.replace(tzinfo=ZoneInfo(time_zone)) if t.tzinfo is None else t) for t in starts]
    if not starts or len(starts) != len(hours) or any(not isfinite(h) or h <= 0 for h in hours):
        raise ValueError('Invalid optimizer intervals')
    ends = [s + timedelta(hours=h) for s, h in zip(starts, hours)]
    if any(ends[i] != starts[i+1] for i in range(len(starts)-1)):
        raise ValueError('Non-contiguous optimizer intervals')
    n = len(starts)
    consumption, states = {}, {}
    for key, spec in devices.items():
        if key not in {'car', 'hot_water', 'dehumidifier'}:
            raise ValueError('Unsupported flexible component: ' + key)
        power = number(spec, 'power_kw', .001, 50)
        on = [model.add_var(name=f'flex_{key}_on_{i}', var_type=BINARY) for i in range(n)]
        energy = [model.add_var(name=f'flex_{key}_kwh_{i}', lb=0, ub=power*h) for i,h in enumerate(hours)]
        consumption[key] = energy
        for i,h in enumerate(hours):
            # Humidity model uses fixed-speed operation; EV charging and tank
            # thermostat may finish inside an interval.
            if key == "dehumidifier":
                model += energy[i] == on[i]*power*h
            else:
                model += energy[i] <= on[i]*power*h
        if key == 'car':
            capacity = number(spec, 'capacity_kwh', .001, 200)
            initial = number(spec, 'initial_kwh', 0, capacity)
            reserve = number(spec, 'reserve_kwh', 0, capacity)
            efficiency = number(spec, 'efficiency', .01, 1)
            available = [(instant(a['start']), instant(a['end'])) for a in spec['availability']]
            if any(b <= a for a,b in available):
                raise ValueError('Invalid car availability')
            levels = [model.add_var(name=f'flex_car_energy_{i}', lb=0, ub=capacity) for i in range(n+1)]
            model += levels[0] == initial
            trips = [(instant(t['departure']), number(t,'energy_kwh',0,capacity)) for t in spec.get('trips',[])]
            deadlines = [(instant(t['at']),number(t,'target_kwh',0,capacity)) for t in spec.get('targets',[])]
            for i,(start,end) in enumerate(zip(starts,ends)):
                if not any(a <= start and end <= b for a,b in available):
                    model += energy[i] == 0
                withdrawal = sum(kwh for at,kwh in trips if start <= at < end)
                if withdrawal:
                    model += levels[i] >= withdrawal + reserve
                for at,target in deadlines:
                    if start <= at < end or (i == n-1 and at == end):
                        model += (levels[i+1] if at == end else levels[i]) >= target
                model += levels[i+1] == levels[i] + energy[i]*efficiency - withdrawal
                # An initially low charge may recover; no fictional immediate SOC jump.
                model += levels[i+1] >= min(reserve, initial)
            states[key] = levels
        elif key == 'hot_water':
            minimum = number(spec,'minimum_c',1,90)
            maximum = number(spec,'maximum_c',minimum+.1,90)
            initial = number(spec,'initial_c',minimum,maximum)
            volume = number(spec,'volume_l',1,2000)
            cop = number(spec,'cop',.1,10)
            cooling = number(spec,'cooling_c_per_h',0,10)
            heat_capacity = volume*4.186/3600  # kWh/K, stored water only
            levels = [model.add_var(name=f'flex_water_c_{i}',lb=minimum,ub=maximum) for i in range(n+1)]
            model += levels[0] == initial
            draws = [(instant(d['at']), number(d,'thermal_kwh',0,100)) for d in spec.get('draws',[])]
            for i,(start,end) in enumerate(zip(starts,ends)):
                draw_c = sum(kwh for at,kwh in draws if start <= at < end)/heat_capacity
                # Shower happens before heat supplied in that interval.
                model += levels[i] - draw_c >= minimum
                model += levels[i+1] == levels[i] + energy[i]*cop/heat_capacity - cooling*hours[i] - draw_c
            states[key] = levels
        else:
            maximum = number(spec,'maximum_percent',1,100)
            target = number(spec,'stop_percent',0,maximum-.1)
            initial = number(spec,'initial_percent',0,maximum)
            rise = number(spec,'rise_percent_per_h',0,50)
            removal = number(spec,'removal_percent_per_h',.001,100)
            levels = [model.add_var(name=f'flex_humidity_{i}',lb=min(initial,target),ub=maximum) for i in range(n+1)]
            model += levels[0] == initial
            for i in range(n):
                # Do not start/restart below the stop threshold. Forecast can
                # pre-dry above it before a later expensive period.
                model += levels[i] >= target - 100*(1-on[i])
                model += levels[i+1] == levels[i] + rise*hours[i] - removal*hours[i]*on[i]
            states[key] = levels
    return consumption, states
