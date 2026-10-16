import pytest

from planner.domain.corridor import build_corridor

EAST_WEST = [(-100.0, 40.0), (-98.0, 40.0)]


def test_corridor_keeps_only_nodes_near_the_route():
    grid = build_corridor([EAST_WEST], max_nodes=10_000, radius_km=20)
    spec = grid.spec

    assert spec.step == 0.1
    lats = {spec.lonlat(i)[1] for i in grid.nodes}
    lons = [spec.lonlat(i)[0] for i in grid.nodes]
    # 20 km is ~0.18 deg of latitude: rows 39.9..40.1 only.
    assert lats == {39.9, 40.0, 40.1}
    assert min(lons) <= -100.0 and max(lons) >= -98.0
    assert len(grid.nodes) < spec.nx * spec.ny


def test_grid_origin_is_aligned_to_the_step_lattice():
    # Aligned nodes mean the same places are requested (and cached) across trips.
    spec = build_corridor([EAST_WEST], max_nodes=10_000).spec

    assert spec.west / spec.step == pytest.approx(round(spec.west / spec.step))
    assert spec.south / spec.step == pytest.approx(round(spec.south / spec.step))


def test_spacing_coarsens_to_respect_node_budget():
    long_route = [(-118.0, 34.0), (-74.0, 40.7)]

    grid = build_corridor([long_route], max_nodes=300)

    assert len(grid.nodes) <= 300
    assert grid.spec.step > 0.1


def test_multiple_routes_share_one_grid():
    north = [(-100.0, 41.0), (-98.0, 41.0)]

    grid = build_corridor([EAST_WEST, north], max_nodes=10_000, radius_km=20)
    lats = {grid.spec.lonlat(i)[1] for i in grid.nodes}

    assert {40.0, 41.0} <= lats
    assert 40.5 not in lats  # gap between the two corridors is not filled


def test_requires_a_path():
    with pytest.raises(ValueError):
        build_corridor([], max_nodes=10)


def test_reports_the_radius_it_used():
    assert build_corridor([EAST_WEST], max_nodes=10_000, radius_km=20).radius_km == 20
    # Coarse spacings widen the corridor so it stays a few nodes across.
    coarse = build_corridor([[(-118.0, 34.0), (-74.0, 40.7)]], max_nodes=100)
    assert coarse.radius_km >= 1.5 * coarse.spec.step * 111.32 - 1e-9
