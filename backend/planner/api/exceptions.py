"""Map domain/provider failures onto consistent JSON error responses."""

import logging

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

from planner.errors import PlannerError

logger = logging.getLogger(__name__)


def exception_handler(exc: Exception, context: dict) -> Response | None:
    if isinstance(exc, PlannerError):
        if exc.status_code >= 500:
            logger.warning("Planner error: %s", exc, exc_info=exc.__cause__)
        return Response({"detail": str(exc), "code": exc.code}, status=exc.status_code)

    response = drf_exception_handler(exc, context)
    if response is None:
        logger.exception("Unhandled API error", exc_info=exc)
        return Response(
            {"detail": "Unexpected server error.", "code": "server_error"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
    return response
