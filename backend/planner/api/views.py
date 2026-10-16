from django.conf import settings
from django.http import FileResponse, HttpRequest, HttpResponse, JsonResponse
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle, ScopedRateThrottle
from rest_framework.views import APIView

from planner.providers.geocoding import search_places
from planner.services.heatmap import build_heatmap
from planner.services.trip import Location, TripRequest, plan_trip

from .serializers import HeatmapRequestSerializer, PlanRequestSerializer


class HealthView(APIView):
    throttle_classes: list = []

    def get(self, request: Request) -> Response:
        return Response({"status": "ok"})


class GeocodeView(APIView):
    def get(self, request: Request) -> Response:
        query = request.query_params.get("q", "")[:200]
        places = search_places(query)
        return Response({"results": [p.__dict__ for p in places]})


class PlanView(APIView):
    """Three route options with ETA-aligned checkpoint weather, risk and a recommendation."""

    throttle_classes = [AnonRateThrottle, ScopedRateThrottle]
    throttle_scope = "plan"

    def post(self, request: Request) -> Response:
        serializer = PlanRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        trip = TripRequest(
            origin=Location(**data["origin"]),
            destination=Location(**data["destination"]),
            departure=data["departure"],
            load_weight_lb=data["load_weight_lb"],
            interval_miles=data["interval_miles"],
        )
        return Response(plan_trip(trip))


class HeatmapView(APIView):
    """Hourly corridor weather/risk grid for the 0-48 h forecast slider."""

    throttle_classes = [AnonRateThrottle, ScopedRateThrottle]
    throttle_scope = "plan"

    def post(self, request: Request) -> Response:
        serializer = HeatmapRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        return Response(
            build_heatmap(
                data["paths"], data["departure_utc"], data["load_weight_lb"], data["hours"]
            )
        )


def spa_index(request: HttpRequest) -> HttpResponse:
    """Serve the built React app, or point developers at the Vite dev server."""
    index = settings.FRONTEND_DIST_DIR / "index.html"
    if index.exists():
        return FileResponse(index.open("rb"), content_type="text/html")
    return JsonResponse(
        {"detail": "Frontend build not found. In development use the Vite dev server."},
        status=404,
    )
