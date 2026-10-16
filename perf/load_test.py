"""Backend latency and throughput tests against a production-mode server + mock upstreams.

    python perf/load_test.py record      # one-time: record real OSRM responses (needs internet)
    python perf/load_test.py cold        # first-request latency per trip, upstream call counts
    python perf/load_test.py burst       # every trip planned at the same moment, empty cache
    python perf/load_test.py load        # warm-cache throughput at increasing concurrency
    python perf/load_test.py all         # cold + burst + load, saved to perf/results/backend.json

Each phase starts a fresh server, so caches never leak between phases.
"""

from __future__ import annotations

import argparse
import json
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import requests
from common import RESULTS, TRIPS, heatmap_body, plan_body, running_stack, summarize, upstream_stats


def timed_post(session: requests.Session, url: str, body: dict) -> tuple[float, requests.Response]:
    start = time.perf_counter()
    response = session.post(url, json=body, headers={"Accept-Encoding": "gzip"}, timeout=180)
    return time.perf_counter() - start, response


def record() -> None:
    with running_stack(latency="none", record=True, log_name="record") as (app, _):
        s = requests.Session()
        for trip in TRIPS:
            seconds, r = timed_post(s, f"{app}/api/plan/", plan_body(trip))
            r.raise_for_status()
            names = [route["summary"] for route in r.json()["routes"]]
            print(f"recorded {trip:18s} in {seconds:5.1f}s  routes: {names}")


def cold() -> list[dict]:
    """Realistic upstream latency, fresh caches: what a user waits for on a first plan."""
    rows = []
    with running_stack(latency="realistic", log_name="cold") as (app, mock):
        s = requests.Session()
        for trip in TRIPS:
            upstream_stats(mock, reset=True)
            plan_s, r = timed_post(s, f"{app}/api/plan/", plan_body(trip, interval=10))
            r.raise_for_status()
            plan = r.json()
            plan_calls = upstream_stats(mock, reset=True)
            heat_s, h = timed_post(s, f"{app}/api/heatmap/", heatmap_body(plan))
            h.raise_for_status()
            heat_calls = upstream_stats(mock, reset=True)
            # Same trip, heavier load and a later departure: should be served from cache.
            replan_s, r2 = timed_post(s, f"{app}/api/plan/", plan_body(trip, 45_000, 10))
            r2.raise_for_status()
            replan_calls = upstream_stats(mock, reset=True)
            rows.append(
                {
                    "trip": trip,
                    "miles": round(min(rt["distance_mi"] for rt in plan["routes"])),
                    "checkpoints": sum(len(rt["checkpoints"]) for rt in plan["routes"]),
                    "plan_s": plan_s,
                    "plan_kb": len(r.content) / 1024,
                    "heatmap_s": heat_s,
                    "heatmap_kb": len(h.content) / 1024,
                    "replan_s": replan_s,
                    "osrm_calls": plan_calls["osrm"],
                    "meteo_locations_plan": plan_calls["meteo_locations"],
                    "meteo_locations_heatmap": heat_calls["meteo_locations"],
                    "meteo_locations_replan": replan_calls["meteo_locations"],
                }
            )
            print(
                f"{trip:18s} plan {plan_s:5.2f}s  heatmap {heat_s:5.2f}s  "
                f"replan {replan_s * 1000:6.0f}ms  weather locations "
                f"{plan_calls['meteo_locations']}+{heat_calls['meteo_locations']}"
                f"+{replan_calls['meteo_locations']}"
            )
    return rows


def burst() -> dict:
    """All trips at once on an empty cache (realistic latency): contention check."""
    with running_stack(latency="realistic", log_name="burst") as (app, _):
        def one(trip: str) -> float:
            seconds, r = timed_post(requests.Session(), f"{app}/api/plan/", plan_body(trip, interval=10))
            r.raise_for_status()
            return seconds

        start = time.perf_counter()
        with ThreadPoolExecutor(len(TRIPS)) as pool:
            per_trip = dict(zip(TRIPS, pool.map(one, TRIPS), strict=True))
        wall = time.perf_counter() - start
    print(f"burst of {len(TRIPS)} cold plans: wall {wall:.2f}s, slowest {max(per_trip.values()):.2f}s")
    return {"wall_s": wall, "per_trip_s": per_trip}


def load(duration: float, levels: list[int]) -> list[dict]:
    """Warm caches: how many plan/heatmap requests per second the server sustains."""
    rows = []
    with running_stack(latency="none", log_name="load") as (app, _):
        warm = requests.Session()
        plans = {}
        for trip in TRIPS:  # warm route + forecast caches; keep plans for heatmap bodies
            _, r = timed_post(warm, f"{app}/api/plan/", plan_body(trip))
            plans[trip] = r.json()
            timed_post(warm, f"{app}/api/heatmap/", heatmap_body(plans[trip]))

        scenarios = {
            # A user tweaking load weight and interval on already-planned trips.
            "plan": lambda rnd: (
                "/api/plan/",
                plan_body(rnd.choice(list(TRIPS)), rnd.choice([20_000, 35_000, 45_000]), 25),
            ),
            "heatmap": lambda rnd: ("/api/heatmap/", heatmap_body(plans[rnd.choice(list(TRIPS))])),
        }
        for name, make in scenarios.items():
            for concurrency in levels:
                latencies: list[float] = []
                errors = 0
                lock = threading.Lock()
                deadline = time.perf_counter() + duration

                def worker(seed: int) -> None:
                    nonlocal errors
                    rnd, session = random.Random(seed), requests.Session()
                    while time.perf_counter() < deadline:
                        path, body = make(rnd)
                        seconds, r = timed_post(session, f"{app}{path}", body)
                        with lock:
                            if r.ok:
                                latencies.append(seconds)
                            else:
                                errors += 1

                with ThreadPoolExecutor(concurrency) as pool:
                    list(pool.map(worker, range(concurrency)))
                stats = summarize(latencies)
                row = {"endpoint": name, "concurrency": concurrency, "rps": len(latencies) / duration}
                row |= {"errors": errors} | stats
                rows.append(row)
                print(
                    f"{name:8s} c={concurrency:<3d} {row['rps']:6.1f} req/s  p50 {stats['p50']:6.0f}ms"
                    f"  p90 {stats['p90']:6.0f}ms  p99 {stats['p99']:6.0f}ms  errors {errors}"
                )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("phase", choices=["record", "cold", "burst", "load", "all"])
    parser.add_argument("--duration", type=float, default=15, help="seconds per load level")
    parser.add_argument("--concurrency", type=int, nargs="+", default=[1, 4, 8, 16])
    args = parser.parse_args()

    if args.phase == "record":
        record()
        return
    results: dict = {}
    if args.phase in ("cold", "all"):
        results["cold"] = cold()
    if args.phase in ("burst", "all"):
        results["burst"] = burst()
    if args.phase in ("load", "all"):
        results["load"] = load(args.duration, args.concurrency)
    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / f"backend-{args.phase}.json"
    out.write_text(json.dumps(results, indent=2))
    print(f"saved {out}")


if __name__ == "__main__":
    main()
