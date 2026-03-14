"""Fetch OpenAPI specs from URLs with auto-detection and path probing.

Given a URL, this module:
- If it points directly to a spec file (.json, .yaml, .yml), fetches and parses it
- If it points to a domain/path, probes well-known paths for OpenAPI specs
- Validates that the fetched content is a valid OpenAPI/Swagger spec
"""

from __future__ import annotations

import json
import logging
from typing import Any
from urllib.parse import urlparse

import httpx
import yaml

logger = logging.getLogger(__name__)

# Well-known paths where OpenAPI specs are commonly served
WELL_KNOWN_PATHS = [
    "/openapi.json",
    "/openapi.yaml",
    "/swagger.json",
    "/v2/swagger.json",
    "/v3/api-docs",
    "/api-docs",
    "/.well-known/openapi.json",
    "/v1/openapi.json",
]

# File extensions that indicate a direct spec URL
SPEC_EXTENSIONS = (".json", ".yaml", ".yml")


class SpecFetchError(Exception):
    """Raised when a spec cannot be fetched or found."""


def fetch_spec_from_url(url: str, *, timeout: float = 30.0) -> tuple[dict[str, Any], str]:
    """Fetch an OpenAPI spec from a URL.

    If the URL points directly to a spec file (ends in .json/.yaml/.yml),
    fetches and parses it. Otherwise, probes well-known paths.

    Args:
        url: The URL to fetch from (direct spec URL or domain)
        timeout: HTTP request timeout in seconds

    Returns:
        Tuple of (parsed_spec_dict, source_url)

    Raises:
        SpecFetchError: If the URL is unreachable or no valid spec is found
    """
    parsed = urlparse(url)

    # If URL path ends with a spec extension, try direct fetch first
    if any(parsed.path.endswith(ext) for ext in SPEC_EXTENSIONS):
        return _fetch_direct(url, timeout=timeout)

    # Otherwise, probe well-known paths
    return _probe_paths(url, timeout=timeout)


def _fetch_direct(url: str, *, timeout: float) -> tuple[dict[str, Any], str]:
    """Fetch a spec from a direct URL."""
    try:
        resp = httpx.get(url, timeout=timeout, follow_redirects=True)
    except (httpx.ConnectError, httpx.TimeoutException, OSError) as exc:
        raise SpecFetchError(f"Could not reach URL: {url} ({exc})") from exc
    except httpx.HTTPError as exc:
        raise SpecFetchError(f"Could not reach URL: {url} ({exc})") from exc

    if resp.status_code != 200:
        # Fall back to probing if direct fetch returns non-200
        return _probe_paths(url, timeout=timeout)

    spec = _parse_response(resp.text, url)
    if spec is not None:
        return spec, url

    # Direct URL didn't contain a valid spec, try probing
    return _probe_paths(url, timeout=timeout)


def _probe_paths(url: str, *, timeout: float) -> tuple[dict[str, Any], str]:
    """Probe well-known paths at the given base URL for an OpenAPI spec."""
    base_url = _normalise_base_url(url)
    tried_paths: list[str] = []
    unreachable = True

    for path in WELL_KNOWN_PATHS:
        probe_url = f"{base_url}{path}"
        tried_paths.append(path)

        try:
            resp = httpx.get(probe_url, timeout=timeout, follow_redirects=True)
            unreachable = False  # At least one request succeeded
        except (httpx.ConnectError, httpx.TimeoutException, OSError):
            logger.debug("Probe failed for %s", probe_url, exc_info=True)
            continue
        except httpx.HTTPError:
            logger.debug("Probe HTTP error for %s", probe_url, exc_info=True)
            unreachable = False
            continue

        if resp.status_code != 200:
            continue

        spec = _parse_response(resp.text, probe_url)
        if spec is not None:
            return spec, probe_url

    if unreachable:
        raise SpecFetchError(f"Could not reach URL: {url}")

    raise SpecFetchError(
        f"No OpenAPI spec found at {url}. "
        f"Tried: {', '.join(tried_paths)}"
    )


def _normalise_base_url(url: str) -> str:
    """Ensure URL has a scheme and no trailing slash, strip path for probing."""
    url = url.rstrip("/")
    parsed = urlparse(url)

    if not parsed.scheme:
        url = f"https://{url}"
        parsed = urlparse(url)

    # Use just scheme + netloc as base for probing
    return f"{parsed.scheme}://{parsed.netloc}"


def _parse_response(text: str, url: str) -> dict[str, Any] | None:
    """Parse response text as JSON or YAML and validate it's an OpenAPI spec.

    Returns the parsed spec dict if valid, None otherwise.
    """
    spec: dict[str, Any] | None = None

    # Try JSON first
    try:
        spec = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        pass

    # Try YAML if JSON failed
    if spec is None:
        try:
            spec = yaml.safe_load(text)
        except yaml.YAMLError:
            return None

    if not isinstance(spec, dict):
        return None

    # Validate it looks like an OpenAPI/Swagger spec
    if "openapi" not in spec and "swagger" not in spec:
        return None

    return spec
