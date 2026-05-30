"""CP-SAT scheduling engine with extensible plan assignment."""

from __future__ import annotations

from collections import defaultdict

from ortools.sat.python import cp_model

from src.models import (
    BusInput,
    BusTimeline,
    ChargingEvent,
    Direction,
    Route,
    Scenario,
    ScheduleResult,
    StationQueueEntry,
)
from src.planner import (
    _stop_chain,
    enumerate_valid_plans,
    is_valid_plan,
    travel_minutes_between,
)
from src.rules import ObjectiveContext, weighted_score


HORIZON = 4000  # minutes — generous upper bound for schedule window


def assign_charging_plans(scenario: Scenario) -> dict[str, list[str]]:
    """Pick a valid charging plan per bus, balancing station load."""
    route = scenario.route
    plans_by_dir = {
        Direction.BK: enumerate_valid_plans(route, Direction.BK),
        Direction.KB: enumerate_valid_plans(route, Direction.KB),
    }

    # Minimal-stop plans first (typically 2 charges for 540 km route).
    min_len = min(len(p) for plans in plans_by_dir.values() for p in plans)
    candidates_by_dir = {
        d: [p for p in plans_by_dir[d] if len(p) == min_len] or plans_by_dir[d]
        for d in plans_by_dir
    }

    station_load: dict[str, int] = defaultdict(int)
    assignments: dict[str, list[str]] = {}

    # Group buses by direction; when operator weight is high, keep fleet on same plan variant.
    op_weight = scenario.weights.operator
    buses_by_dir: dict[Direction, list[BusInput]] = defaultdict(list)
    for bus in scenario.buses:
        buses_by_dir[bus.direction].append(bus)

    for direction, buses in buses_by_dir.items():
        candidates = candidates_by_dir[direction]
        if not candidates:
            raise RuntimeError(f"No valid charging plans for direction {direction}")

        if op_weight >= 1.5:
            # Operator-heavy: assign all buses of same operator to the same plan template.
            by_operator: dict[str, list[BusInput]] = defaultdict(list)
            for b in buses:
                by_operator[b.operator].append(b)
            for op_buses in by_operator.values():
                _assign_group(op_buses, candidates, station_load, assignments)
        else:
            _assign_group(sorted(buses, key=lambda b: b.departure_min), candidates, station_load, assignments)

    return assignments


def _assign_group(
    buses: list[BusInput],
    candidates: list[list[str]],
    station_load: dict[str, int],
    assignments: dict[str, list[str]],
) -> None:
    """Greedy load-balancing across candidate plan shapes."""
    for i, bus in enumerate(buses):
        best_plan = candidates[i % len(candidates)]
        best_score = None
        for plan in candidates:
            score = sum(station_load[s] for s in plan)
            if best_score is None or score < best_score:
                best_score = score
                best_plan = plan
        assignments[bus.id] = list(best_plan)
        for s in best_plan:
            station_load[s] += 1


