from django.conf import settings
from django.http import FileResponse, HttpRequest, HttpResponse, JsonResponse
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView


class HealthView(APIView):
    throttle_classes: list = []

    def get(self, request: Request) -> Response:
        return Response({"status": "ok"})


def spa_index(request: HttpRequest) -> HttpResponse:
    """Serve the built React app, or point developers at the Vite dev server."""
    index = settings.FRONTEND_DIST_DIR / "index.html"
    if index.exists():
        return FileResponse(index.open("rb"), content_type="text/html")
    return JsonResponse(
        {"detail": "Frontend build not found. In development use the Vite dev server."},
        status=404,
    )
