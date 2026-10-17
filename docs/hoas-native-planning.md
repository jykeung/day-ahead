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
