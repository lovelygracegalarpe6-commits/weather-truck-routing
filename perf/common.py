"""Shared helpers for the performance scripts: trips, process management, statistics."""

from __future__ import annotations

import os
import statistics
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
PERF = ROOT / "perf"
RESULTS = PERF / "results"

TRIPS = {
    "dallas-houston": ((32.7767, -96.797, "Dallas, TX"), (29.7604, -95.3698, "Houston, TX")),
    "chicago-nashville": ((41.8781, -87.6298, "Chicago, IL"), (36.1627, -86.7816, "Nashville, TN")),
    "denver-slc": ((39.7392, -104.9903, "Denver, CO"), (40.7608, -111.891, "Salt Lake City, UT")),
    # Long-haul stress case: ~2,000 mi, the most checkpoints and the biggest payloads.
    "la-chicago": ((34.0522, -118.2437, "Los Angeles, CA"), (41.8781, -87.6298, "Chicago, IL")),
}


def plan_body(trip: str, load_lb: float = 35_000, interval: int = 25) -> dict:
    (olat, olon, olabel), (dlat, dlon, dlabel) = TRIPS[trip]
    return {
        "origin": {"lat": olat, "lon": olon, "label": olabel},
        "destination": {"lat": dlat, "lon": dlon, "label": dlabel},
        "departure": None,
        "load_weight_lb": load_lb,
        "interval_miles": interval,
    }


def _decimate(path: list, max_points: int = 1500) -> list:
    """Same thinning the frontend applies before requesting the heatmap (useHeatmap.ts)."""
    if len(path) <= max_points:
        return path
    step = (len(path) - 1) / (max_points - 1)
    return [path[round(i * step)] for i in range(max_points)]


def heatmap_body(plan: dict) -> dict:
    return {
        "paths": [_decimate(route["path"]) for route in plan["routes"]],
        "departure_utc": plan["trip"]["departure_utc"],
        "load_weight_lb": plan["trip"]["load_weight_lb"],
    }


def summarize(latencies_s: list[float]) -> dict:
    """Latency percentiles in milliseconds."""
    if not latencies_s:
        return {}
    ms = sorted(x * 1000 for x in latencies_s)

    def pct(p: float) -> float:
        return ms[min(len(ms) - 1, round(p / 100 * (len(ms) - 1)))]

    return {
        "n": len(ms),
        "mean": statistics.fmean(ms),
        "p50": pct(50),
        "p90": pct(90),
        "p99": pct(99),
        "max": ms[-1],
    }


def wait_for(url: str, timeout: float = 60) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if requests.get(url, timeout=2).ok:
                return
        except requests.RequestException:
            pass
        time.sleep(0.3)
    raise RuntimeError(f"{url} did not become ready within {timeout}s")


@contextmanager
def running_stack(
    latency: str = "realistic",
    record: bool = False,
    mock_port: int = 8090,
    app_port: int = 8001,
    threads: int = 16,
    log_name: str = "server",
) -> Iterator[tuple[str, str]]:
    """Start the mock upstreams and the production-mode app server; yield their URLs."""
    RESULTS.mkdir(exist_ok=True)
    mock_url = f"http://127.0.0.1:{mock_port}"
    app_url = f"http://127.0.0.1:{app_port}"
    mock_cmd = [sys.executable, str(PERF / "mock_upstreams.py"), "--port", str(mock_port)]
    mock_cmd += ["--latency", latency] + (["--record"] if record else [])
    env = os.environ | {
        "DJANGO_DEBUG": "0",
        "DJANGO_ALLOWED_HOSTS": "127.0.0.1,localhost",
        "OSRM_BASE_URL": mock_url,
        "OPEN_METEO_BASE_URL": mock_url,
        "PHOTON_BASE_URL": mock_url,
        "API_THROTTLE_PLAN": "1000000/min",
        "API_THROTTLE_ANON": "1000000/min",
        "HTTP_FORCE_IPV4": "0",
        "HTTP_TIMEOUT_SECONDS": "60",
    }
    # waitress stands in for gunicorn (which does not run on Windows): same thread model.
    app_cmd = [
        sys.executable, "-m", "waitress", "--host=127.0.0.1", f"--port={app_port}",
        f"--threads={threads}", "--connection-limit=1000", "config.wsgi:application",
    ]  # fmt: skip
    log = open(RESULTS / f"{log_name}.log", "w", encoding="utf-8")  # noqa: SIM115
    mock = subprocess.Popen(mock_cmd, stdout=log, stderr=subprocess.STDOUT)
    app = subprocess.Popen(app_cmd, cwd=BACKEND, env=env, stdout=log, stderr=subprocess.STDOUT)
    try:
        wait_for(f"{mock_url}/__stats")
        wait_for(f"{app_url}/api/health/")
        yield app_url, mock_url
    finally:
        for proc in (app, mock):
            proc.terminate()
            proc.wait(timeout=10)
        log.close()


def upstream_stats(mock_url: str, reset: bool = False) -> dict:
    stats = requests.get(f"{mock_url}/__stats", timeout=5).json()
    if reset:
        requests.post(f"{mock_url}/__stats/reset", timeout=5)
    return stats
