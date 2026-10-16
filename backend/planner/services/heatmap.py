"""Hourly weather + risk on a corridor grid, for the map heatmap and its time slider.

Frames are aligned to the departure time (frame h = departure + h hours) so the
heatmap, the truck positions and the checkpoint ETAs all share one clock.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from django.conf import settings

from planner.domain.corridor import build_corridor
from planner.domain.geo import LonLat
from planner.domain.risk import assess
from planner.providers import weather

from .serialization import iso_utc

HOUR = 3600


def build_heatmap(
    paths: Sequence[Sequence[LonLat]],
    departure: datetime,
    load_weight_lb: float,
    hours: int = 48,
) -> dict:
    grid = build_corridor(paths, max_nodes=settings.HEATMAP_MAX_CELLS)
    spec = grid.spec
    node_points = [spec.lonlat(i)[::-1] for i in grid.nodes]  # (lat, lon)

    forecasts = weather.fetch_forecasts(node_points)
    start = departure.timestamp()
    series = [forecasts.get(p) for p in node_points]

    wind, gust, rain, snow, risk = [], [], [], [], []
    for frame in range(hours + 1):
        t = start + frame * HOUR
        samples = [s.sample_at(t) if s else None for s in series]
        wind.append([round(s.wind_mph, 1) if s else None for s in samples])
        gust.append([round(s.gust_mph, 1) if s else None for s in samples])
        rain.append([round(s.rain_in_hr, 3) if s else None for s in samples])
        snow.append([round(s.snow_in_hr, 3) if s else None for s in samples])
        risk.append(
            [
                int(assess(s, load_weight_lb, settings.WIND_METRIC).level) if s else None
                for s in samples
            ]
        )

    return {
        "grid": {
            "west": spec.west,
            "south": spec.south,
            "step": spec.step,
            "nx": spec.nx,
            "ny": spec.ny,
        },
        "nodes": list(grid.nodes),
        "start_utc": iso_utc(start),
        "frame_seconds": HOUR,
        "frames": hours + 1,
        "layers": {"risk": risk, "wind": wind, "gust": gust, "rain": rain, "snow": snow},
    }
