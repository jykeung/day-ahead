# Native-device planning with a total-house forecast

Preparation branch; HOAS live add-on/options are unchanged.

A total-house forecast already includes heating, hot water and car charging.
When a native model replaces one of these schedules, declare its component in
`load forecast excludes`. The declared components must match the native models
exactly: `space_heating` for heating, `hot_water` for a boiler and `car` for EVs.
A native machine supplies its own `forecast component`. A component can be
optimized only once, and exclusions without the corresponding native model
are rejected.

The reader requires a finite non-negative value for each excluded component in
every forecast row. It subtracts those values before integrating the remaining
baseline into each optimizer interval. Missing components, negative/invalid
values and sums above the total fail validation; rounding noise up to 0.1 W is
clamped. Forecast-only existing configurations keep their previous behavior.

Each published plan row now includes `devices: {component: average_kW}` for
configured native loads. `optimized_devices` lists the available keys. Machine
profiles without a forecast component (when no total forecast is configured)
use `machine:<name>`. Existing aggregate plan fields remain unchanged.

This does not add room-temperature thermal dynamics to the degree-day heating
model, infer a tank volume, choose EV energy/departure requirements, or enable
an HA device-control adapter. Configure and review shadow schedules first.

## Joint bounded appliance models (shadow only)

Configure `entity flexible requirements: sensor.dao_appliance_requirements`,
`flexible components: [car, hot_water]`, matching `load forecast excludes`, and
`entity plan: sensor.dao_appliance_shadow_plan`. Do not also enable native EV or
boiler models for those components. The requirements entity must be fresh
(10 minutes) with a `devices` mapping; missing requested components aborts.
The total forecast must cover every interval and contain the excluded components.

`flexible_loads.py` adds consumption directly to DAO's existing grid/battery/PV
balance and capacity tariff objective. Car energy is bounded by capacity and
arrival reserve, withdrawn at departures, and charged only during explicit
availability. Dated targets implement full-for-trip. Hot water has min/max
state constraints, continuous standing loss and timed thermal withdrawals for
showers. Humidity has a maximum, lower stop threshold and rise/removal model.
There is no daily minimum runtime/reheat. These are simple lumped models;
calibration and real actuator adapters remain prerequisites for live use.
Initial tank/humidity outside configured bounds is rejected; existing device
controls retain responsibility until a recovery policy is added.

Flexible runs return after publishing the shadow plan, before device/battery
commands, and do not replace normal report forecasts. `shadow_only` marks the
export and `device_states` exposes predicted tank temperature, humidity and car
kWh. The planner horizon is the weather/price horizon, not a guaranteed full
week. Weekly commuting feeds rolling dated trips; unknown trip consumption or
availability beyond the forecast must be updated in subsequent runs.

Run `scripts/compare_flexible_return.py` with a dedicated shadow options file
from `dao/prog` (repository root in PYTHONPATH). It solves normal and earlier
return with a common start time and the same DAO battery/grid objective. It
publishes differences in objective cost, grid cost, imports and exports on
`sensor.dao_early_return_comparison`. Avoided export is not claimed to be solar
energy uniquely traced into the car. Estimated prices are identified. A
comparison never changes the committed arrival or live options.
