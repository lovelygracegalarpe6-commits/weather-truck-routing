"""Place search via Photon (OpenStreetMap data, free, no key, autocomplete-friendly)."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass

from django.conf import settings
from django.core.cache import cache

from .http import get_json

# Bias results toward the contiguous US (the app's units and truck rules are US-centric).
_BIAS_LAT, _BIAS_LON = 39.8, -98.6


@dataclass(frozen=True)
class Place:
    label: str
    lat: float
    lon: float


def _label(props: dict) -> str:
    street = " ".join(p for p in (props.get("housenumber"), props.get("street")) if p)
    parts = [
        props.get("name") or street,
        props.get("city") if props.get("city") != props.get("name") else None,
        props.get("state"),
        props.get("countrycode", "").upper() or props.get("country"),
    ]
    seen: list[str] = []
    for part in parts:
        if part and part not in seen:
            seen.append(part)
    return ", ".join(seen)


def search_places(query: str, limit: int = 6) -> list[Place]:
    query = query.strip()
    if len(query) < 2:
        return []
    key = "geo:" + hashlib.sha1(f"{query.lower()}|{limit}".encode()).hexdigest()
    cached = cache.get(key)
    if cached is not None:
        return [Place(**p) for p in cached]

    payload = get_json(
        f"{settings.PHOTON_BASE_URL}/api/",
        {"q": query, "limit": limit, "lang": "en", "lat": _BIAS_LAT, "lon": _BIAS_LON},
        provider="Geocoding service",
        read_timeout=8.0,
    )
    places: list[Place] = []
    for feature in payload.get("features", []):
        lon, lat = feature["geometry"]["coordinates"][:2]
        label = _label(feature.get("properties", {}))
        if label and all(p.label != label for p in places):
            places.append(Place(label=label, lat=round(lat, 6), lon=round(lon, 6)))

    cache.set(key, [asdict(p) for p in places], timeout=24 * 3600)
    return places
