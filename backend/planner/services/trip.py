"""Plan a trip: routes -> checkpoints -> ETA-aligned weather -> risk -> recommendation."""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.utils import timezone

from planner.domain.checkpoints import CheckpointPosition, sample_checkpoints
from planner.domain.geo import METERS_PER_MILE, haversine_m, simplify_indices
from planner.domain.recommendation import (
    RouteRiskSummary,
    explain,
    rank_routes,
    summarize_route,
    warnings_for,
)
from planner.domain.risk import RiskAssessment, WeatherSample, assess
from planner.errors import InvalidTripError
from planner.providers import routing, weather
from planner.providers.routing import RouteOption

from .serialization import iso_utc, level_key

logger = logging.getLogger(__name__)

MAX_DAYS_AHEAD = 7  # keeps whole trips inside the 16-day forecast with room to spare
MAX_HOURS_IN_PAST = 6
MIN_TRIP_KM = 1.0
PATH_TOLERANCE_M = 25.0  # simplification for the map; checkpoints use the full track
ROUTE_IDS = "ABC"


@dataclass(frozen=True)
class Location:
    lat: float
    lon: float
    label: str = ""

    @property
    def lonlat(self) -> tuple[float, float]:
        return (self.lon, self.lat)


@dataclass(frozen=True)
class TripRequest:
    origin: Location
    destination: Location
    departure: datetime | None  # naive = origin-local wall time; aware = absolute; None = now
    load_weight_lb: float
    interval_miles: int


def resolve_departure(departure: datetime | None, tz_name: str, now: datetime) -> datetime:
    """Absolute UTC departure; naive inputs are wall-clock time at the origin."""
    if departure is None:
        return now.replace(second=0, microsecond=0)
    if departure.tzinfo is None:
        try:
            departure = departure.replace(tzinfo=ZoneInfo(tz_name))
        except ZoneInfoNotFoundError:
            departure = departure.replace(tzinfo=UTC)
    departure = departure.astimezone(UTC)

    if departure < now - timedelta(hours=MAX_HOURS_IN_PAST):
        raise InvalidTripError("Departure time is in the past (in the origin's local time).")
    if departure > now + timedelta(days=MAX_DAYS_AHEAD):
        raise InvalidTripError(
            f"Departure must be within {MAX_DAYS_AHEAD} days so the whole trip is forecast."
        )
    return departure


def _checkpoint_payload(
    cp: CheckpointPosition,
    eta: datetime,
    sample: WeatherSample | None,
    risk: RiskAssessment | None,
) -> dict:
    return {
        "index": cp.index,
        "mile": round(cp.mile, 1),
        "lat": round(cp.lat, 5),
        "lon": round(cp.lon, 5),
        "eta_utc": iso_utc(eta),
        "eta_offset_s": round(cp.eta_offset_s),
        "represents_miles": round(cp.represents_miles, 2),
        "level": level_key(risk.level) if risk else None,
        "levels": (
            {"wind": risk.wind.key, "rain": risk.rain.key, "snow": risk.snow.key} if risk else None
        ),
        "reasons": list(risk.reasons) if risk else [],
        "weather": (
            {
                "wind_mph": round(sample.wind_mph, 1),
                "gust_mph": round(sample.gust_mph, 1),
                "rain_in_hr": round(sample.rain_in_hr, 3),
                "snow_in_hr": round(sample.snow_in_hr, 3),
            }
            if sample
            else None
        ),
    }


