class PlannerError(Exception):
    """Base error whose message is safe to show to the user."""

    status_code = 400
    code = "planner_error"


class InvalidTripError(PlannerError):
    code = "invalid_trip"


class NoRouteError(PlannerError):
    status_code = 422
    code = "no_route"


class UpstreamError(PlannerError):
    """A third-party API (routing, geocoding, weather) failed or rate-limited us."""

    status_code = 502
    code = "upstream_error"
