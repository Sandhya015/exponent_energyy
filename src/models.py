"""Domain models for the bus charging scheduler."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Direction(str, Enum):
    BK = "BK"  # Bengaluru → Kochi
    KB = "KB"  # Kochi → Bengaluru


@dataclass(frozen=True)
class Weights:
    individual: float = 1.0
    operator: float = 1.0
    overall: float = 1.0


@dataclass(frozen=True)
class Segment:
    from_stop: str
    to_stop: str
    distance_km: float


@dataclass(frozen=True)
class Station:
    id: str
    name: str
    km_from_bengaluru: float
    chargers: int = 1


@dataclass(frozen=True)
class Route:
    id: str
    name: str
    speed_kmh: float
    range_km: float
    charge_duration_min: int
    segments: tuple[Segment, ...]
    stations: tuple[Station, ...]
    endpoints: tuple[str, ...]
    default_weights: Weights

    @property
    def total_distance_km(self) -> float:
        return sum(s.distance_km for s in self.segments)

    def travel_minutes(self, distance_km: float) -> int:
        """At constant speed, minutes = distance when speed is 60 km/h."""
        return int(round(distance_km * 60.0 / self.speed_kmh))

    def station_ids(self) -> list[str]:
        return [s.id for s in self.stations]

    def station_by_id(self, station_id: str) -> Station:
        for s in self.stations:
            if s.id == station_id:
                return s
        raise KeyError(station_id)


@dataclass(frozen=True)
class BusInput:
    id: str
    operator: str
    direction: Direction
    departure_min: int  # minutes from midnight


@dataclass(frozen=True)
class Scenario:
    id: str
    name: str
    description: str
    route: Route
    buses: tuple[BusInput, ...]
    weights: Weights


@dataclass(frozen=True)
class ChargingEvent:
    bus_id: str
    operator: str
    station_id: str
    arrival_min: int
    charge_start_min: int
    charge_end_min: int
    wait_min: int


@dataclass
class BusTimeline:
    bus_id: str
    operator: str
    direction: Direction
    departure_min: int
    stations_used: list[str]
    events: list[ChargingEvent]
    arrival_min: int
    total_wait_min: int
    legs: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class StationQueueEntry:
    bus_id: str
    operator: str
    arrival_min: int
    charge_start_min: int
    charge_end_min: int
    wait_min: int


@dataclass
class ScheduleResult:
    scenario: Scenario
    bus_timelines: list[BusTimeline]
    station_queues: dict[str, list[StationQueueEntry]]
    makespan_min: int
    total_wait_min: int
    operator_spread_min: int
    solver_status: str
    plan_assignments: dict[str, list[str]]
