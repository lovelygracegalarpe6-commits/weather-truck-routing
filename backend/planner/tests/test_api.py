"""API tests with the third-party providers replaced by deterministic fakes."""

from datetime import UTC, datetime, timedelta

import pytest
from rest_framework.test import APIClient

from planner.domain.geo import build_track
from planner.errors import UpstreamError
from planner.providers import routing, weather
from planner.providers.geocoding import Place
from planner.providers.routing import RouteOption
from planner.providers.weather import HourlySeries
from planner.services import trip as trip_service

H = 3600
NOW = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)


def straight(lat: float, hours: float) -> RouteOption:
    coords = [(-100 + i * 0.02, lat) for i in range(101)]  # ~105 mi east-west
    return RouteOption.from_track(
        build_track(coords, total_duration_s=hours * H), summary=f"Road {lat}", source="osrm"
    )


@pytest.fixture
def fakes(monkeypatch):
    """Route A (fast) runs through 40 mph wind at lat 40; route B (slower) is calm."""
    calls = {"weather_points": 0}

    def fake_routes(origin, destination, max_speed_mph, wanted=3):
        return [straight(40.0, 2.0), straight(41.0, 2.5)]

    def fake_forecasts(points):
        calls["weather_points"] += len(points)
        first = NOW.timestamp() - 8 * H
        times = tuple(first + i * H for i in range(9 * 24 + 8))
        out = {}
        for lat, lon in points:
            wind = 40.0 if abs(lat - 40.0) < 0.3 else 5.0
            n = len(times)
            out[(lat, lon)] = HourlySeries(
                times=times,
                wind_mph=(wind,) * n,
                gust_mph=(wind + 10,) * n,
                rain_in_hr=(0.0,) * n,
                snow_in_hr=(0.0,) * n,
            )
        return out

    monkeypatch.setattr(routing, "fetch_route_options", fake_routes)
    monkeypatch.setattr(weather, "fetch_forecasts", fake_forecasts)
    monkeypatch.setattr(weather, "lookup_timezone", lambda lat, lon: "America/Chicago")
    monkeypatch.setattr(trip_service.timezone, "now", lambda: NOW)
    return calls


def plan(client=None, **overrides):
    body = {
        "origin": {"lat": 40.0, "lon": -100.0, "label": "Origin"},
        "destination": {"lat": 40.0, "lon": -98.0, "label": "Destination"},
        "departure": "2026-10-16T08:00",
        "load_weight_lb": 45_000,
        "interval_miles": 10,
    } | overrides
    return (client or APIClient()).post("/api/plan/", body, format="json")


def test_plan_recommends_route_avoiding_severe_wind_for_heavy_load(fakes):
    response = plan()

    assert response.status_code == 200
    data = response.json()
    route_a, route_b = data["routes"]
    assert (route_a["id"], route_b["id"]) == ("A", "B")
    # 40 mph + 45,000 lb -> Severe along all of route A.
    assert route_a["stats"]["max_level"] == "severe"
    assert route_a["stats"]["miles_by_level"]["severe"] == pytest.approx(
        route_a["distance_mi"], abs=0.2
    )
    assert route_b["stats"]["max_level"] == "low"
    assert data["recommendation"]["route_id"] == "B"
    assert route_b["recommended"] and route_b["rank"] == 1
    assert data["recommendation"]["comparisons"][0]["criterion"] == "severe_miles"
    assert route_a["checkpoints"][3]["reasons"] == ["Wind 40 mph with 45,000 lb load (> 40,000 lb)"]


def test_lighter_load_lowers_risk_but_still_prefers_calm_route(fakes):
    data = plan(load_weight_lb=20_000).json()

    route_a = data["routes"][0]
    assert route_a["stats"]["max_level"] == "high"
    assert data["recommendation"]["comparisons"][0]["criterion"] == "high_miles"


def test_departure_is_local_time_at_origin_and_etas_follow_drive_time(fakes):
    data = plan().json()

    # 08:00 in Chicago (CDT, UTC-5) is 13:00 UTC.
    assert data["trip"]["departure_utc"] == "2026-10-16T13:00:00Z"
    assert data["trip"]["timezone"] == "America/Chicago"
    checkpoints = data["routes"][0]["checkpoints"]
    assert checkpoints[0]["mile"] == 0
    assert checkpoints[1]["mile"] == 10
    assert [c["mile"] for c in checkpoints][-1] == data["routes"][0]["distance_mi"]
    last_eta = datetime.fromisoformat(checkpoints[-1]["eta_utc"])
    assert last_eta == datetime(2026, 10, 16, 15, 0, tzinfo=UTC)  # 2 h drive


