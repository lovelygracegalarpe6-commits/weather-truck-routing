import pytest

from planner.errors import InvalidTripError, NoRouteError
from planner.providers import geocoding, routing, weather
from planner.providers.weather import HourlySeries

H = 3600


# --- routing ---------------------------------------------------------------------------


def osrm_route(coords, duration, legs=None):
    """Minimal OSRM route object with per-segment annotations."""
    legs = legs or [coords]
    out_legs = []
    for leg in legs:
        n = len(leg) - 1
        out_legs.append(
            {
                "summary": "I 65",
                "annotation": {"distance": [1000.0] * n, "duration": [duration / n] * n},
            }
        )
    flat = [c for i, leg in enumerate(legs) for c in (leg if i == 0 else leg[1:])]
    return {"geometry": {"coordinates": flat}, "legs": out_legs, "duration": duration}


def test_trim_spurs_removes_out_and_back_at_via_point():
    coords = [(0, 0), (1, 0), (1, 1), (1, 2), (1, 1), (1, 0), (2, 0)]
    distances = [1.0, 1.0, 1.0, 1.0, 1.0, 1.0]
    durations = [10.0, 10.0, 10.0, 10.0, 10.0, 10.0]

    coords, distances, durations = routing._trim_spurs(coords, distances, durations, [3])

    assert coords == [(0, 0), (1, 0), (2, 0)]
    assert distances == [1.0, 1.0]
    assert durations == [10.0, 10.0]


def test_via_route_spur_is_trimmed_when_building_option():
    leg1 = [(0.0, 0.0), (0.1, 0.0), (0.1, 0.1)]
    leg2 = [(0.1, 0.1), (0.1, 0.0), (0.2, 0.0)]
    option = routing._to_option(
        osrm_route(None, 400, legs=[leg1, leg2]), "osrm-via", max_speed_mph=1000
    )

    assert option.track.coords == ((0.0, 0.0), (0.1, 0.0), (0.2, 0.0))
    assert option.track.duration_s == pytest.approx(200)


def test_fetch_route_options_tops_up_with_distinct_via_routes(monkeypatch):
    north = [(0.0, 0.0), (0.5, 0.2), (1.0, 0.0)]
    south = [(0.0, 0.0), (0.5, -0.2), (1.0, 0.0)]
    straight = [(0.0, 0.0), (0.5, 0.0), (1.0, 0.0)]
    duplicate = [(0.0, 0.0), (0.5, 0.0), (1.0, 0.0)]
    calls = []

    def fake_request(points, alternatives):
        calls.append(points)
        if len(points) == 2:
            return [osrm_route(straight, 3600), osrm_route(duplicate, 3700)]
        # First via candidate repeats the straight route (rejected), then distinct ones.
        return [
            [osrm_route(duplicate, 3600)],
            [osrm_route(north, 4000)],
            [osrm_route(south, 4100)],
        ][len(calls) - 2]

    monkeypatch.setattr(routing, "_request", fake_request)

    options = routing.fetch_route_options((0, 0), (1, 0), max_speed_mph=1000)

    assert [o.track.coords[1] for o in options] == [(0.5, 0.0), (0.5, 0.2), (0.5, -0.2)]
    assert [o.source for o in options] == ["osrm", "osrm-via", "osrm-via"]
    assert len(calls) == 4


def test_via_candidates_that_are_too_slow_are_rejected(monkeypatch):
    straight = [(0.0, 0.0), (0.5, 0.0), (1.0, 0.0)]
    detour = [(0.0, 0.0), (0.5, 0.5), (1.0, 0.0)]

    def fake_request(points, alternatives):
        if len(points) == 2:
            return [osrm_route(straight, 3600)]
        return [osrm_route(detour, 3600 * 2)]  # 2x slower than fastest

    monkeypatch.setattr(routing, "_request", fake_request)

    options = routing.fetch_route_options((0, 0), (1, 0), max_speed_mph=1000)

    assert len(options) == 1


def test_no_route_propagates(monkeypatch):
    def fake_request(points, alternatives):
        raise NoRouteError("No drivable route was found between these places.")

    monkeypatch.setattr(routing, "_request", fake_request)

    with pytest.raises(NoRouteError):
        routing.fetch_route_options((0, 0), (1, 0), max_speed_mph=65)


