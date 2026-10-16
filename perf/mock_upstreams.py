"""Local stand-ins for OSRM, Open-Meteo and Photon, used by the performance tests.

Load-testing the free public APIs would break their usage policies (and trip their rate
limits), and their latency varies from run to run. This server makes runs repeatable:

* OSRM: replays recorded responses (record them once with ``--record``).
* Open-Meteo: synthesises deterministic hourly forecasts for any coordinates, with a
  storm moving across the central US so risk levels and the heatmap are non-trivial.
* Photon: answers geocoding for a few cities.

Latency is injected per request (``--latency realistic``, calibrated against the real
services from this project's development, or ``none`` to measure our code alone).

    python perf/mock_upstreams.py --port 8090 [--latency none] [--record]
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

FIXTURES = Path(__file__).parent / "fixtures" / "osrm"
REAL_OSRM = "https://router.project-osrm.org"

# Seconds. "realistic" mirrors timings measured against the public services:
# OSRM ~2-3 s for a long route with steps; Open-Meteo ~0.5 s + ~20 ms per location.
LATENCY_PROFILES = {
    "realistic": {"osrm": 2.0, "meteo_base": 0.5, "meteo_per_location": 0.02, "photon": 0.3},
    "none": {"osrm": 0.0, "meteo_base": 0.0, "meteo_per_location": 0.0, "photon": 0.0},
}

CITIES = {
    "chicago": ("Chicago", "Illinois", 41.8781, -87.6298),
    "nashville": ("Nashville", "Tennessee", 36.1627, -86.7816),
    "denver": ("Denver", "Colorado", 39.7392, -104.9903),
    "salt lake city": ("Salt Lake City", "Utah", 40.7608, -111.891),
    "dallas": ("Dallas", "Texas", 32.7767, -96.797),
    "houston": ("Houston", "Texas", 29.7604, -95.3698),
    "los angeles": ("Los Angeles", "California", 34.0522, -118.2437),
}


# --- Synthetic weather -------------------------------------------------------------------

EPOCH = int(time.time() // 86400 * 86400)  # midnight UTC today: storm track is stable per day


def synth_weather(lat: float, lon: float, t: float) -> tuple[float, float, float, float]:
    """(wind mph, gust mph, rain in/hr, snow in/hr) at a place and unix time."""
    hours = (t - EPOCH) / 3600
    wind = 9 + 5 * math.sin(math.radians(lat * 20 + hours * 15)) + 4 * math.cos(
        math.radians(lon * 15 - hours * 10)
    )
    # A storm crossing from the Rockies to the Ohio valley every 48 h.
    phase = (hours % 48) / 48
    c_lon, c_lat = -106 + 30 * phase, 37 + 4 * phase
    d2 = ((lon - c_lon) * math.cos(math.radians(lat))) ** 2 + (lat - c_lat) ** 2
    s = math.exp(-d2 / (2 * 1.6**2))
    wind = max(wind + 44 * s, 0.0)
    gust = wind * 1.45 + 3
    precip = 0.9 * s**1.5
    if lat > 40.5:
        return wind, gust, 0.0, round(precip * 4, 3)
    return wind, gust, round(precip, 3), 0.0


def tz_guess(lon: float) -> str:
    if lon > -85:
        return "America/New_York"
    if lon > -101:
        return "America/Chicago"
    if lon > -114:
        return "America/Denver"
    return "America/Los_Angeles"


def forecast_payload(query: dict[str, list[str]]) -> object:
    lats = [float(v) for v in query["latitude"][0].split(",")]
    lons = [float(v) for v in query["longitude"][0].split(",")]
    if "hourly" not in query:  # timezone lookup
        return {"latitude": lats[0], "longitude": lons[0], "timezone": tz_guess(lons[0])}

    past = int(query.get("past_hours", ["0"])[0])
    hours = int(query.get("forecast_hours", ["48"])[0])
    start = int(time.time() // 3600 * 3600) - past * 3600
    times = [start + i * 3600 for i in range(past + hours)]
    items = []
    for lat, lon in zip(lats, lons, strict=True):
        rows = [synth_weather(lat, lon, t) for t in times]
        items.append(
            {
                "latitude": lat,
                "longitude": lon,
                "hourly": {
                    "time": times,
                    "wind_speed_10m": [round(r[0], 1) for r in rows],
                    "wind_gusts_10m": [round(r[1], 1) for r in rows],
                    "rain": [r[2] for r in rows],
                    "showers": [0.0] * len(rows),
                    "snowfall": [r[3] for r in rows],
                },
            }
        )
    return items if len(items) > 1 else items[0]


def photon_payload(query: dict[str, list[str]]) -> dict:
    q = query.get("q", [""])[0].strip().lower()
    features = [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {"name": name, "state": state, "countrycode": "US"},
        }
        for key, (name, state, lat, lon) in CITIES.items()
        if key.startswith(q) or q in key
    ]
    return {"type": "FeatureCollection", "features": features}


# --- OSRM record / replay ------------------------------------------------------------------


def fixture_path(path: str, query: str) -> Path:
    params = "&".join(sorted(query.split("&")))
    digest = hashlib.sha1(f"{path}?{params}".encode()).hexdigest()[:16]
    return FIXTURES / f"{digest}.json.gz"


def osrm_payload(path: str, query: str, record: bool) -> tuple[int, bytes]:
    fixture = fixture_path(path, query)
    if fixture.exists():
        return 200, gzip.decompress(fixture.read_bytes())
    if not record:
        msg = {"code": "NoFixture", "message": f"No recorded OSRM response for {path}"}
        return 502, json.dumps(msg).encode()
    import requests  # only needed when recording

    response = requests.get(f"{REAL_OSRM}{path}?{query}", timeout=60)
    if response.ok:
        FIXTURES.mkdir(parents=True, exist_ok=True)
        fixture.write_bytes(gzip.compress(response.content, compresslevel=9))
    return response.status_code, response.content


# --- HTTP server ---------------------------------------------------------------------------


class Stats:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        self.counts = {"osrm": 0, "meteo_requests": 0, "meteo_locations": 0, "photon": 0}

    def add(self, key: str, n: int = 1) -> None:
        with self.lock:
            self.counts[key] += n


def make_handler(latency: dict, record: bool, stats: Stats):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args) -> None:  # keep load-test output clean
            pass

        def _send(self, status: int, body: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802 (http.server naming)
            url = urlsplit(self.path)
            query = parse_qs(url.query)
            if url.path.startswith("/route/v1/"):
                stats.add("osrm")
                time.sleep(latency["osrm"])
                self._send(*osrm_payload(url.path, url.query, record))
            elif url.path == "/v1/forecast":
                n = len(query["latitude"][0].split(","))
                stats.add("meteo_requests")
                stats.add("meteo_locations", n)
                time.sleep(latency["meteo_base"] + latency["meteo_per_location"] * n)
                self._send(200, json.dumps(forecast_payload(query)).encode())
            elif url.path == "/api/":
                stats.add("photon")
                time.sleep(latency["photon"])
                self._send(200, json.dumps(photon_payload(query)).encode())
            elif url.path == "/__stats":
                self._send(200, json.dumps(stats.counts).encode())
            else:
                self._send(404, b'{"message": "unknown path"}')

        def do_POST(self) -> None:  # noqa: N802
            if self.path == "/__stats/reset":
                stats.reset()
                self._send(200, b"{}")
            else:
                self._send(404, b"{}")

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--port", type=int, default=8090)
    parser.add_argument("--latency", choices=LATENCY_PROFILES, default="realistic")
    parser.add_argument("--record", action="store_true", help="fetch missing OSRM fixtures")
    args = parser.parse_args()

    server = ThreadingHTTPServer(
        ("127.0.0.1", args.port),
        make_handler(LATENCY_PROFILES[args.latency], args.record, Stats()),
    )
    server.daemon_threads = True
    print(f"mock upstreams on http://127.0.0.1:{args.port} (latency={args.latency})", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
