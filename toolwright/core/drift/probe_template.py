"""Probe template extraction and sanitization for traffic-captured tools.

Extracts sanitized request templates from captured HTTP exchanges.
The key operation is sanitization — removing ephemeral/dynamic parameters
that would cause probe failures or false drift, while keeping structural
parameters that affect response shape.

SECURITY: Never stores credentials in probe templates. Headers like
x-api-key, authorization, and api-key are stripped aggressively.
"""

from __future__ import annotations

import re
import urllib.parse

from toolwright.models.probe_template import ProbeTemplate

# ---------------------------------------------------------------------------
# Query parameter lists
# ---------------------------------------------------------------------------

# Parameters to ALWAYS STRIP — ephemeral, will cause probe failures
STRIP_PARAMS: set[str] = {
    # Pagination cursors (ephemeral tokens)
    "page_info",
    "cursor",
    "after",
    "before",
    "next_page_token",
    "continuation_token",
    "start_after",
    "starting_after",
    "ending_before",
    "page_token",
    "scroll_id",
    # Timestamps and nonces
    "timestamp",
    "ts",
    "nonce",
    "_",  # cache busters
    "since",
    "until",  # time-scoped filters
    # Auth tokens that appear in query strings
    "access_token",
    "token",
    "api_key",
    "apikey",
    "key",
    "signature",
    "sig",
    "hmac",
    # Request IDs
    "request_id",
    "req_id",
    "trace_id",
    "correlation_id",
    "idempotency_key",
}

# Parameters to ALWAYS KEEP — these affect response shape
KEEP_PARAMS: set[str] = {
    # Field selection / expansion (CRITICAL — these change response shape)
    "fields",
    "include",
    "expand",
    "embed",
    "select",
    "exclude",
    "omit",
    # Filtering (affects which objects come back)
    "status",
    "state",
    "type",
    "kind",
    "category",
    "sort",
    "sort_by",
    "sort_order",
    "order",
    "order_by",
    "direction",
    # Pagination size (keep, but not cursors)
    "limit",
    "per_page",
    "page_size",
    "count",
    "max_results",
    "page",  # numeric page numbers are reproducible
    # API version (affects response shape)
    "api_version",
    "version",
    "v",
    # Format
    "format",
    "response_format",
}

# ---------------------------------------------------------------------------
# Header lists
# ---------------------------------------------------------------------------

# Headers that affect response shape — KEEP these
# SECURITY: Do NOT add any auth/credential headers here
SHAPE_HEADERS: set[str] = {
    "accept",
    "content-type",
    "x-api-version",
    "x-shopify-api-version",
    "x-github-api-version",
    "api-version",
}

# Headers to ALWAYS STRIP — auth, tracking, ephemeral
STRIP_HEADERS: set[str] = {
    # Auth and credentials (SECURITY CRITICAL)
    "authorization",
    "cookie",
    "x-api-key",
    "api-key",
    "x-auth-token",
    "x-token",
    "x-access-token",
    "x-session-id",
    "x-csrf-token",
    "proxy-authorization",
    # Request tracking
    "x-request-id",
    "x-correlation-id",
    "x-trace-id",
    # Client identity
    "user-agent",
    "referer",
    "origin",
    "host",
    "from",
    # Caching / conditional
    "connection",
    "cache-control",
    "if-none-match",
    "if-modified-since",
}

# Patterns that indicate a header is auth-related (for unknown X-* headers)
_AUTH_HEADER_PATTERNS: list[str] = [
    "auth",
    "token",
    "key",
    "secret",
    "credential",
    "session",
    "csrf",
    "bearer",
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def extract_probe_template(
    method: str,
    url: str,
    request_headers: dict[str, str],
) -> ProbeTemplate:
    """Extract a sanitized probe template from a captured request.

    Keeps parameters that affect response shape.
    Strips parameters that are ephemeral or would cause probe failures.
    """
    parsed = urllib.parse.urlparse(url)
    query = dict(urllib.parse.parse_qsl(parsed.query))

    sanitized_query = _sanitize_query_params(query)
    sanitized_headers = _sanitize_headers(request_headers)

    return ProbeTemplate(
        method=method,
        path=parsed.path,
        query_params=sanitized_query,
        headers=sanitized_headers,
    )


# ---------------------------------------------------------------------------
# Sanitization helpers
# ---------------------------------------------------------------------------


def _sanitize_query_params(params: dict[str, str]) -> dict[str, str]:
    """Sanitize query params for probe template.

    Decision logic:
    1. If param name is in STRIP_PARAMS -> remove
    2. If param name is in KEEP_PARAMS -> keep
    3. If param value looks like a cursor/token (long base64, UUID) -> remove
    4. Otherwise -> keep (conservative — unknown params might affect shape)
    """
    result: dict[str, str] = {}
    for key, value in params.items():
        key_lower = key.lower()

        # Explicit strip list
        if key_lower in STRIP_PARAMS:
            continue

        # Explicit keep list
        if key_lower in KEEP_PARAMS:
            result[key] = value
            continue

        # Heuristic: strip values that look like ephemeral tokens
        if _looks_like_token(value):
            continue

        # Default: keep (conservative)
        result[key] = value

    return result


def _sanitize_headers(headers: dict[str, str]) -> dict[str, str]:
    """Keep only headers that affect response shape.

    SECURITY: Aggressively strips anything that looks like auth.
    """
    result: dict[str, str] = {}
    for key, value in headers.items():
        key_lower = key.lower()

        # Explicit strip list
        if key_lower in STRIP_HEADERS:
            continue

        # Explicit keep list
        if key_lower in SHAPE_HEADERS:
            result[key] = value
            continue

        # For unknown X-* headers: keep only if they don't look like auth
        if key_lower.startswith("x-"):
            if any(
                pattern in key_lower for pattern in _AUTH_HEADER_PATTERNS
            ):
                continue  # Header name looks like auth — strip it
            if _looks_like_secret_value(value):
                continue  # Header value looks like a credential — strip it
            result[key] = value
            continue

        # Non-X-* headers not in either list: skip (don't keep unknown headers)

    return result


def _looks_like_token(value: str) -> bool:
    """Heuristic: does this value look like an ephemeral cursor/token?"""
    # Very long base64-ish strings
    if len(value) > 64 and re.match(r"^[A-Za-z0-9+/=-]+$", value):
        return True
    # UUIDs
    return re.match(
        r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
        value,
        re.I,
    ) is not None


def _looks_like_secret_value(value: str) -> bool:
    """Heuristic: does this header value look like a credential?

    Catches JWTs and long base64-encoded tokens that might appear in
    X-* headers that don't match auth keyword patterns.
    """
    # JWTs: three dot-separated base64 segments
    if value.count(".") == 2 and len(value) > 40:
        parts = value.split(".")
        if all(re.match(r"^[A-Za-z0-9_-]+=*$", p) for p in parts if p):
            return True
    # Long base64-ish strings (likely tokens/keys)
    return len(value) > 64 and re.match(r"^[A-Za-z0-9+/=-]+$", value) is not None
