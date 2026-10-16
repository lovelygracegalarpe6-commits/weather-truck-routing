import pytest

from planner.domain.recommendation import explain, rank_routes, summarize_route, warnings_for
from planner.domain.risk import RiskLevel

L, M, H, S, N = (
    RiskLevel.LOW,
    RiskLevel.MODERATE,
    RiskLevel.HIGH,
    RiskLevel.SEVERE,
    RiskLevel.NO_TRAVEL,
)


def route(route_id, risks, hours):
    return summarize_route(route_id, f"Route {route_id}", risks, duration_s=hours * 3600)


def test_summary_totals_miles_and_distance_weighted_average():
    s = route("A", [(L, 50), (H, 10), (S, 20), (None, 5)], hours=2)

    assert s.miles_by_level[L] == 50
    assert s.high_miles == 10
    assert s.severe_miles == 20
    assert s.unknown_miles == 5
    assert s.average_risk == pytest.approx((0 * 50 + 2 * 10 + 3 * 20) / 80)
    assert s.max_level == S


def test_summary_without_any_forecast():
    s = route("A", [(None, 10)], hours=1)

    assert s.average_risk is None
    assert s.max_level is None


@pytest.mark.parametrize(
    ("a", "b", "winner", "criterion"),
    [
        # No Travel miles dominate everything else.
        ([(N, 10), (L, 90)], [(S, 100)], "B", "no_travel_miles"),
        # Fewest Severe beats fewer High and a shorter time.
        ([(S, 10), (L, 90)], [(H, 100)], "B", "severe_miles"),
        # Same Severe: fewest High wins.
        ([(H, 20), (L, 80)], [(H, 10), (M, 90)], "B", "high_miles"),
        # Same Severe & High: lowest average risk wins.
        ([(H, 10), (M, 90)], [(H, 10), (L, 90)], "B", "average_risk"),
    ],
)
def test_ranking_follows_brief_priority(a, b, winner, criterion):
    # A is always faster so time can only matter as the final tie-breaker.
    ra, rb = route("A", a, hours=5), route("B", b, hours=9)

    ranked = rank_routes([ra, rb])

    assert ranked[0].route_id == winner
    assert explain(ranked[0], ranked[1:])[0].criterion == criterion


def test_travel_time_breaks_full_risk_tie():
    slow, fast = route("A", [(L, 100)], hours=3), route("B", [(L, 100)], hours=2.5)

    ranked = rank_routes([slow, fast])

    assert ranked[0].route_id == "B"
    [comparison] = explain(ranked[0], ranked[1:])
    assert comparison.text == "Same weather risk as Route A, but 0h 30m faster."


def test_float_noise_does_not_break_mileage_ties():
    a = route("A", [(S, 10.000001), (L, 90)], hours=2)
    b = route("B", [(S, 9.99999), (L, 90)], hours=1)

    assert rank_routes([a, b])[0].route_id == "B"  # decided by time, not by 2e-6 mi


def test_explanation_text_for_severe_miles():
    best, other = route("A", [(L, 100)], hours=3), route("B", [(S, 30), (L, 70)], hours=2)

    [comparison] = explain(best, [other])

    assert comparison.text == "Fewer Severe miles than Route B: 0 mi vs 30 mi."


def test_warnings_when_recommended_route_is_still_dangerous():
    assert warnings_for(route("A", [(N, 20), (L, 80)], hours=1))[0].startswith(
        "Every route crosses No Travel"
    )
    assert warnings_for(route("A", [(S, 20), (L, 80)], hours=1)) == [
        "The recommended route still has 20 mi of Severe weather."
    ]
    assert warnings_for(route("A", [(L, 100)], hours=1)) == []
