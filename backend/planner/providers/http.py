"""Shared HTTP session: identifies the app, retries transient failures, enforces timeouts."""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

import requests
from django.conf import settings
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from planner.errors import UpstreamError

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def session() -> requests.Session:
    s = requests.Session()
    retry = Retry(
        total=2,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=8, pool_maxsize=16)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    s.headers.update({"User-Agent": settings.HTTP_USER_AGENT, "Accept": "application/json"})
    return s


def get_json(url: str, params: dict[str, Any], provider: str) -> Any:
    """GET a JSON document or raise UpstreamError with a user-safe message."""
    try:
        response = session().get(url, params=params, timeout=settings.HTTP_TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        raise UpstreamError(f"{provider} is unreachable right now. Please try again.") from exc

    if response.status_code == 429:
        raise UpstreamError(f"{provider} rate limit reached. Please wait a minute and retry.")
    if response.status_code >= 500:
        raise UpstreamError(f"{provider} is having problems (HTTP {response.status_code}).")
    try:
        payload = response.json()
    except ValueError as exc:
        raise UpstreamError(f"{provider} returned an unreadable response.") from exc
    if response.status_code >= 400:
        logger.warning("%s rejected request %s: %s", provider, response.url, payload)
        reason = (
            (payload.get("reason") or payload.get("message")) if isinstance(payload, dict) else ""
        )
        raise UpstreamError(f"{provider} rejected the request: {reason or response.status_code}")
    return payload