def schedule_scenario(scenario: Scenario) -> ScheduleResult:
    route = scenario.route
    plan_assignments = assign_charging_plans(scenario)
    for bus in scenario.buses:
        plan = plan_assignments[bus.id]
        if not is_valid_plan(route, bus.direction, plan):
            raise ValueError(f"Invalid plan {plan} assigned to {bus.id}")

    model = cp_model.CpModel()
    charge_dur = route.charge_duration_min

    # Per-bus charging event keys in route order.
    events: list[tuple[str, str, BusInput, str]] = []
    for bus in scenario.buses:
        for station_id in plan_assignments[bus.id]:
            events.append((bus.id, station_id, bus, station_id))

    # Decision variables
    arrival: dict[tuple[str, str], cp_model.IntVar] = {}
    start: dict[tuple[str, str], cp_model.IntVar] = {}
    end: dict[tuple[str, str], cp_model.IntVar] = {}
    wait: dict[tuple[str, str], cp_model.IntVar] = {}

    bus_finish: dict[str, cp_model.IntVar] = {}

    for bus in scenario.buses:
        chain = _stop_chain(route, bus.direction)
        origin = chain[0]
        destination = chain[-1]
        plan = plan_assignments[bus.id]

        prev_end = None
        prev_stop = origin

        for station_id in plan:
            key = (bus.id, station_id)
            travel = travel_minutes_between(route, bus.direction, prev_stop, station_id)

            arr = model.NewIntVar(0, HORIZON, f"arr_{bus.id}_{station_id}")
            st = model.NewIntVar(0, HORIZON, f"start_{bus.id}_{station_id}")
            en = model.NewIntVar(0, HORIZON, f"end_{bus.id}_{station_id}")
            w = model.NewIntVar(0, HORIZON, f"wait_{bus.id}_{station_id}")

            arrival[key] = arr
            start[key] = st
            end[key] = en
            wait[key] = w

            if prev_end is None:
                model.Add(arr == bus.departure_min + travel)
            else:
                model.Add(arr == prev_end + travel)

            model.Add(st >= arr)
            model.Add(w == st - arr)
            model.Add(en == st + charge_dur)

            prev_end = en
            prev_stop = station_id

        final_travel = travel_minutes_between(route, bus.direction, plan[-1], destination)
        finish = model.NewIntVar(0, HORIZON, f"finish_{bus.id}")
        model.Add(finish == prev_end + final_travel)
        bus_finish[bus.id] = finish

    # One charger per station — no overlapping intervals.
    by_station: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for bus_id, station_id, _, _ in events:
        by_station[station_id].append((bus_id, station_id))

    for station_id, keys in by_station.items():
        station = route.station_by_id(station_id)
        intervals = []
        for key in keys:
            intervals.append(
                model.NewIntervalVar(start[key], charge_dur, end[key], f"iv_{key[0]}_{key[1]}")
            )
        model.AddCumulative(intervals, [1] * len(intervals), station.chargers)

    # Objective components
    total_wait = model.NewIntVar(0, HORIZON * len(events), "total_wait")
    model.Add(total_wait == sum(wait.values()))

    makespan = model.NewIntVar(0, HORIZON, "makespan")
    model.AddMaxEquality(makespan, list(bus_finish.values()))

    # Operator spread: sum of (max finish - min finish) per operator.
    buses_by_op: dict[str, list[str]] = defaultdict(list)
    for bus in scenario.buses:
        buses_by_op[bus.operator].append(bus.id)

    spread_terms = []
    for op, bus_ids in buses_by_op.items():
        if len(bus_ids) < 2:
            continue
        finishes = [bus_finish[bid] for bid in bus_ids]
        op_max = model.NewIntVar(0, HORIZON, f"opmax_{op}")
        op_min = model.NewIntVar(0, HORIZON, f"opmin_{op}")
        model.AddMaxEquality(op_max, finishes)
        model.AddMinEquality(op_min, finishes)
        spread = model.NewIntVar(0, HORIZON, f"spread_{op}")
        model.Add(spread == op_max - op_min)
        spread_terms.append(spread)

    operator_spread = model.NewIntVar(0, HORIZON * len(spread_terms), "operator_spread")
    if spread_terms:
        model.Add(operator_spread == sum(spread_terms))
    else:
        model.Add(operator_spread == 0)

    w = scenario.weights
    # Scale weights to integers for CP-SAT (0.1 precision).
    scale = 10
    obj_terms = []
    if w.individual:
        obj_terms.append(int(w.individual * scale) * total_wait)
    if w.overall:
        obj_terms.append(int(w.overall * scale) * makespan)
    if w.operator:
        obj_terms.append(int(w.operator * scale) * operator_spread)

    model.Minimize(sum(obj_terms) if obj_terms else total_wait)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 30.0
    status = solver.Solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise RuntimeError(f"CP-SAT failed with status {solver.StatusName(status)}")

    return _build_result(
        scenario,
        plan_assignments,
        solver,
        arrival,
        start,
        end,
        wait,
        bus_finish,
        solver.StatusName(status),
    )


