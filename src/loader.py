"""Load route and scenario YAML files into domain models."""

from __future__ import annotations

from pathlib import Path

import yaml

from src.models import (
    BusInput,
    Direction,
    Route,
    Scenario,
    Segment,
    Station,
    Weights,
)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
ROUTES_DIR = DATA_DIR
SCENARIOS_DIR = DATA_DIR / "scenarios"


def parse_time_to_minutes(value: str) -> int:
    """Convert HH:MM string to minutes from midnight."""
    hour, minute = value.strip().split(":")
    return int(hour) * 60 + int(minute)


def minutes_to_time(value: int) -> str:
    hour, minute = divmod(int(value), 60)
    return f"{hour:02d}:{minute:02d}"


def load_route(path: Path | None = None) -> Route:
    path = path or ROUTES_DIR / "route.yaml"
    with path.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    segments = tuple(
        Segment(from_stop=s["from"], to_stop=s["to"], distance_km=float(s["distance_km"]))
        for s in raw["segments"]
    )
    stations = tuple(
        Station(
            id=s["id"],
            name=s["name"],
            km_from_bengaluru=float(s["km_from_bengaluru"]),
            chargers=int(s.get("chargers", 1)),
        )
        for s in raw["stations"]
    )
    weights_raw = raw.get("weights", {})
    weights = Weights(
        individual=float(weights_raw.get("individual", 1.0)),
        operator=float(weights_raw.get("operator", 1.0)),
        overall=float(weights_raw.get("overall", 1.0)),
    )
    endpoints = tuple(ep["id"] for ep in raw["endpoints"])

    return Route(
        id=raw["id"],
        name=raw["name"],
        speed_kmh=float(raw["speed_kmh"]),
        range_km=float(raw["battery"]["range_km"]),
        charge_duration_min=int(raw["battery"]["charge_duration_min"]),
        segments=segments,
        stations=stations,
        endpoints=endpoints,
        default_weights=weights,
    )


def load_scenario(path: Path, route: Route | None = None) -> Scenario:
    with path.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    if route is None:
        route = load_route()

    weights_raw = raw.get("weights", {})
    weights = Weights(
        individual=float(weights_raw.get("individual", route.default_weights.individual)),
        operator=float(weights_raw.get("operator", route.default_weights.operator)),
        overall=float(weights_raw.get("overall", route.default_weights.overall)),
    )

    buses = tuple(
        BusInput(
            id=b["id"],
            operator=b["operator"].lower(),
            direction=Direction(b["direction"]),
            departure_min=parse_time_to_minutes(b["departure"]),
        )
        for b in raw["buses"]
    )

    return Scenario(
        id=raw["id"],
        name=raw["name"],
        description=raw.get("description", ""),
        route=route,
        buses=buses,
        weights=weights,
    )


def list_scenario_files() -> list[Path]:
    return sorted(SCENARIOS_DIR.glob("scenario_*.yaml"))


def load_all_scenarios(route: Route | None = None) -> list[Scenario]:
    route = route or load_route()
    return [load_scenario(p, route) for p in list_scenario_files()]
