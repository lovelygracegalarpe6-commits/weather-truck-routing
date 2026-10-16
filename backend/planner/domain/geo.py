"""Geometry helpers for routes: distances, time-aware tracks, simplification, overlap.

Coordinates are (lon, lat) tuples, matching GeoJSON and OSRM.
"""

from __future__ import annotations

import math
from bisect import bisect_right
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

LonLat = tuple[float, float]

EARTH_RADIUS_M = 6_371_008.8
METERS_PER_MILE = 1609.344
MPH_TO_MPS = METERS_PER_MILE / 3600.0


def haversine_m(a: LonLat, b: LonLat) -> float:
    lon1, lat1 = map(math.radians, a)
    lon2, lat2 = map(math.radians, b)
    h = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(h)))


@dataclass(frozen=True)
class TrackPoint:
    lon: float
    lat: float
    distance_m: float
    time_s: float


@dataclass(frozen=True)
class Track:
    """A route polyline with cumulative distance and drive time at every vertex."""

    coords: tuple[LonLat, ...]
    cum_dist_m: tuple[float, ...]
    cum_time_s: tuple[float, ...]

    @property
    def distance_m(self) -> float:
        return self.cum_dist_m[-1]

    @property
    def duration_s(self) -> float:
        return self.cum_time_s[-1]

    def locate(self, distance_m: float) -> TrackPoint:
        """Position and elapsed drive time at a distance along the route."""
        return self._interpolate(self.cum_dist_m, distance_m)

    def locate_time(self, time_s: float) -> TrackPoint:
        """Position reached after driving for `time_s` seconds."""
        return self._interpolate(self.cum_time_s, time_s)

    def _interpolate(self, axis: Sequence[float], value: float) -> TrackPoint:
        value = min(max(value, 0.0), axis[-1])
        i = min(bisect_right(axis, value), len(axis) - 1)
        lo, hi = i - 1, i
        span = axis[hi] - axis[lo]
        f = (value - axis[lo]) / span if span > 0 else 0.0
        (lon0, lat0), (lon1, lat1) = self.coords[lo], self.coords[hi]
        return TrackPoint(
            lon=lon0 + (lon1 - lon0) * f,
            lat=lat0 + (lat1 - lat0) * f,
            distance_m=self.cum_dist_m[lo] + (self.cum_dist_m[hi] - self.cum_dist_m[lo]) * f,
            time_s=self.cum_time_s[lo] + (self.cum_time_s[hi] - self.cum_time_s[lo]) * f,
        )


def build_track(
    coords: Sequence[LonLat],
    total_duration_s: float,
    segment_distances_m: Sequence[float] | None = None,
    segment_durations_s: Sequence[float] | None = None,
    max_speed_mph: float | None = None,
) -> Track:
    """Build a Track from a polyline and the router's per-segment annotations.

    * Segment durations are rescaled so they add up to the router's total (the
      total includes turn penalties that the per-segment annotations omit).
    * Missing or misaligned annotations fall back to haversine distances with
      the total duration spread proportionally to distance.
    * `max_speed_mph` caps the speed on every segment (trucks are slower than cars).
    """
    if len(coords) < 2:
        raise ValueError("A track needs at least two coordinates")
    n_segments = len(coords) - 1

    if segment_distances_m is None or len(segment_distances_m) != n_segments:
        segment_distances_m = [haversine_m(coords[i], coords[i + 1]) for i in range(n_segments)]
    total_distance = sum(segment_distances_m)

    if (
        segment_durations_s is not None
        and len(segment_durations_s) == n_segments
        and sum(segment_durations_s) > 0
    ):
        scale = total_duration_s / sum(segment_durations_s)
        durations = [d * scale for d in segment_durations_s]
    elif total_distance > 0:
        durations = [total_duration_s * d / total_distance for d in segment_distances_m]
    else:
        durations = [0.0] * n_segments

    if max_speed_mph:
        max_mps = max_speed_mph * MPH_TO_MPS
        durations = [
            max(t, d / max_mps) for t, d in zip(durations, segment_distances_m, strict=True)
        ]

    cum_dist, cum_time = [0.0], [0.0]
    for d, t in zip(segment_distances_m, durations, strict=True):
        cum_dist.append(cum_dist[-1] + d)
        cum_time.append(cum_time[-1] + t)

    return Track(
        coords=tuple((float(lon), float(lat)) for lon, lat in coords),
        cum_dist_m=tuple(cum_dist),
        cum_time_s=tuple(cum_time),
    )


class _LocalProjection:
    """Equirectangular projection to meters; accurate enough at route scale."""

    def __init__(self, ref_lat: float):
        self.kx = math.radians(1) * EARTH_RADIUS_M * math.cos(math.radians(ref_lat))
        self.ky = math.radians(1) * EARTH_RADIUS_M

    def __call__(self, p: LonLat) -> tuple[float, float]:
        return p[0] * self.kx, p[1] * self.ky


def simplify_indices(coords: Sequence[LonLat], tolerance_m: float) -> list[int]:
    """Ramer-Douglas-Peucker; returns the indices of the vertices to keep."""
    n = len(coords)
    if n <= 2:
        return list(range(n))
    project = _LocalProjection(sum(lat for _, lat in coords) / n)
    pts = [project(c) for c in coords]
    keep = [False] * n
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    tol2 = tolerance_m * tolerance_m
    while stack:
        start, end = stack.pop()
        (x1, y1), (x2, y2) = pts[start], pts[end]
        dx, dy = x2 - x1, y2 - y1
        seg_len2 = dx * dx + dy * dy
        worst_i, worst_d2 = -1, tol2
        for i in range(start + 1, end):
            px, py = pts[i]
            if seg_len2 == 0:
                d2 = (px - x1) ** 2 + (py - y1) ** 2
            else:
                t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / seg_len2))
                d2 = (px - x1 - t * dx) ** 2 + (py - y1 - t * dy) ** 2
            if d2 > worst_d2:
                worst_i, worst_d2 = i, d2
        if worst_i != -1:
            keep[worst_i] = True
            stack.append((start, worst_i))
            stack.append((worst_i, end))
    return [i for i, k in enumerate(keep) if k]


def shared_fraction(
    a: Track, b: Track, tolerance_m: float = 250.0, step_m: float = 1000.0
) -> float:
    """Fraction of route `a`'s length that runs along route `b` (within `tolerance_m`)."""
    project = _LocalProjection((a.coords[0][1] + a.coords[-1][1]) / 2)
    cell = tolerance_m

    # Densify b so that hashing its points by cell finds every nearby stretch of road.
    buckets: dict[tuple[int, int], list[tuple[float, float]]] = defaultdict(list)
    spacing = tolerance_m / 2
    d = 0.0
    while d <= b.distance_m:
        p = b.locate(d)
        x, y = project((p.lon, p.lat))
        buckets[(int(x // cell), int(y // cell))].append((x, y))
        d += spacing

    samples = max(2, int(a.distance_m // step_m) + 1)
    shared = 0
    tol2 = tolerance_m * tolerance_m
    for k in range(samples):
        p = a.locate(a.distance_m * k / (samples - 1))
        x, y = project((p.lon, p.lat))
        cx, cy = int(x // cell), int(y // cell)
        if any(
            (x - bx) ** 2 + (y - by) ** 2 <= tol2
            for gx in (cx - 1, cx, cx + 1)
            for gy in (cy - 1, cy, cy + 1)
            for bx, by in buckets.get((gx, gy), ())
        ):
            shared += 1
    return shared / samples
