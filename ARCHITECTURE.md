# Architecture

## Approach: OR-Tools CP-SAT

**Choice:** Google OR-Tools **CP-SAT** constraint solver.

**Why it fits:**

| Requirement | How CP-SAT helps |
|-------------|------------------|
| Hard rules (1 charger, 25 min charge, no range violation) | Native interval variables + linear constraints |
| Soft rules (wait, operator, makespan) | Weighted linear objective |
| Scales to more buses/stations | Cumulative constraints generalize to N chargers |
| Adding rules | New constraints or objective terms — no engine rewrite |
| Defensible in interview | Industry-standard for resource scheduling |

The problem decomposes into two phases:

1. **Plan selection** (`planner.py` + `assign_charging_plans`) — which stations each bus visits, respecting the 240 km range rule and route order.
2. **Queue scheduling** (`scheduler.py`) — when each bus starts charging at each station, respecting single-charger capacity and minimizing weighted wait/makespan/operator spread.

Range feasibility is validated **before** scheduling; queue timing is optimized ** jointly** across all buses with CP-SAT.

```
Scenario YAML ──► Loader ──► Planner (valid plans)
                                │
                                ▼
                         Plan assignment (load balance)
                                │
                                ▼
                         CP-SAT scheduler ──► ScheduleResult ──► Streamlit UI
                                ▲
                         Rules / Weights
```

---

## Data structure design

### Philosophy

> **A scenario IS the data structure.**

Everything the scheduler needs to run lives in YAML files under `data/`. Code reads generic structures; it never hardcodes "4 stations" or "20 buses."

### `data/route.yaml` — world definition

| Field | Purpose |
|-------|---------|
| `segments[]` | Ordered legs with distances — drives travel time |
| `stations[]` | Charging stops with `km_from_bengaluru`, `chargers` count |
| `battery.range_km` | Hard range limit |
| `battery.charge_duration_min` | Fixed charge duration |
| `weights` | Defaults for new scenarios |

### `data/scenarios/*.yaml` — runnable scenarios

| Field | Purpose |
|-------|---------|
| `id`, `name`, `description` | UI + identification |
| `route_id` | Links to route (future: multiple routes) |
| `weights` | Per-scenario soft-rule overrides |
| `buses[]` | `{ id, operator, direction, departure }` |

### Output — `ScheduleResult` (in memory)

| Field | Purpose |
|-------|---------|
| `bus_timelines[]` | Per-bus: stations used, events, waits, final arrival |
| `station_queues{}` | Per-station ordered charging list |
| `plan_assignments{}` | Which plan was chosen per bus |

---

## Anticipated future changes

Each row: **change → how the design handles it without code changes** (or minimal change).

| Future change | Data-only? | How |
|---------------|------------|-----|
| New station E mid-route | ✅ | Add to `route.yaml` `segments` + `stations`; planner auto-enumerates new valid plans |
| Double chargers at station B | ✅ | Set `chargers: 2` on station B in `route.yaml`; cumulative constraint already uses this field |
| New operator "Redbus" | ✅ | Use new `operator` string in scenario bus entries |
| New route Chennai↔Mumbai | ✅ | New `route.yaml` + scenarios with `route_id` pointing to it |
| 50 buses instead of 20 | ✅ | Add rows to scenario YAML |
| Different battery range / charge time | ✅ | Edit `battery` block in route YAML |
| Scenario-specific weights | ✅ | Already supported in scenario `weights` block |
| Priority bus (hard rule) | ⚠️ small code | Add constraint in `scheduler.py`: `start[priority] <= start[other]` when both at same station |
| Time-of-day electricity cost | ⚠️ small code | New `SoftRule` + weight key in YAML |
| Multiple routes sharing a station | ✅ | Station ids are global in route file; cross-route scheduling would merge events at shared station id |
| Driver shift max hours | ⚠️ small code | Hard constraint on `bus_finish - departure <= max_shift` |
| Partial charging (80% top-up) | ❌ code | Would extend `ChargingEvent` with SOC fields — model change, but planner/scheduler interfaces stay |
| Dynamic speed / traffic | ⚠️ small code | Replace fixed `travel_minutes_between` with time-varying lookup table in route data |
| 6th scenario for live interview | ✅ | Drop new YAML in `data/scenarios/` |

**Design goal:** anything that describes *the world* is YAML; anything that describes *policy* is a rule + weight; only truly new physics needs code.

---

## Soft rules

Defined in `src/rules.py` as pluggable `SoftRule` classes:

| Rule | Weight key | Measures |
|------|------------|----------|
| `IndividualWaitRule` | `individual` | Sum of all bus wait times |
| `OperatorSpreadRule` | `operator` | Sum of (latest − earliest finish) per operator |
| `OverallMakespanRule` | `overall` | Last bus arrival time |

Changing weights in scenario YAML visibly shifts schedules — especially Scenario 4 where `operator: 2.0` clusters same-operator buses to reduce fleet spread.

---

## Hard rules (enforced in code)

1. **Range** — only valid station subsets from `enumerate_valid_plans()` are assigned.
2. **Route order** — plans are monotonic subsets of ordered station list per direction.
3. **One charger** — `AddCumulative` with capacity = `station.chargers`.
4. **Charge duration** — fixed 25-minute intervals.
5. **No charging before arrival** — `start >= arrival`.

---

## Assumptions

1. **Speed:** 60 km/h constant → 100 km = 100 minutes (per spec example).
2. **Clock:** Minutes from midnight; display uses 24h+ for post-midnight arrivals.
3. **Endpoints:** Buses leave origin with full 240 km range; endpoint chargers are not scheduled.
4. **Minimum charges:** 540 km route requires ≥ 2 mid-route charges; planner prefers minimum-stop plans.
5. **Plan assignment:** Greedy load-balancing among equal-length plans before CP-SAT; operator-heavy scenarios group fleets on shared plan templates when `operator` weight ≥ 1.5.
6. **Solver timeout:** 30 s max; worst-case scenarios may return FEASIBLE rather than OPTIMAL — still valid.

---

## What I'd improve with more time

- Joint CP-SAT optimization of **plan choice + queue order** (optional interval variables per station).
- Interactive weight sliders in the UI for live experimentation.
- Unit tests for planner range validation and small scheduling fixtures.
- Gantt-style timeline visualization per station.