def _route_payload(
    route_id: str,
    option: RouteOption,
    departure: datetime,
    checkpoints: list[dict],
    summary: RouteRiskSummary,
) -> dict:
    track = option.track
    keep = simplify_indices(track.coords, PATH_TOLERANCE_M)
    return {
        "id": route_id,
        "name": summary.name,
        "summary": option.summary,
        "source": option.source,
        "distance_mi": round(track.distance_m / METERS_PER_MILE, 1),
        "duration_s": round(track.duration_s),
        "arrival_utc": iso_utc(departure + timedelta(seconds=track.duration_s)),
        "stats": {
            "miles_by_level": {
                level.key: round(miles, 1) for level, miles in summary.miles_by_level.items()
            },
            "unknown_miles": round(summary.unknown_miles, 1),
            "average_risk": (
                round(summary.average_risk, 3) if summary.average_risk is not None else None
            ),
            "max_level": level_key(summary.max_level),
        },
        "path": [[round(track.coords[i][0], 5), round(track.coords[i][1], 5)] for i in keep],
        "path_times_s": [round(track.cum_time_s[i]) for i in keep],
        "checkpoints": checkpoints,
    }


def plan_trip(request: TripRequest, now: datetime | None = None) -> dict:
    now = now or timezone.now()
    origin, destination = request.origin, request.destination
    if haversine_m(origin.lonlat, destination.lonlat) < MIN_TRIP_KM * 1000:
        raise InvalidTripError("Origin and destination are the same place.")

    # The origin's timezone and the routes are independent: fetch them concurrently.
    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=1) as pool:
        tz_future = pool.submit(weather.lookup_timezone, origin.lat, origin.lon)
        options = routing.fetch_route_options(
            origin.lonlat, destination.lonlat, max_speed_mph=settings.TRUCK_MAX_SPEED_MPH
        )
        tz_name = tz_future.result()
    t1 = time.perf_counter()
    departure = resolve_departure(request.departure, tz_name, now)

    route_checkpoints = [sample_checkpoints(o.track, request.interval_miles) for o in options]
    snapped = [[weather.snap((cp.lat, cp.lon)) for cp in cps] for cps in route_checkpoints]
    forecasts = weather.fetch_forecasts([p for points in snapped for p in points])
    logger.info(
        "Planned %d routes: routing %.1fs, weather %.1fs for %d locations",
        len(options),
        t1 - t0,
        time.perf_counter() - t1,
        len(forecasts),
    )

    summaries: list[RouteRiskSummary] = []
    routes: list[dict] = []
    for route_id, option, cps, points in zip(
        ROUTE_IDS, options, route_checkpoints, snapped, strict=False
    ):
        payloads, risks = [], []
        for cp, point in zip(cps, points, strict=True):
            eta = departure + timedelta(seconds=cp.eta_offset_s)
            sample = forecasts[point].sample_at(eta.timestamp()) if point in forecasts else None
            risk = assess(sample, request.load_weight_lb, settings.WIND_METRIC) if sample else None
            risks.append((risk.level if risk else None, cp.represents_miles))
            payloads.append(_checkpoint_payload(cp, eta, sample, risk))

        summary = summarize_route(route_id, f"Route {route_id}", risks, option.track.duration_s)
        summaries.append(summary)
        routes.append(_route_payload(route_id, option, departure, payloads, summary))

    ranked = rank_routes(summaries)
    best = ranked[0]
    rank_of = {s.route_id: i + 1 for i, s in enumerate(ranked)}
    for route in routes:
        route["rank"] = rank_of[route["id"]]
        route["recommended"] = route["id"] == best.route_id

    return {
        "trip": {
            "origin": {"lat": origin.lat, "lon": origin.lon, "label": origin.label},
            "destination": {
                "lat": destination.lat,
                "lon": destination.lon,
                "label": destination.label,
            },
            "departure_utc": iso_utc(departure),
            "timezone": tz_name,
            "load_weight_lb": request.load_weight_lb,
            "interval_miles": request.interval_miles,
            "wind_metric": settings.WIND_METRIC,
            "truck_max_speed_mph": settings.TRUCK_MAX_SPEED_MPH,
        },
        "recommendation": {
            "route_id": best.route_id,
            "comparisons": [
                {"other_route_id": c.other_route_id, "criterion": c.criterion, "text": c.text}
                for c in explain(best, ranked[1:])
            ],
            "warnings": warnings_for(best),
        },
        "routes": routes,
        "generated_at": iso_utc(now),
    }
