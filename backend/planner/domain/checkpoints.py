"""Place weather checkpoints along a route at a fixed mileage interval."""

from __future__ import annotations

from dataclasses import dataclass

from .geo import METERS_PER_MILE, Track

ALLOWED_INTERVALS_MILES = (10, 25, 50)


@dataclass(frozen=True)
class CheckpointPosition:
    index: int
    mile: float
    lon: float
    lat: float
    eta_offset_s: float  # drive time from departure
    represents_miles: float  # length of road this checkpoint stands for


def sample_checkpoints(track: Track, interval_miles: float) -> list[CheckpointPosition]:
    """Checkpoints at mile 0, every `interval_miles`, and at the destination.

    Each checkpoint represents the stretch of road closer to it than to its
    neighbours (half the gap on each side), so per-level mileage always sums to
    the route length and a single bad checkpoint counts for about one interval.
    """
    if interval_miles <= 0:
        raise ValueError("interval_miles must be positive")

    total_m = track.distance_m
    step_m = interval_miles * METERS_PER_MILE
    distances = [i * step_m for i in range(int(total_m // step_m) + 1)]
    # Always end at the destination unless it already sits (almost) on a sample.
    if total_m - distances[-1] > 0.05 * step_m or len(distances) == 1:
        distances.append(total_m)
    else:
        distances[-1] = total_m

    bounds = [0.0]
    bounds += [(distances[i] + distances[i + 1]) / 2 for i in range(len(distances) - 1)]
    bounds.append(total_m)

    checkpoints = []
    for i, d in enumerate(distances):
        p = track.locate(d)
        checkpoints.append(
            CheckpointPosition(
                index=i,
                mile=d / METERS_PER_MILE,
                lon=p.lon,
                lat=p.lat,
                eta_offset_s=p.time_s,
                represents_miles=(bounds[i + 1] - bounds[i]) / METERS_PER_MILE,
            )
        )
    return checkpoints
