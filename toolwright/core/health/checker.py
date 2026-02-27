"""Health checker for tool endpoints.

Non-mutating probes to verify that API endpoints behind tools
are reachable and responding. Uses HEAD for read endpoints and
OPTIONS for write endpoints to avoid side effects.
"""

from __future__ import annotations

import asyncio
import re
import time
from enum import StrEnum

from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Failure classification
# ---------------------------------------------------------------------------


class FailureClass(StrEnum):
    """Known failure categories for health probes."""

    AUTH_EXPIRED = "auth_expired"
    ENDPOINT_GONE = "endpoint_gone"
    RATE_LIMITED = "rate_limited"
    SERVER_ERROR = "server_error"
    NETWORK_UNREACHABLE = "network_unreachable"
    SCHEMA_CHANGED = "schema_changed"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Health result
# ---------------------------------------------------------------------------


class HealthResult(BaseModel):
    """Outcome of a single health probe."""

    tool_id: str
    healthy: bool
    failure_class: FailureClass | None = None
    status_code: int | None = None
    response_time_ms: float = 0.0
    error_message: str | None = None


# ---------------------------------------------------------------------------
# Health checker
# ---------------------------------------------------------------------------

# Status codes that indicate a healthy response
_HEALTHY_CODES = frozenset(range(200, 400))

# Path parameter pattern: {param_name}
_PATH_PARAM_RE = re.compile(r"\{[^}]+\}")


class HealthChecker:
    """Non-mutating health prober for API endpoints.

    Uses HEAD for GET endpoints and OPTIONS for POST/PUT/DELETE/PATCH
    to avoid any side effects.
    """

    def __init__(
        self,
        *,
        scheme: str = "https",
        timeout_seconds: float = 10.0,
        max_concurrent: int = 5,
    ) -> None:
        self.scheme = scheme
        self.timeout_seconds = timeout_seconds
        self.max_concurrent = max_concurrent

    # -- Public API --------------------------------------------------------

    async def check_tool(self, action: dict) -> HealthResult:
        """Probe a single tool's endpoint.

        Args:
            action: Dict with ``name``, ``method``, ``host``, ``path`` keys.

        Returns:
            HealthResult with probe outcome.
        """
        tool_id = action.get("name", "unknown")
        method = action.get("method", "GET").upper()
        probe_method = self._probe_method(method)
        url = self._build_probe_url(action)

        status_code, response_time_ms, error = await self._send_probe(
            probe_method, url, self.timeout_seconds
        )

        if error is not None:
            failure = self.classify_failure(status_code, error=error)
            return HealthResult(
                tool_id=tool_id,
                healthy=False,
                failure_class=failure,
                status_code=status_code,
                response_time_ms=response_time_ms,
                error_message=error,
            )

        if status_code is not None and status_code in _HEALTHY_CODES:
            return HealthResult(
                tool_id=tool_id,
                healthy=True,
                status_code=status_code,
                response_time_ms=response_time_ms,
            )

        failure = self.classify_failure(status_code)
        return HealthResult(
            tool_id=tool_id,
            healthy=False,
            failure_class=failure,
            status_code=status_code,
            response_time_ms=response_time_ms,
        )

    async def check_all(self, actions: list[dict]) -> list[HealthResult]:
        """Probe multiple endpoints concurrently with rate limiting.

        Args:
            actions: List of action dicts.

        Returns:
            List of HealthResult in same order as input.
        """
        if not actions:
            return []

        semaphore = asyncio.Semaphore(self.max_concurrent)

        async def bounded_check(action: dict) -> HealthResult:
            async with semaphore:
                return await self.check_tool(action)

        tasks = [bounded_check(a) for a in actions]
        return list(await asyncio.gather(*tasks))

    # -- Classification ----------------------------------------------------

    @staticmethod
    def classify_failure(
        status_code: int | None, *, error: str | None = None
    ) -> FailureClass:
        """Map a status code or error string to a FailureClass."""
        if error is not None:
            lower = error.lower()
            if any(kw in lower for kw in ("connect", "timeout", "dns", "refused")):
                return FailureClass.NETWORK_UNREACHABLE
            if status_code is None:
                return FailureClass.UNKNOWN

        if status_code is None:
            return FailureClass.UNKNOWN

        if status_code in (401, 403):
            return FailureClass.AUTH_EXPIRED
        if status_code in (404, 410):
            return FailureClass.ENDPOINT_GONE
        if status_code == 429:
            return FailureClass.RATE_LIMITED
        if 500 <= status_code < 600:
            return FailureClass.SERVER_ERROR

        return FailureClass.UNKNOWN

    # -- Internal ----------------------------------------------------------

    def _probe_method(self, original_method: str) -> str:
        """Choose a safe probe method.

        GET -> HEAD (safe, same endpoint)
        POST/PUT/DELETE/PATCH -> OPTIONS (no side effects)
        """
        if original_method.upper() == "GET":
            return "HEAD"
        return "OPTIONS"

    def _build_probe_url(self, action: dict) -> str:
        """Build URL for probe, replacing path params with placeholder."""
        host = action.get("host", "localhost")
        path = action.get("path", "/")
        # Replace {param} placeholders with a safe value
        path = _PATH_PARAM_RE.sub("_probe_", path)
        return f"{self.scheme}://{host}{path}"

    async def _send_probe(
        self, method: str, url: str, timeout: float
    ) -> tuple[int | None, float, str | None]:
        """Send the actual HTTP probe.

        Returns (status_code, response_time_ms, error_string_or_None).
        """
        try:
            import httpx
        except ImportError:
            return (None, 0.0, "httpx not installed")

        start = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.request(method, url)
                elapsed = (time.monotonic() - start) * 1000
                return (response.status_code, elapsed, None)
        except Exception as exc:
            elapsed = (time.monotonic() - start) * 1000
            return (None, elapsed, f"{type(exc).__name__}: {exc}")
