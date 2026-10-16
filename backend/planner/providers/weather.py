"""Hourly forecasts from Open-Meteo (free, no key, many locations per request).

Units requested from the API match the risk rules directly: mph and inches.
* `rain` + `showers` = liquid precipitation in the preceding hour  -> in/hr
* `snowfall`        = snowfall in the preceding hour (inches)      -> in/hr
* `wind_speed_10m` / `wind_gusts_10m` are instantaneous values on the hour.
"""

from __future__ import annotations

from bisect import bisect_left
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from django.conf import settings
from django.core.cache import cache

from planner.domain.risk import WeatherSample
from planner.errors import InvalidTripError, UpstreamError

from .http import get_json

HOUR = 3600
# Small batches in parallel: Open-Meteo latency grows with locations per request.
BATCH_SIZE = 25
MAX_WORKERS = 8
CACHE_SECONDS = 60 * 60  # models update hourly at best
# The free tier counts every location as one call: 600 per minute.
MAX_LOCATIONS = 600
# One fixed window per location: departures may be up to 6 h in the past or 7 days
# ahead, plus up to ~2 days of driving.
PAST_HOURS = 8
FORECAST_HOURS = 9 * 24
SNAP_DEG = 0.1
READ_TIMEOUT_SECONDS = 8.0  # normally < 2 s; fail fast and retry on a stalled connection
HOURLY_VARS = "wind_speed_10m,wind_gusts_10m,rain,showers,snowfall"

LatLon = tuple[float, float]


@dataclass(frozen=True)
class HourlySeries:
    times: tuple[int, ...]  # unix seconds, on the hour, ascending
    wind_mph: tuple[float | None, ...]
    gust_mph: tuple[float | None, ...]
    rain_in_hr: tuple[float | None, ...]
    snow_in_hr: tuple[float | None, ...]

    def sample_at(self, t: float) -> WeatherSample | None:
        """Weather at unix time `t`, or None outside the forecast.

        Wind is interpolated linearly between the bracketing hours. Precipitation
        values are totals for the hour *ending* at their timestamp, so time `t` uses
        the bucket stamped at the next full hour.
        """
        if not self.times or t < self.times[0] - HOUR or t > self.times[-1]:
            return None
        i = bisect_left(self.times, t)  # first hour >= t  (the precip bucket)
        i = min(i, len(self.times) - 1)
        rain, snow = self.rain_in_hr[i], self.snow_in_hr[i]

        lo = max(i - 1, 0) if self.times[i] > t else i
        hi = i
        span = self.times[hi] - self.times[lo]
        f = (t - self.times[lo]) / span if span else 0.0
        wind = _lerp(self.wind_mph[lo], self.wind_mph[hi], f)
        gust = _lerp(self.gust_mph[lo], self.gust_mph[hi], f)

        if None in (wind, gust, rain, snow):
            return None
        return WeatherSample(wind_mph=wind, gust_mph=gust, rain_in_hr=rain, snow_in_hr=snow)


def _lerp(a: float | None, b: float | None, f: float) -> float | None:
    if a is None or b is None:
        return a if f < 0.5 else b
    return a + (b - a) * f


def snap(point: LatLon, resolution_deg: float = SNAP_DEG) -> LatLon:
    """Snap to a lattice so nearby checkpoints share a forecast (and a cache entry).

    0.1 deg is ~11 km, so a checkpoint's forecast comes from at most ~7 km away;
    the heatmap grid uses multiples of the same lattice and shares cache entries.
    """
    lat, lon = point
    return (
        round(round(lat / resolution_deg) * resolution_deg, 4),
        round(round(lon / resolution_deg) * resolution_deg, 4),
    )


def _cache_key(point: LatLon) -> str:
    return f"wx:{point[0]:.4f}:{point[1]:.4f}"


def _parse(item: dict) -> HourlySeries:
    hourly = item.get("hourly", {})
    rain = hourly.get("rain", [])
    showers = hourly.get("showers", [])
    return HourlySeries(
        times=tuple(hourly.get("time", [])),
        wind_mph=tuple(hourly.get("wind_speed_10m", [])),
        gust_mph=tuple(hourly.get("wind_gusts_10m", [])),
        rain_in_hr=tuple(
            None if r is None and s is None else (r or 0.0) + (s or 0.0)
            for r, s in zip(rain, showers, strict=True)
        ),
        snow_in_hr=tuple(hourly.get("snowfall", [])),
    )


def _fetch_batch(points: Sequence[LatLon]) -> list[HourlySeries]:
    payload = get_json(
        f"{settings.OPEN_METEO_BASE_URL}/v1/forecast",
        {
            "latitude": ",".join(f"{lat:.4f}" for lat, _ in points),
            "longitude": ",".join(f"{lon:.4f}" for _, lon in points),
            "hourly": HOURLY_VARS,
            "wind_speed_unit": "mph",
            "precipitation_unit": "inch",
            "timeformat": "unixtime",
            "timezone": "GMT",
            "past_hours": PAST_HOURS,
            "forecast_hours": FORECAST_HOURS,
        },
        provider="Weather service",
        read_timeout=READ_TIMEOUT_SECONDS,
    )
    items = payload if isinstance(payload, list) else [payload]
    if len(items) != len(points):
        raise UpstreamError("Weather service returned an unexpected number of locations.")
    return [_parse(item) for item in items]


def fetch_forecasts(points: Sequence[LatLon]) -> dict[LatLon, HourlySeries]:
    """Hourly series for each (already snapped) point over the whole planning window.

    The window is the same for every request, so a cached location serves any
    departure time: changing departure or load weight costs no extra API calls.
    """
    unique = list(dict.fromkeys(points))
    result: dict[LatLon, HourlySeries] = {}
    missing = []
    for p in unique:
        hit = cache.get(_cache_key(p))
        if hit is None:
            missing.append(p)
        else:
            result[p] = hit

    if len(missing) > MAX_LOCATIONS:
        raise InvalidTripError(
            f"This trip needs forecasts for {len(missing)} locations, more than the weather "
            "service allows per minute. Choose a larger checkpoint interval."
        )

    batches = [missing[i : i + BATCH_SIZE] for i in range(0, len(missing), BATCH_SIZE)]
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        for batch, series_list in zip(batches, pool.map(_fetch_batch, batches), strict=True):
            for p, series in zip(batch, series_list, strict=True):
                result[p] = series
                cache.set(_cache_key(p), series, timeout=CACHE_SECONDS)
    return result


def lookup_timezone(lat: float, lon: float) -> str:
    """IANA timezone name for a location (used to interpret local departure times)."""
    key = f"tz:{lat:.2f}:{lon:.2f}"
    tz = cache.get(key)
    if tz is None:
        payload = get_json(
            f"{settings.OPEN_METEO_BASE_URL}/v1/forecast",
            {"latitude": f"{lat:.4f}", "longitude": f"{lon:.4f}", "timezone": "auto"},
            provider="Weather service",
            read_timeout=READ_TIMEOUT_SECONDS,
        )
        tz = payload.get("timezone") or "UTC"
        cache.set(key, tz, timeout=7 * 24 * 3600)
    return tz