def test_route_payload_carries_map_geometry_with_drive_times(fakes):
    route = plan().json()["routes"][0]

    assert len(route["path"]) == len(route["path_times_s"]) >= 2
    assert route["path_times_s"][0] == 0
    assert route["path_times_s"][-1] == route["duration_s"]


def test_omitted_departure_means_leave_now(fakes):
    data = plan(departure=None).json()

    assert data["trip"]["departure_utc"] == "2026-10-16T12:00:00Z"


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"destination": {"lat": 40.0, "lon": -100.0}}, "same place"),
        ({"departure": "2026-10-30T08:00"}, "within 7 days"),
        ({"departure": "2026-10-15T08:00"}, "in the past"),
    ],
)
def test_invalid_trips_are_rejected_with_clear_messages(fakes, overrides, message):
    response = plan(**overrides)

    assert response.status_code == 400
    assert message in response.json()["detail"]
    assert response.json()["code"] == "invalid_trip"


@pytest.mark.parametrize(
    "overrides",
    [
        {"interval_miles": 15},
        {"load_weight_lb": -1},
        {"departure": "tomorrow morning"},
        {"origin": {"lat": 95, "lon": 0}},
    ],
)
def test_malformed_requests_return_field_errors(fakes, overrides):
    response = plan(**overrides)

    assert response.status_code == 400
    assert set(response.json()) & {"interval_miles", "load_weight_lb", "departure", "origin"}


def test_upstream_failures_surface_as_502(fakes, monkeypatch):
    def broken(*args, **kwargs):
        raise UpstreamError("Routing service is unreachable right now. Please try again.")

    monkeypatch.setattr(routing, "fetch_route_options", broken)

    response = plan()

    assert response.status_code == 502
    assert response.json()["code"] == "upstream_error"


def test_heatmap_returns_hourly_frames_on_corridor_grid(fakes):
    departure = NOW + timedelta(hours=1)
    body = {
        "paths": [[[-100.0, 40.0], [-98.0, 40.0]], [[-100.0, 41.0], [-98.0, 41.0]]],
        "departure_utc": departure.isoformat(),
        "load_weight_lb": 45_000,
    }

    response = APIClient().post("/api/heatmap/", body, format="json")

    assert response.status_code == 200
    data = response.json()
    assert data["frames"] == 49
    assert data["start_utc"] == "2026-10-16T13:00:00Z"
    n_nodes = len(data["nodes"])
    for layer in ("risk", "wind", "gust", "rain", "snow"):
        assert len(data["layers"][layer]) == 49
        assert all(len(frame) == n_nodes for frame in data["layers"][layer])
    grid = data["grid"]
    risk_by_lat = {}
    for node, level in zip(data["nodes"], data["layers"]["risk"][0], strict=True):
        lat = round(grid["south"] + (node // grid["nx"]) * grid["step"], 4)
        risk_by_lat.setdefault(lat, set()).add(level)
    assert risk_by_lat[40.0] == {3}  # Severe for the heavy load
    assert risk_by_lat[41.0] == {0}


def test_heatmap_validates_paths(fakes):
    body = {
        "paths": [[[-100.0, 140.0], [-98.0, 40.0]]],
        "departure_utc": NOW.isoformat(),
        "load_weight_lb": 1,
    }

    response = APIClient().post("/api/heatmap/", body, format="json")

    assert response.status_code == 400
    assert "paths" in response.json()


def test_geocode_endpoint(monkeypatch):
    monkeypatch.setattr(
        "planner.api.views.search_places",
        lambda q: [Place(label=f"{q.title()}, Tennessee, US", lat=36.16, lon=-86.78)],
    )

    response = APIClient().get("/api/geocode/", {"q": "nashville"})

    assert response.status_code == 200
    assert response.json() == {
        "results": [{"label": "Nashville, Tennessee, US", "lat": 36.16, "lon": -86.78}]
    }
