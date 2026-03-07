"""Async shape probe executor.

Fires a GET request from a ProbeTemplate with injected auth,
parses the JSON response, and returns a structured ProbeResult.
Only GET is allowed (read-only probes for drift detection).
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode, urljoin

import httpx

from toolwright.models.probe_template import ProbeTemplate

logger = logging.getLogger("toolwright.drift.probe_executor")

# Default limits
DEFAULT_TIMEOUT: float = 15.0
DEFAULT_MAX_RESPONSE_BYTES: int = 5 * 1024 * 1024  # 5 MB


@dataclass
class ProbeResult:
    """Result of a single shape probe."""

    ok: bool
    status_code: int | None = None
    body: Any = None
    error: str | None = None


async def execute_probe(
    template: ProbeTemplate,
    host: str,
    *,
    client: httpx.AsyncClient | None = None,
    auth_header: str | None = None,
    extra_headers: dict[str, str] | None = None,
    base_url: str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
) -> ProbeResult:
    """Execute a shape probe from a ProbeTemplate.

    Args:
        template: Sanitized probe template (method, path, query_params, headers).
        host: Target API host (e.g. "api.example.com").
        client: Optional httpx.AsyncClient (created internally if None).
        auth_header: Authorization header value to inject.
        extra_headers: Additional headers to merge.
        base_url: Override base URL (e.g. "http://localhost:8080").
        timeout: Request timeout in seconds.
        max_response_bytes: Maximum response size before rejecting.

    Returns:
        ProbeResult with parsed JSON body on success, or error details.
    """
    # Only GET probes are allowed (safety: read-only)
    if template.method.upper() != "GET":
        return ProbeResult(
            ok=False,
            error=f"Only GET probes are allowed, got {template.method.upper()}",
        )

    # Build URL
    if base_url:
        url = urljoin(base_url.rstrip("/") + "/", template.path.lstrip("/"))
    else:
        url = f"https://{host}{template.path}"

    if template.query_params:
        url = f"{url}?{urlencode(template.query_params)}"

    # Build headers
    headers: dict[str, str] = {"User-Agent": "Toolwright/1.0"}
    headers.update(template.headers)
    if extra_headers:
        headers.update(extra_headers)
    if auth_header:
        headers["Authorization"] = auth_header

    # Execute request
    owns_client = client is None
    if owns_client:
        client = httpx.AsyncClient(timeout=timeout)

    try:
        response = await client.request(
            "GET",
            url,
            headers=headers,
            timeout=timeout,
            follow_redirects=False,
        )
    except (httpx.TimeoutException, httpx.ConnectTimeout, httpx.ReadTimeout):
        return ProbeResult(ok=False, error=f"Timeout after {timeout}s")
    except httpx.HTTPError as exc:
        return ProbeResult(ok=False, error=f"HTTP error: {exc}")
    finally:
        if owns_client:
            await client.aclose()

    # Check status
    if response.status_code != 200:
        return ProbeResult(
            ok=False,
            status_code=response.status_code,
            error=f"Non-200 status: {response.status_code}",
        )

    # Check content-length before parsing
    raw_cl = response.headers.get("content-length")
    if raw_cl and int(raw_cl) > max_response_bytes:
        return ProbeResult(
            ok=False,
            status_code=response.status_code,
            error=f"Response size {raw_cl} bytes exceeds limit of {max_response_bytes}",
        )

    # Check content type
    content_type = response.headers.get("content-type", "")
    if "json" not in content_type.lower():
        return ProbeResult(
            ok=False,
            status_code=response.status_code,
            error=f"Expected JSON content-type, got: {content_type}",
        )

    # Parse JSON
    try:
        body = response.json()
    except (json.JSONDecodeError, ValueError) as exc:
        return ProbeResult(
            ok=False,
            status_code=response.status_code,
            error=f"Failed to parse JSON response: {exc}",
        )

    return ProbeResult(
        ok=True,
        status_code=response.status_code,
        body=body,
    )
