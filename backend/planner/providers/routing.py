"""Route options from OSRM.

OSRM's `alternatives` often returns fewer than three routes. When that happens we
look for more by routing through "via" points offset to either side of the
fastest route, then keep candidates that are reasonable (not much slower) and
genuinely different (low overlap with routes we already have).
"""

from __future__ import annotations

import logging
import math
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from django.conf import settings
from django.core.cache import cache

from planner.domain.geo import (
    LonLat,
    Track,
    build_track,
    haversine_m,
    shared_fraction,
    simplify_indices,
)
from planner.errors import NoRouteError

from .http import get_json

logger = logging.getLogger(__name__)

MAX_DURATION_RATIO = 1.6  # alternatives may be at most 60% slower than the fastest
MAX_SHARED_FRACTION = 0.8  # ...and must not run along an existing route for >80% of it
VIA_OFFSETS = (0.15, -0.15, 0.3, -0.3)  # fraction of straight-line distance, left/right
VIA_BATCH = 2  # via candidates requested concurrently (one left, one right of the route)
CACHE_SECONDS = 60 * 60
DISPLAY_TOLERANCE_M = 25.0  # map-line simplification; checkpoints use the full track


@dataclass(frozen=True)
class RouteOption:
    track: Track
    summary: str  # major roads, e.g. "I 65, I 57"
    source: str  # "osrm" or "osrm-via"
    # Vertices kept for drawing the route. Computed once here so it is cached with the
    # route: simplification is the most expensive step of re-planning a long trip.
    display_indices: tuple[int, ...]

    @classmethod
    def from_track(cls, track: Track, summary: str, source: str) -> RouteOption:
        indices = tuple(simplify_indices(track.coords, DISPLAY_TOLERANCE_M))
        return cls(track=track, summary=summary, source=source, display_indices=indices)


def _route_url(points: Sequence[LonLat]) -> str:
    coords = ";".join(f"{lon:.6f},{lat:.6f}" for lon, lat in points)
    return f"{settings.OSRM_BASE_URL}/route/v1/driving/{coords}"


def _request(points: Sequence[LonLat], alternatives: int) -> list[dict]:
    payload = get_json(
        _route_url(points),
        {
            "alternatives": alternatives if alternatives > 0 else "false",
            "overview": "full",
            "geometries": "geojson",
            "steps": "true",  # needed for leg summaries (road names)
            "annotations": "distance,duration",
            "continue_straight": "false",  # allow U-turns at via points; spurs are trimmed
        },
        provider="Routing service",
    )
    code = payload.get("code")
    if code == "NoRoute":
        raise NoRouteError("No drivable route was found between these places.")
    if code != "Ok":
        raise NoRouteError(payload.get("message") or f"Routing failed ({code}).")
    return payload["routes"]


def _trim_spurs(
    coords: list[LonLat], distances: list[float], durations: list[float], junctions: list[int]
) -> tuple[list[LonLat], list[float], list[float]]:
    """Remove out-and-back stretches where a route retraces itself at a via point."""
    for j in sorted(junctions, reverse=True):
        k = 0
        while j - k - 1 >= 0 and j + k + 1 < len(coords) and coords[j - k - 1] == coords[j + k + 1]:
            k += 1
        if k:
            del coords[j - k + 1 : j + k + 1]
            del distances[j - k : j + k]
            del durations[j - k : j + k]
    return coords, distances, durations


def _to_option(route: dict, source: str, max_speed_mph: float) -> RouteOption:
    coords = [(round(lon, 6), round(lat, 6)) for lon, lat in route["geometry"]["coordinates"]]
    distances: list[float] = []
    durations: list[float] = []
    junctions: list[int] = []
    for leg in route["legs"]:
        annotation = leg.get("annotation", {})
        distances += annotation.get("distance", [])
        durations += annotation.get("duration", [])
        junctions.append(len(distances))
    junctions.pop()  # the last "junction" is the destination

    total_duration = float(route["duration"])
    aligned = len(distances) == len(coords) - 1 == len(durations)
    if aligned and junctions:
        # Keep OSRM's turn-penalty overhead proportional after cutting spurs.
        scale = total_duration / sum(durations) if sum(durations) else 1.0
        coords, distances, durations = _trim_spurs(coords, distances, durations, junctions)
        total_duration = sum(durations) * scale

    track = build_track(
        coords,
        total_duration_s=total_duration,
        segment_distances_m=distances if aligned else None,
        segment_durations_s=durations if aligned else None,
        max_speed_mph=max_speed_mph,
    )
    summary = ", ".join(leg["summary"] for leg in route["legs"] if leg.get("summary"))
    return RouteOption.from_track(track, _dedupe_roads(summary), source)


