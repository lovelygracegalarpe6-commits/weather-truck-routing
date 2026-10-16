import pytest

from planner.domain.checkpoints import sample_checkpoints
from planner.domain.geo import (
    METERS_PER_MILE,
    build_track,
    haversine_m,
    shared_fraction,
    simplify_indices,
)

# One degree of longitude on the equator is ~69.17 miles.
MILES_PER_DEG_EQUATOR = haversine_m((0, 0), (1, 0)) / METERS_PER_MILE


def straight_track(miles: float, hours: float, max_speed_mph=None):
    lon_end = miles / MILES_PER_DEG_EQUATOR
    coords = [(lon_end * i / 100, 0.0) for i in range(101)]
    return build_track(coords, total_duration_s=hours * 3600, max_speed_mph=max_speed_mph)


def test_haversine_matches_known_distance():
    chicago, nashville = (-87.6298, 41.8781), (-86.7816, 36.1627)
    assert haversine_m(chicago, nashville) / METERS_PER_MILE == pytest.approx(397, abs=2)


def test_track_locates_by_distance_and_time():
    track = straight_track(miles=100, hours=2)

    halfway = track.locate(50 * METERS_PER_MILE)
    assert halfway.time_s == pytest.approx(3600)
    assert track.locate_time(1800).distance_m / METERS_PER_MILE == pytest.approx(25)
    # Out-of-range queries clamp to the ends.
    assert track.locate(-5).distance_m == 0
    assert track.locate_time(10**9).distance_m == pytest.approx(track.distance_m)


def test_router_durations_are_rescaled_to_route_total():
    coords = [(0, 0), (0.1, 0), (0.2, 0)]
    track = build_track(coords, total_duration_s=300, segment_durations_s=[50, 100])

    assert track.cum_time_s == pytest.approx((0, 100, 300))


def test_misaligned_annotations_fall_back_to_distance_weighting():
    coords = [(0, 0), (0.1, 0), (0.3, 0)]
    track = build_track(coords, total_duration_s=300, segment_durations_s=[1, 2, 3])

    assert track.cum_time_s == pytest.approx((0, 100, 300))


def test_truck_speed_cap_slows_fast_segments():
    # Router says 100 miles in 1h (100 mph); capped at 50 mph it takes 2h.
    track = straight_track(miles=100, hours=1, max_speed_mph=50)
    assert track.duration_s == pytest.approx(7200, rel=1e-3)


def test_checkpoints_every_interval_plus_destination():
    track = straight_track(miles=103, hours=2)

    cps = sample_checkpoints(track, interval_miles=10)

    assert [round(c.mile) for c in cps] == [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 103]
    assert sum(c.represents_miles for c in cps) == pytest.approx(103)
    assert cps[0].represents_miles == pytest.approx(5)
    assert cps[5].represents_miles == pytest.approx(10)
    assert cps[-1].represents_miles == pytest.approx(1.5)
    assert cps[-1].eta_offset_s == pytest.approx(7200)


def test_destination_close_to_last_sample_is_merged():
    track = straight_track(miles=100.2, hours=2)

    cps = sample_checkpoints(track, interval_miles=10)

    assert len(cps) == 11
    assert cps[-1].mile == pytest.approx(100.2)


def test_short_route_still_has_origin_and_destination():
    cps = sample_checkpoints(straight_track(miles=3, hours=0.1), interval_miles=50)

    assert [round(c.mile) for c in cps] == [0, 3]
    assert sum(c.represents_miles for c in cps) == pytest.approx(3)


def test_simplify_drops_collinear_points_but_keeps_corners():
    coords = [(i * 0.01, 0.0) for i in range(50)] + [(0.49, i * 0.01) for i in range(1, 50)]

    kept = simplify_indices(coords, tolerance_m=10)

    assert kept == [0, 49, 98]


def test_shared_fraction_detects_overlap():
    a = build_track([(0, 0), (1, 0)], total_duration_s=3600)
    same = build_track([(0, 0), (1, 0)], total_duration_s=3000)
    half = build_track([(0, 0), (0.5, 0), (0.5, 1)], total_duration_s=3600)
    apart = build_track([(0, 0.5), (1, 0.5)], total_duration_s=3600)

    assert shared_fraction(a, same) == pytest.approx(1.0)
    assert shared_fraction(a, half) == pytest.approx(0.5, abs=0.03)
    assert shared_fraction(a, apart) == 0
