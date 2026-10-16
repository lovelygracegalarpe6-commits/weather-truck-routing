"""Hourly forecasts from Open-Meteo (free, no key, many locations per request).

Units requested from the API match the risk rules directly: mph and inches.
* `rain` + `showers` = liquid precipitation in the preceding hour  -> in/hr
* `snowfall`        = snowfall in the preceding hour (inches)      -> in/hr
* `wind_speed_10m` / `wind_gusts_10m` are instantaneous values on the hour.
"""

from __future__ import annotations

import math
from bisect import bisect_left
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime

from django.conf import settings
from django.core.cache import cache

from planner.domain.risk import WeatherSample
from planner.errors import InvalidTripError, UpstreamError

from .http import get_json

HOUR = 3600
BATCH_SIZE = 100  # locations per HTTP request (keeps URLs well under limits)
MAX_WORKERS = 4
CACHE_SECONDS = 30 * 60  # forecasts update roughly hourly
MAX_LOCATIONS = 600  # Open-Meteo free tier allows 600 calls/minute
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


def snap(point: LatLon, resolution_deg: float = 0.05) -> LatLon:
    """Snap to a lattice so nearby checkpoints share a forecast (and a cache entry).

    0.05 deg is ~5 km, comparable to the forecast models' own grid spacing.
    """
    lat, lon = point
    return (
        round(round(lat / resolution_deg) * resolution_deg, 4),
        round(round(lon / resolution_deg) * resolution_deg, 4),
    )


def _iso_hour(t: float) -> str:
    return datetime.fromtimestamp(t, tz=UTC).strftime("%Y-%m-%dT%H:00")


def _cache_key(point: LatLon, start: str, end: str) -> str:
    return f"wx:{point[0]:.4f}:{point[1]:.4f}:{start}:{end}"


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


def _fetch_batch(points: Sequence[LatLon], start: str, end: str) -> list[HourlySeries]:
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
            "start_hour": start,
            "end_hour": end,
        },
        provider="Weather service",
    )
    items = payload if isinstance(payload, list) else [payload]
    if len(items) != len(points):
        raise UpstreamError("Weather service returned an unexpected number of locations.")
    return [_parse(item) for item in items]


def fetch_hourly(
    points: Sequence[LatLon], start_unix: float, end_unix: float
) -> dict[LatLon, HourlySeries]:
    """Hourly series covering [start, end] for each (already snapped) point."""
    start = _iso_hour(math.floor(start_unix / HOUR) * HOUR - HOUR)
    end = _iso_hour(math.ceil(end_unix / HOUR) * HOUR + HOUR)

    unique = list(dict.fromkeys(points))
    result: dict[LatLon, HourlySeries] = {}
    missing = []
    for p in unique:
        hit = cache.get(_cache_key(p, start, end))
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
        for batch, series_list in zip(
            batches, pool.map(lambda b: _fetch_batch(b, start, end), batches), strict=True
        ):
            for p, series in zip(batch, series_list, strict=True):
                result[p] = series
                cache.set(_cache_key(p, start, end), series, timeout=CACHE_SECONDS)
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
        )
        tz = payload.get("timezone") or "UTC"
        cache.set(key, tz, timeout=7 * 24 * 3600)
    return tz