def _build_result(
    scenario: Scenario,
    plan_assignments: dict[str, list[str]],
    solver: cp_model.CpSolver,
    arrival: dict,
    start: dict,
    end: dict,
    wait: dict,
    bus_finish: dict,
    status: str,
) -> ScheduleResult:
    route = scenario.route
    bus_timelines: list[BusTimeline] = []
    station_queues: dict[str, list[StationQueueEntry]] = defaultdict(list)

    total_wait = 0
    per_bus_wait: dict[str, int] = {}
    per_operator_finish: dict[str, list[int]] = defaultdict(list)
    makespan = 0

    bus_lookup = {b.id: b for b in scenario.buses}

    for bus in scenario.buses:
        plan = plan_assignments[bus.id]
        events: list[ChargingEvent] = []
        legs: list[dict] = []
        bus_wait = 0
        chain = _stop_chain(route, bus.direction)
        origin = chain[0]
        prev_stop = origin

        for station_id in plan:
            key = (bus.id, station_id)
            arr = solver.Value(arrival[key])
            st = solver.Value(start[key])
            en = solver.Value(end[key])
            w = solver.Value(wait[key])
            bus_wait += w

            travel = travel_minutes_between(route, bus.direction, prev_stop, station_id)
            legs.append(
                {
                    "from": prev_stop,
                    "to": station_id,
                    "travel_min": travel,
                    "arrival": arr,
                    "charge_start": st,
                    "charge_end": en,
                    "wait_min": w,
                }
            )

            evt = ChargingEvent(
                bus_id=bus.id,
                operator=bus.operator,
                station_id=station_id,
                arrival_min=arr,
                charge_start_min=st,
                charge_end_min=en,
                wait_min=w,
            )
            events.append(evt)
            station_queues[station_id].append(
                StationQueueEntry(
                    bus_id=bus.id,
                    operator=bus.operator,
                    arrival_min=arr,
                    charge_start_min=st,
                    charge_end_min=en,
                    wait_min=w,
                )
            )
            prev_stop = station_id

        destination = chain[-1]
        final_travel = travel_minutes_between(route, bus.direction, plan[-1], destination)
        finish = solver.Value(bus_finish[bus.id])
        legs.append(
            {
                "from": plan[-1],
                "to": destination,
                "travel_min": final_travel,
                "arrival": finish,
            }
        )

        per_bus_wait[bus.id] = bus_wait
        per_operator_finish[bus.operator].append(finish)
        total_wait += bus_wait
        makespan = max(makespan, finish)

        bus_timelines.append(
            BusTimeline(
                bus_id=bus.id,
                operator=bus.operator,
                direction=bus.direction,
                departure_min=bus.departure_min,
                stations_used=plan,
                events=events,
                arrival_min=finish,
                total_wait_min=bus_wait,
                legs=legs,
            )
        )

    for sid in station_queues:
        station_queues[sid].sort(key=lambda e: e.charge_start_min)

    operator_spread = sum(max(v) - min(v) for v in per_operator_finish.values() if len(v) > 1)

    ctx = ObjectiveContext(
        total_wait_min=total_wait,
        makespan_min=makespan,
        operator_spread_min=operator_spread,
        per_bus_wait=per_bus_wait,
        per_operator_finish=dict(per_operator_finish),
    )
    _ = weighted_score(ctx, scenario.weights)  # available for diagnostics

    return ScheduleResult(
        scenario=scenario,
        bus_timelines=sorted(bus_timelines, key=lambda t: t.departure_min),
        station_queues=dict(station_queues),
        makespan_min=makespan,
        total_wait_min=total_wait,
        operator_spread_min=operator_spread,
        solver_status=status,
        plan_assignments=plan_assignments,
    )