def _dedupe_roads(summary: str) -> str:
    roads: list[str] = []
    for road in (r.strip() for r in summary.split(",")):
        if road and road not in roads:
            roads.append(road)
    return ", ".join(roads[:3])


def _is_distinct(candidate: RouteOption, kept: Sequence[RouteOption]) -> bool:
    return all(
        shared_fraction(candidate.track, other.track) < MAX_SHARED_FRACTION
        and shared_fraction(other.track, candidate.track) < MAX_SHARED_FRACTION
        for other in kept
    )


def _via_points(origin: LonLat, destination: LonLat, fastest: Track) -> list[LonLat]:
    """Points beside the middle of the fastest route, perpendicular to the trip."""
    mid = fastest.locate(fastest.distance_m / 2)
    straight_m = haversine_m(origin, destination)
    # Unit vector of the trip in a local metric frame (x east, y north).
    kx = math.cos(math.radians(mid.lat))
    dx = (destination[0] - origin[0]) * kx
    dy = destination[1] - origin[1]
    norm = math.hypot(dx, dy) or 1.0
    px, py = -dy / norm, dx / norm  # left-hand perpendicular
    deg_per_m = 1 / 111_320
    points = []
    for f in VIA_OFFSETS:
        offset_deg = f * straight_m * deg_per_m
        points.append((mid.lon + px * offset_deg / kx, mid.lat + py * offset_deg))
    return points


def fetch_route_options(
    origin: LonLat, destination: LonLat, max_speed_mph: float, wanted: int = 3
) -> list[RouteOption]:
    """Up to `wanted` distinct routes, fastest first. Cached: road networks rarely change."""
    key = (
        f"routes:{origin[0]:.5f},{origin[1]:.5f}:{destination[0]:.5f},{destination[1]:.5f}"
        f":{max_speed_mph}:{wanted}"
    )
    options = cache.get(key)
    if options is None:
        options = _find_route_options(origin, destination, max_speed_mph, wanted)
        cache.set(key, options, timeout=CACHE_SECONDS)
    return options


def _find_route_options(
    origin: LonLat, destination: LonLat, max_speed_mph: float, wanted: int
) -> list[RouteOption]:
    routes = _request([origin, destination], alternatives=wanted)
    options: list[RouteOption] = []
    for route in routes:
        option = _to_option(route, "osrm", max_speed_mph)
        if _is_distinct(option, options):
            options.append(option)

    fastest = min(options, key=lambda o: o.track.duration_s)

    def via_route(via: LonLat) -> dict | None:
        try:
            return _request([origin, via, destination], alternatives=0)[0]
        except NoRouteError:
            return None  # via point in a lake, desert, across a border...

    vias = _via_points(origin, destination, fastest.track)
    # Request candidates in concurrent pairs (each pair costs one round trip), but judge
    # them in a fixed order so the chosen routes never depend on response timing.
    for i in range(0, len(vias), VIA_BATCH):
        if len(options) >= wanted:
            break
        batch = vias[i : i + VIA_BATCH]
        with ThreadPoolExecutor(max_workers=len(batch)) as pool:
            routes = list(pool.map(via_route, batch))
        for via, route in zip(batch, routes, strict=True):
            if route is None or len(options) >= wanted:
                continue
            candidate = _to_option(route, "osrm-via", max_speed_mph)
            too_slow = candidate.track.duration_s > MAX_DURATION_RATIO * fastest.track.duration_s
            if not too_slow and _is_distinct(candidate, options):
                options.append(candidate)
            else:
                logger.debug("Rejected via candidate %s (too_slow=%s)", via, too_slow)

    return sorted(options, key=lambda o: o.track.duration_s)[:wanted]
