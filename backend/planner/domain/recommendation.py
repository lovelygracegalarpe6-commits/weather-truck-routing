"""Summarise each route's risk and pick the recommended one.

Ranking is lexicographic, in the order the brief prescribes:

  0. Fewest No Travel miles   (not in the brief's list; added because a route with
                               impassable stretches must never beat one without)
  1. Fewest Severe miles
  2. Fewest High miles
  3. Lowest average risk      (distance-weighted mean of level values 0..4)
  4. Shortest travel time

Mileage is compared at 0.1 mi and average risk at 0.01 so floating-point noise from
interpolation cannot decide a tie.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from .risk import RiskLevel


@dataclass(frozen=True)
class RouteRiskSummary:
    route_id: str
    name: str
    miles_by_level: dict[RiskLevel, float]
    unknown_miles: float
    average_risk: float | None
    max_level: RiskLevel | None
    duration_s: float

    @property
    def no_travel_miles(self) -> float:
        return self.miles_by_level[RiskLevel.NO_TRAVEL]

    @property
    def severe_miles(self) -> float:
        return self.miles_by_level[RiskLevel.SEVERE]

    @property
    def high_miles(self) -> float:
        return self.miles_by_level[RiskLevel.HIGH]


def summarize_route(
    route_id: str,
    name: str,
    checkpoint_risks: Iterable[tuple[RiskLevel | None, float]],
    duration_s: float,
) -> RouteRiskSummary:
    """`checkpoint_risks` are (level, represented miles); level None = no forecast."""
    miles = dict.fromkeys(RiskLevel, 0.0)
    unknown = 0.0
    for level, represented in checkpoint_risks:
        if level is None:
            unknown += represented
        else:
            miles[level] += represented

    known = sum(miles.values())
    average = sum(level * m for level, m in miles.items()) / known if known > 0 else None
    present = [level for level, m in miles.items() if m > 0]
    return RouteRiskSummary(
        route_id=route_id,
        name=name,
        miles_by_level=miles,
        unknown_miles=unknown,
        average_risk=average,
        max_level=max(present) if present else None,
        duration_s=duration_s,
    )


@dataclass(frozen=True)
class Criterion:
    key: str
    label: str


CRITERIA = (
    Criterion("no_travel_miles", "No Travel miles"),
    Criterion("severe_miles", "Severe miles"),
    Criterion("high_miles", "High miles"),
    Criterion("average_risk", "average risk"),
    Criterion("duration_s", "travel time"),
)


def _criterion_values(s: RouteRiskSummary) -> tuple[float, ...]:
    # Unknown average (no forecast at all) sorts after any known value.
    avg = round(s.average_risk, 2) if s.average_risk is not None else float("inf")
    return (
        round(s.no_travel_miles, 1),
        round(s.severe_miles, 1),
        round(s.high_miles, 1),
        avg,
        round(s.duration_s),
    )


def rank_routes(summaries: Sequence[RouteRiskSummary]) -> list[RouteRiskSummary]:
    """Best route first. Python's sort is stable, so full ties keep input order."""
    return sorted(summaries, key=_criterion_values)


def _miles(value: float) -> str:
    return f"{value:.0f} mi" if value >= 10 or value == 0 else f"{value:.1f} mi"


def _duration(seconds: float) -> str:
    minutes = round(seconds / 60)
    return f"{minutes // 60}h {minutes % 60:02d}m"


def _describe_win(criterion: Criterion, best: float, other: float, other_name: str) -> str:
    if criterion.key == "duration_s":
        return f"Same weather risk as {other_name}, but {_duration(other - best)} faster."
    if criterion.key == "average_risk":
        return (
            f"Same Severe and High mileage as {other_name}, but lower average risk: "
            f"{best:.2f} vs {other:.2f}."
        )
    return f"Fewer {criterion.label} than {other_name}: {_miles(best)} vs {_miles(other)}."


@dataclass(frozen=True)
class Comparison:
    other_route_id: str
    criterion: str
    text: str


def explain(best: RouteRiskSummary, others: Sequence[RouteRiskSummary]) -> list[Comparison]:
    """For each other route, the first criterion where the best route wins."""
    best_values = _criterion_values(best)
    comparisons = []
    for other in others:
        other_values = _criterion_values(other)
        for i, criterion in enumerate(CRITERIA):
            if best_values[i] == other_values[i]:
                continue
            text = _describe_win(criterion, best_values[i], other_values[i], other.name)
            comparisons.append(Comparison(other.route_id, criterion.key, text))
            break
        else:
            comparisons.append(
                Comparison(other.route_id, "tie", f"Identical risk and time to {other.name}.")
            )
    return comparisons


def warnings_for(best: RouteRiskSummary) -> list[str]:
    warnings = []
    if best.no_travel_miles > 0:
        warnings.append(
            f"Every route crosses No Travel conditions; even the recommended route has "
            f"{best.no_travel_miles:.0f} mi. Consider delaying departure."
        )
    elif best.severe_miles > 0:
        warnings.append(
            f"The recommended route still has {best.severe_miles:.0f} mi of Severe weather."
        )
    if best.unknown_miles > 0:
        warnings.append(
            f"{best.unknown_miles:.0f} mi of the recommended route are beyond the forecast range."
        )
    return warnings
