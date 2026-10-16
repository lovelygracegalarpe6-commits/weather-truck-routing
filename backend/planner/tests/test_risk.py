import pytest

from planner.domain.risk import (
    RiskLevel,
    WeatherSample,
    assess,
    classify_rain,
    classify_snow,
    classify_wind,
    wind_level_for_load,
)

L, M, H, S, N = (
    RiskLevel.LOW,
    RiskLevel.MODERATE,
    RiskLevel.HIGH,
    RiskLevel.SEVERE,
    RiskLevel.NO_TRAVEL,
)


def sample(wind=0.0, rain=0.0, snow=0.0, gust=None):
    return WeatherSample(
        wind_mph=wind,
        gust_mph=wind if gust is None else gust,
        rain_in_hr=rain,
        snow_in_hr=snow,
    )


@pytest.mark.parametrize(
    ("mph", "expected"),
    [
        (0, L),
        (24.9, L),
        (25, M),
        (34, M),
        (34.9, M),
        (35, H),
        (44.9, H),
        (45, S),
        (54.9, S),
        (55, N),
        (80, N),
    ],
)
def test_wind_bands_are_lower_bound_inclusive(mph, expected):
    assert classify_wind(mph) == expected


@pytest.mark.parametrize(
    ("rate", "expected"),
    [
        (0, L),
        (0.099, L),
        (0.10, M),
        (0.25, M),
        (0.251, H),
        (0.50, H),
        (0.51, S),
        (1.00, S),
        (1.01, N),
    ],
)
def test_rain_bands_are_upper_bound_inclusive(rate, expected):
    assert classify_rain(rate) == expected


@pytest.mark.parametrize(
    ("rate", "expected"),
    [
        (0, L),
        (0.49, L),
        (0.5, M),
        (1.0, M),
        (1.01, H),
        (2.0, H),
        (2.01, S),
        (3.0, S),
        (3.01, N),
    ],
)
def test_snow_bands_are_upper_bound_inclusive(rate, expected):
    assert classify_snow(rate) == expected


@pytest.mark.parametrize(
    ("mph", "load", "expected"),
    [
        # >= 55 mph is No Travel for any load
        (55, 0, N),
        (60, 10_000, N),
        # 45-54 mph: No Travel only above 30,000 lb
        (45, 30_000, S),
        (45, 30_001, N),
        (54.9, 45_000, N),
        # 35-44 mph: Severe only above 40,000 lb
        (35, 40_000, H),
        (35, 40_001, S),
        (44.9, 80_000, S),
        # Load rules never apply outside their wind bands
        (34.9, 80_000, M),
        (10, 80_000, L),
    ],
)
def test_load_rules_escalate_wind(mph, load, expected):
    level, _ = wind_level_for_load(mph, load)
    assert level == expected


def test_checkpoint_level_is_worst_condition():
    result = assess(sample(wind=26, rain=0.3, snow=0.6), load_lb=10_000)

    assert (result.wind, result.rain, result.snow) == (M, H, M)
    assert result.level == H
    assert result.reasons == ("Rain 0.30 in/hr",)


def test_reasons_mention_load_rule_when_it_drives_the_level():
    result = assess(sample(wind=40), load_lb=42_000)

    assert result.level == S
    assert result.reasons == ("Wind 40 mph with 42,000 lb load (> 40,000 lb)",)


def test_reasons_list_every_condition_tied_for_worst():
    result = assess(sample(wind=36, rain=0.4), load_lb=0)

    assert result.level == H
    assert result.reasons == ("Wind 36 mph", "Rain 0.40 in/hr")


def test_calm_weather_has_no_reasons():
    result = assess(sample(wind=5), load_lb=80_000)

    assert result.level == L
    assert result.reasons == ()


def test_gust_metric_uses_gust_speed():
    weather = sample(wind=20, gust=50)

    assert assess(weather, load_lb=0).level == L
    assert assess(weather, load_lb=0, wind_metric="gust").level == S
    assert assess(weather, load_lb=35_000, wind_metric="gust").level == N
