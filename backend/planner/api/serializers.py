from datetime import datetime

from rest_framework import serializers

from planner.domain.checkpoints import ALLOWED_INTERVALS_MILES

MAX_LOAD_LB = 200_000
MAX_PATH_POINTS = 6_000


class LocationSerializer(serializers.Serializer):
    lat = serializers.FloatField(min_value=-90, max_value=90)
    lon = serializers.FloatField(min_value=-180, max_value=180)
    label = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")


class PlanRequestSerializer(serializers.Serializer):
    origin = LocationSerializer()
    destination = LocationSerializer()
    departure = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        default=None,
        help_text=(
            "ISO 8601. Without an offset (e.g. 2026-10-17T06:00) it is local time at the "
            "origin. Omit for 'leave now'."
        ),
    )
    load_weight_lb = serializers.FloatField(min_value=0, max_value=MAX_LOAD_LB)
    interval_miles = serializers.ChoiceField(choices=ALLOWED_INTERVALS_MILES, default=25)

    def validate_departure(self, value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value)
        except ValueError as exc:
            raise serializers.ValidationError(
                "Use ISO 8601, e.g. 2026-10-17T06:00 or 2026-10-17T11:00:00Z."
            ) from exc


class HeatmapRequestSerializer(serializers.Serializer):
    paths = serializers.ListField(
        child=serializers.ListField(
            child=serializers.ListField(child=serializers.FloatField(), min_length=2, max_length=2),
            min_length=2,
        ),
        min_length=1,
        max_length=3,
    )
    departure_utc = serializers.DateTimeField()
    load_weight_lb = serializers.FloatField(min_value=0, max_value=MAX_LOAD_LB)
    hours = serializers.IntegerField(min_value=1, max_value=48, default=48)

    def validate_paths(self, paths: list) -> list:
        if sum(len(p) for p in paths) > MAX_PATH_POINTS:
            raise serializers.ValidationError(f"At most {MAX_PATH_POINTS} points in total.")
        for path in paths:
            for lon, lat in path:
                if not (-180 <= lon <= 180 and -90 <= lat <= 90):
                    raise serializers.ValidationError("Coordinates must be [lon, lat] in degrees.")
        return [[(lon, lat) for lon, lat in path] for path in paths]
