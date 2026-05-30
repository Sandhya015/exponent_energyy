"""Soft optimization rules — add new rules here without touching the solver core."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from src.models import Weights


@dataclass
class ObjectiveContext:
    """Metrics available when evaluating a schedule."""

    total_wait_min: int
    makespan_min: int
    operator_spread_min: int
    per_bus_wait: dict[str, int]
    per_operator_finish: dict[str, list[int]]


class SoftRule(ABC):
    """A tunable soft objective component."""

    name: str

    @abstractmethod
    def evaluate(self, ctx: ObjectiveContext) -> int:
        """Return a non-negative penalty/score component (lower is better)."""

    @abstractmethod
    def weight_key(self) -> str:
        """Key in scenario/route weights YAML."""


class IndividualWaitRule(SoftRule):
    name = "individual"

    def evaluate(self, ctx: ObjectiveContext) -> int:
        return ctx.total_wait_min

    def weight_key(self) -> str:
        return "individual"


class OverallMakespanRule(SoftRule):
    name = "overall"

    def evaluate(self, ctx: ObjectiveContext) -> int:
        return ctx.makespan_min

    def weight_key(self) -> str:
        return "overall"


class OperatorSpreadRule(SoftRule):
    """Penalize large spread in finish times within each operator fleet."""

    name = "operator"

    def evaluate(self, ctx: ObjectiveContext) -> int:
        spread = 0
        for finishes in ctx.per_operator_finish.values():
            if len(finishes) < 2:
                continue
            spread += max(finishes) - min(finishes)
        return spread

    def weight_key(self) -> str:
        return "operator"


DEFAULT_RULES: list[SoftRule] = [
    IndividualWaitRule(),
    OperatorSpreadRule(),
    OverallMakespanRule(),
]


def weighted_score(ctx: ObjectiveContext, weights: Weights, rules: list[SoftRule] | None = None) -> float:
    rules = rules or DEFAULT_RULES
    total = 0.0
    for rule in rules:
        w = getattr(weights, rule.weight_key())
        total += w * rule.evaluate(ctx)
    return total
