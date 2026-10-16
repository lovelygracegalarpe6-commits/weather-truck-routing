"""A regular lat/lon grid covering the trip corridor, used for the weather heatmap.

Only grid nodes within `radius_km` of a route are kept, so weather is fetched for
the corridor rather than the whole bounding box. The finest spacing whose node count
fits the budget wins; the corridor widens with coarse spacings so it stays at least
a few nodes across.
"""

from __future__ import annotations

import math
from collections.abc import Iterator, Sequence
from dataclasses import dataclass

from .geo import LonLat

KM_PER_DEG_LAT = 111.32
# Multiples of the 0.1 deg weather lattice, so heatmap nodes share cached forecasts
# with checkpoints.
STEPS_DEG = (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.8, 1.0, 1.5, 2.0)
DEFAULT_RADIUS_KM = 40.0


@dataclass(frozen=True)
class GridSpec:
    west: float
    south: float
    step: float
    nx: int
    ny: int

    def lonlat(self, index: int) -> LonLat:
        iy, ix = divmod(index, self.nx)
        return (round(self.west + ix * self.step, 4), round(self.south + iy * self.step, 4))


@dataclass(frozen=True)
class CorridorGrid:
    spec: GridSpec
    nodes: tuple[int, ...]  # flat indices (iy * nx + ix), ascending
    radius_km: float  # every node lies within this distance of a route


def _densify(path: Sequence[LonLat], max_gap_deg: float) -> Iterator[LonLat]:
    for (lon0, lat0), (lon1, lat1) in zip(path, path[1:], strict=False):
        n = max(1, math.ceil(max(abs(lon1 - lon0), abs(lat1 - lat0)) / max_gap_deg))
        for k in range(n):
            f = k / n
            yield lon0 + (lon1 - lon0) * f, lat0 + (lat1 - lat0) * f
    if path:
        yield path[-1]


def _km_per_deg_lon(paths: Sequence[Sequence[LonLat]]) -> float:
    lats = [lat for path in paths for _, lat in path]
    mid_lat = (min(lats) + max(lats)) / 2
    return KM_PER_DEG_LAT * max(math.cos(math.radians(mid_lat)), 0.1)


def _grid_for_step(
    paths: Sequence[Sequence[LonLat]], step: float, radius_km: float
) -> CorridorGrid:
    lons = [lon for path in paths for lon, _ in path]
    lats = [lat for path in paths for _, lat in path]
    km_per_deg_lon = _km_per_deg_lon(paths)
    pad_lat, pad_lon = radius_km / KM_PER_DEG_LAT, radius_km / km_per_deg_lon

    west = math.floor((min(lons) - pad_lon) / step) * step
    south = math.floor((min(lats) - pad_lat) / step) * step
    nx = math.ceil((max(lons) + pad_lon - west) / step) + 1
    ny = math.ceil((max(lats) + pad_lat - south) / step) + 1
    spec = GridSpec(west=round(west, 6), south=round(south, 6), step=step, nx=nx, ny=ny)

    kx, ky = math.ceil(pad_lon / step), math.ceil(pad_lat / step)
    r2 = radius_km * radius_km
    inside = bytearray(nx * ny)  # cheaper than a set: neighbouring samples overlap heavily
    for path in paths:
        for lon, lat in _densify(path, step / 2):
            cx, cy = round((lon - west) / step), round((lat - south) / step)
            x0, x1 = (cx - kx if cx > kx else 0), (cx + kx if cx + kx < nx else nx - 1)
            y0, y1 = (cy - ky if cy > ky else 0), (cy + ky if cy + ky < ny else ny - 1)
            for iy in range(y0, y1 + 1):
                dy = (south + iy * step - lat) * KM_PER_DEG_LAT
                row = iy * nx
                for ix in range(x0, x1 + 1):
                    dx = (west + ix * step - lon) * km_per_deg_lon
                    if dx * dx + dy * dy <= r2:
                        inside[row + ix] = 1
    nodes = tuple(i for i, v in enumerate(inside) if v)
    return CorridorGrid(spec=spec, nodes=nodes, radius_km=radius_km)


def _estimated_nodes(paths: Sequence[Sequence[LonLat]], step: float, radius_km: float) -> float:
    """Buffer area of every path over the cell area (overlap between paths counted twice)."""
    kx = _km_per_deg_lon(paths)
    length_km = sum(
        math.hypot((lon1 - lon0) * kx, (lat1 - lat0) * KM_PER_DEG_LAT)
        for path in paths
        for (lon0, lat0), (lon1, lat1) in zip(path, path[1:], strict=False)
    )
    area = length_km * 2 * radius_km + len(paths) * math.pi * radius_km**2
    return area / ((step * KM_PER_DEG_LAT) * (step * kx))


def build_corridor(
    paths: Sequence[Sequence[LonLat]],
    max_nodes: int,
    radius_km: float = DEFAULT_RADIUS_KM,
) -> CorridorGrid:
    if not paths or not any(paths):
        raise ValueError("At least one path is required")
    # Keep the corridor at least ~3 nodes wide at coarse spacings.
    radii = [max(radius_km, 1.5 * step * KM_PER_DEG_LAT) for step in STEPS_DEG]
    # Building a grid is the expensive part, so skip spacings that clearly cannot fit.
    # The estimate over-counts where routes overlap, so start two spacings finer than it
    # suggests and let the exact count decide.
    first_fit = next(
        (
            i
            for i, step in enumerate(STEPS_DEG)
            if _estimated_nodes(paths, step, radii[i]) <= max_nodes
        ),
        len(STEPS_DEG) - 1,
    )
    grid = None
    for i in range(max(first_fit - 2, 0), len(STEPS_DEG)):
        grid = _grid_for_step(paths, STEPS_DEG[i], radii[i])
        if len(grid.nodes) <= max_nodes:
            return grid
    assert grid is not None
    return grid
