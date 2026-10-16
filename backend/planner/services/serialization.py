"""Small helpers that turn domain values into JSON-friendly primitives."""

from __future__ import annotations

from datetime import UTC, datetime

from planner.domain.risk import RiskLevel


def iso_utc(value: datetime | float) -> str:
    if not isinstance(value, datetime):
        value = datetime.fromtimestamp(value, tz=UTC)
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def level_key(level: RiskLevel | None) -> str | None:
    return None if level is None else level.key
