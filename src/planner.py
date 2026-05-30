"""Generate feasible charging-station plans respecting the 240 km range rule."""

from __future__ import annotations

from itertools import combinations

from src.models import Direction, Route


def _ordered_stations(route: Route, direction: Direction) -> list[str]:
    ids = route.station_ids()
    return ids if direction == Direction.BK else list(reversed(ids))


def _leg_distances(route: Route, direction: Direction) -> list[float]:
    """Segment distances in travel order for the given direction."""
    segs = list(route.segments)
    if direction == Direction.KB:
        segs = list(reversed(segs))
    return [s.distance_km for s in segs]


def _stop_chain(route: Route, direction: Direction) -> list[str]:
    """Ordered stop ids including endpoints: origin, stations..., destination."""
    if direction == Direction.BK:
        origin, dest = route.endpoints[0], route.endpoints[1]
        middle = route.station_ids()
    else:
        origin, dest = route.endpoints[1], route.endpoints[0]
        middle = list(reversed(route.station_ids()))
    return [origin, *middle, dest]


def _distance_between_stops(
    route: Route, direction: Direction, from_stop: str, to_stop: str
) -> float:
    chain = _stop_chain(route, direction)
    legs = _leg_distances(route, direction)
    if from_stop not in chain or to_stop not in chain:
        raise ValueError(f"Unknown stops {from_stop} -> {to_stop}")
    start_idx = chain.index(from_stop)
    end_idx = chain.index(to_stop)
    if start_idx >= end_idx:
        raise ValueError("to_stop must be after from_stop along route")
    return sum(legs[start_idx:end_idx])


def is_valid_plan(route: Route, direction: Direction, stations: list[str]) -> bool:
    """Check range constraint for a monotonic station subset."""
    if not stations:
        return False

    ordered = _ordered_stations(route, direction)
    indices = [ordered.index(s) for s in stations]
    if indices != sorted(indices):
        return False

    chain = _stop_chain(route, direction)
    origin = chain[0]
    destination = chain[-1]
    max_range = route.range_km

    # Origin to first station
    if _distance_between_stops(route, direction, origin, stations[0]) > max_range:
        return False

    # Between consecutive charging stops
    for a, b in zip(stations, stations[1:]):
        if _distance_between_stops(route, direction, a, b) > max_range:
            return False

    # Last station to destination
    if _distance_between_stops(route, direction, stations[-1], destination) > max_range:
        return False

    return True


def enumerate_valid_plans(route: Route, direction: Direction) -> list[list[str]]:
    """All non-empty station subsets that satisfy range constraints."""
    ordered = _ordered_stations(route, direction)
    valid: list[list[str]] = []
    for r in range(1, len(ordered) + 1):
        for combo in combinations(ordered, r):
            plan = list(combo)
            if is_valid_plan(route, direction, plan):
                valid.append(plan)
    # Prefer fewer stops (less downtime), then lexicographic for stability
    valid.sort(key=lambda p: (len(p), p))
    return valid


def travel_minutes_between(
    route: Route, direction: Direction, from_stop: str, to_stop: str
) -> int:
    return route.travel_minutes(_distance_between_stops(route, direction, from_stop, to_stop))


def naive_arrival_at_station(
    route: Route,
    direction: Direction,
    departure_min: int,
    stations: list[str],
    station_id: str,
) -> int:
    """Arrival time at a station ignoring charger queues (free-flow)."""
    chain = _stop_chain(route, direction)
    origin = chain[0]
    t = departure_min
    for s in stations:
        t += travel_minutes_between(route, direction, origin if s == stations[0] else _prev(stations, s), s)
        if s == station_id:
            return t
        t += route.charge_duration_min
        origin = s
    raise ValueError(f"{station_id} not in plan {stations}")


def _prev(stations: list[str], station_id: str) -> str:
    idx = stations.index(station_id)
    return stations[idx - 1] if idx > 0 else station_id