# --- weather ---------------------------------------------------------------------------


def series(start=0, wind=(10, 20, 30), rain=(0.0, 0.1, 0.3), snow=(0, 0, 0)):
    n = len(wind)
    return HourlySeries(
        times=tuple(start + i * H for i in range(n)),
        wind_mph=tuple(wind),
        gust_mph=tuple(None if w is None else w + 10 for w in wind),
        rain_in_hr=tuple(rain),
        snow_in_hr=tuple(snow),
    )


def test_sample_interpolates_wind_and_uses_hour_ending_precip_bucket():
    s = series()

    at = s.sample_at(1.5 * H)

    assert at.wind_mph == pytest.approx(25)
    assert at.gust_mph == pytest.approx(35)
    assert at.rain_in_hr == pytest.approx(0.3)  # bucket ending at 2h covers 1h..2h


def test_sample_exactly_on_the_hour():
    at = series().sample_at(1 * H)

    assert at.wind_mph == 20
    assert at.rain_in_hr == pytest.approx(0.1)


def test_sample_outside_forecast_is_none():
    s = series(start=10 * H)

    assert s.sample_at(8 * H) is None
    assert s.sample_at(13 * H) is None
    assert s.sample_at(9.5 * H) is not None  # inside the first precip bucket


def test_missing_values_yield_no_sample():
    s = series(wind=(10, None, 30))

    assert s.sample_at(1 * H) is None


def test_snap_groups_nearby_points():
    assert weather.snap((41.8781, -87.6298)) == (41.9, -87.65)
    assert weather.snap((41.8749, -87.6251)) == (41.85, -87.65)


def test_parse_sums_rain_and_showers():
    parsed = weather._parse(
        {
            "hourly": {
                "time": [0, H],
                "wind_speed_10m": [5, 6],
                "wind_gusts_10m": [9, 10],
                "rain": [0.1, None],
                "showers": [0.05, None],
                "snowfall": [0, 0.2],
            }
        }
    )

    assert parsed.rain_in_hr == pytest.approx((0.15, None))
    assert parsed.snow_in_hr == (0, 0.2)


def test_fetch_hourly_batches_dedupes_and_caches(monkeypatch):
    requested = []

    def fake_batch(points, start, end):
        requested.append(list(points))
        return [series() for _ in points]

    monkeypatch.setattr(weather, "_fetch_batch", fake_batch)
    points = [(float(i), 0.0) for i in range(150)] + [(0.0, 0.0)]

    first = weather.fetch_hourly(points, 0, 2 * H)
    again = weather.fetch_hourly(points[:10], 0, 2 * H)

    assert len(first) == 150
    assert [len(b) for b in requested] == [100, 50]
    assert len(again) == 10 and len(requested) == 2  # served from cache


def test_fetch_hourly_refuses_trips_that_exceed_the_rate_limit(monkeypatch):
    monkeypatch.setattr(weather, "_fetch_batch", lambda *a: pytest.fail("should not fetch"))
    points = [(float(i) / 100, 0.0) for i in range(weather.MAX_LOCATIONS + 1)]

    with pytest.raises(InvalidTripError):
        weather.fetch_hourly(points, 0, H)


# --- geocoding -------------------------------------------------------------------------


def test_search_places_builds_readable_labels(monkeypatch):
    payload = {
        "features": [
            {
                "geometry": {"coordinates": [-87.62, 41.87]},
                "properties": {
                    "name": "Chicago",
                    "state": "Illinois",
                    "countrycode": "US",
                },
            },
            {
                "geometry": {"coordinates": [-87.63, 41.88]},
                "properties": {
                    "housenumber": "300",
                    "street": "W Chicago Ave",
                    "city": "Chicago",
                    "state": "Illinois",
                    "countrycode": "US",
                },
            },
        ]
    }
    monkeypatch.setattr(geocoding, "get_json", lambda *a, **k: payload)

    places = geocoding.search_places("chicago")

    assert [p.label for p in places] == [
        "Chicago, Illinois, US",
        "300 W Chicago Ave, Chicago, Illinois, US",
    ]
    assert places[0].lat == 41.87


def test_search_places_ignores_tiny_queries(monkeypatch):
    monkeypatch.setattr(geocoding, "get_json", lambda *a, **k: pytest.fail("no request"))

    assert geocoding.search_places(" a ") == []
