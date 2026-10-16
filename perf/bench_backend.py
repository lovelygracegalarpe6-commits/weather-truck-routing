"""CPU cost of the backend pipeline, in-process, with zero network latency.

Providers are wired to the mock's recorded OSRM responses and synthetic forecasts, so
the numbers measure only our code: parsing, geometry, risk, ranking, serialisation.

    python perf/bench_backend.py             # timing table
    python perf/bench_backend.py --profile   # plus cProfile hotspots for the long-haul trip
"""

from __future__ import annotations

import argparse
import cProfile
import json
import os
import pstats
import statistics
import sys
import time
from datetime import UTC, datetime
from urllib.parse import urlencode, urlsplit

from common import BACKEND, TRIPS

sys.path.insert(0, str(BACKEND))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
os.environ["DJANGO_DEBUG"] = "0"

import django  # noqa: E402

django.setup()

from django.core.cache import cache  # noqa: E402
from rest_framework.renderers import JSONRenderer  # noqa: E402

import mock_upstreams as mock  # noqa: E402
from planner.domain import geo  # noqa: E402
from planner.domain.risk import WeatherSample, assess  # noqa: E402
from planner.providers import geocoding, routing, weather  # noqa: E402
from planner.services.heatmap import build_heatmap  # noqa: E402
from planner.services.trip import Location, TripRequest, plan_trip  # noqa: E402


def fake_get_json(url: str, params: dict, provider: str, read_timeout: float | None = None):
    path = urlsplit(url).path
    if path.startswith("/route/v1/"):
        status, body = mock.osrm_payload(path, urlencode(params), record=False)
        if status != 200:
            raise RuntimeError(f"missing OSRM fixture for {path}; run load_test.py record")
        return json.loads(body)
    query = {k: [str(v)] for k, v in params.items()}
    if path == "/v1/forecast":
        return mock.forecast_payload(query)
    return mock.photon_payload(query)


for module in (routing, weather, geocoding):
    module.get_json = fake_get_json


def trip_request(name: str, interval: int, load: float = 35_000) -> TripRequest:
    (olat, olon, olabel), (dlat, dlon, dlabel) = TRIPS[name]
    return TripRequest(
        origin=Location(olat, olon, olabel),
        destination=Location(dlat, dlon, dlabel),
        departure=None,
        load_weight_lb=load,
        interval_miles=interval,
    )


def bench(fn, repeat: int = 5) -> float:
    """Median wall time in ms."""
    times = []
    for _ in range(repeat):
        start = time.perf_counter()
        fn()
        times.append((time.perf_counter() - start) * 1000)
    return statistics.median(times)


def render(payload: dict) -> bytes:
    return JSONRenderer().render(payload)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", action="store_true")
    args = parser.parse_args()

    print(f"{'trip':18s} {'cold plan':>10s} {'warm plan':>10s} {'heatmap':>9s} {'plan JSON':>10s}")
    for name in TRIPS:
        req = trip_request(name, 10)

        def cold_plan(req=req):
            cache.clear()
            return render(plan_trip(req))

        cold_ms = bench(cold_plan, repeat=3)
        warm_ms = bench(lambda req=req: render(plan_trip(req)))
        plan = plan_trip(req)
        paths = [r["path"] for r in plan["routes"]]
        departure = datetime.fromisoformat(plan["trip"]["departure_utc"])
        heat_ms = bench(lambda: render(build_heatmap(paths, departure, 35_000)), repeat=3)
        size_kb = len(render(plan)) / 1024
        print(f"{name:18s} {cold_ms:8.0f}ms {warm_ms:8.0f}ms {heat_ms:7.0f}ms {size_kb:8.0f}KB")

    sample = WeatherSample(wind_mph=38, gust_mph=50, rain_in_hr=0.3, snow_in_hr=0)
    n = 100_000
    start = time.perf_counter()
    for _ in range(n):
        assess(sample, 42_000)
    print(f"\nassess(): {(time.perf_counter() - start) / n * 1e6:.2f} µs per checkpoint")

    option = routing.fetch_route_options((-118.2437, 34.0522), (-87.6298, 41.8781), 65)[0]
    coords = option.track.coords
    print(f"simplify_indices({len(coords)} pts): {bench(lambda: geo.simplify_indices(coords, 25)):.0f} ms")

    if args.profile:
        req = trip_request("la-chicago", 10)
        plan_trip(req)  # warm caches: profile our CPU work, not fixture parsing
        profiler = cProfile.Profile()
        profiler.enable()
        render(plan_trip(req))
        profiler.disable()
        print("\nWarm long-haul plan, top functions by cumulative time:")
        pstats.Stats(profiler).sort_stats("cumulative").print_stats(18)

    _ = UTC  # keep import for clarity of datetime usage above


if __name__ == "__main__":
    main()
