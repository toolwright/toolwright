"""Endpoint re-discovery - fetch current API state for drift comparison.

Probes well-known OpenAPI spec paths on a host and converts the
discovered spec into Endpoint models for drift comparison.

Design constraints (from user feedback):
- Has its own timeout, independent of health probe timeout
- Failure does not change health status (stays DEGRADED, not UNHEALTHY)
- Handles HAR-captured APIs gracefully (no spec available → returns None)
"""

from __future__ import annotations

import json
import logging
from typing import Any

import yaml

from toolwright.models.endpoint import AuthType, Endpoint, Parameter, ParameterLocation

logger = logging.getLogger(__name__)

DEFAULT_REDISCOVERY_TIMEOUT = 30.0

WELL_KNOWN_SPEC_PATHS = [
    "/openapi.json",
    "/openapi.yaml",
    "/swagger.json",
    "/v1/openapi.json",
    "/api-docs",
    "/.well-known/openapi.json",
]


async def rediscover_endpoints(
    host: str,
    *,
    timeout: float = DEFAULT_REDISCOVERY_TIMEOUT,
) -> list[Endpoint] | None:
    """Probe a host for an OpenAPI spec and return parsed endpoints.

    Tries each well-known path in order, stopping at the first success.
    Returns None if no spec is found or parsing fails.

    Args:
        host: The API host to probe (e.g. "api.example.com").
        timeout: HTTP timeout in seconds (independent of health probe timeout).

    Returns:
        List of Endpoint models if a spec was found, None otherwise.
    """
    import httpx

    async with httpx.AsyncClient(timeout=timeout) as client:
        for spec_path in WELL_KNOWN_SPEC_PATHS:
            url = f"https://{host}{spec_path}"
            try:
                response = await client.get(url)
                if response.status_code != 200:
                    continue

                spec = _parse_response_body(response.text)
                if spec is None:
                    continue

                # Validate it looks like an OpenAPI spec
                if "openapi" not in spec and "swagger" not in spec:
                    continue

                endpoints = parse_spec_to_endpoints(spec, host=host)
                if endpoints:
                    return endpoints

            except Exception:
                logger.debug("Rediscovery probe failed for %s", url, exc_info=True)
                return None

    return None


def _parse_response_body(text: str) -> dict[str, Any] | None:
    """Try to parse response body as JSON, then YAML."""
    # Try JSON first
    try:
        result = json.loads(text)
        if isinstance(result, dict):
            return result
    except (json.JSONDecodeError, ValueError):
        pass

    # Try YAML
    try:
        result = yaml.safe_load(text)
        if isinstance(result, dict):
            return result
    except yaml.YAMLError:
        pass

    return None


def parse_spec_to_endpoints(
    spec: dict[str, Any],
    *,
    host: str,
) -> list[Endpoint]:
    """Convert an OpenAPI spec dict into a list of Endpoint models.

    Lightweight parser that extracts method, path, host, parameters,
    and auth info without going through the full CaptureSession pipeline.

    Args:
        spec: Parsed OpenAPI spec dict.
        host: Host to assign to endpoints.

    Returns:
        List of Endpoint models.
    """
    endpoints: list[Endpoint] = []
    paths = spec.get("paths", {})

    # Detect global security schemes
    security_schemes = (
        spec.get("components", {}).get("securitySchemes", {})
    )
    global_security = spec.get("security", [])

    http_methods = {"get", "post", "put", "patch", "delete", "options", "head"}

    for path_template, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue

        for method in http_methods:
            if method not in path_item:
                continue

            operation = path_item[method]
            if not isinstance(operation, dict):
                continue

            # Extract parameters
            params = _extract_parameters(operation, path_item)

            # Determine auth type
            auth_type = _detect_auth_type(
                operation, global_security, security_schemes
            )

            # Determine risk tier from method
            risk_tier = _infer_risk_tier(method)

            endpoint = Endpoint(
                method=method.upper(),
                path=path_template,
                host=host,
                auth_type=auth_type,
                risk_tier=risk_tier,
                parameters=params,
                tool_id=operation.get("operationId"),
            )
            endpoints.append(endpoint)

    return endpoints


def _extract_parameters(
    operation: dict[str, Any],
    path_item: dict[str, Any],
) -> list[Parameter]:
    """Extract parameters from operation and path item."""
    params: list[Parameter] = []
    seen: set[str] = set()

    # Operation params override path-level params
    all_params = path_item.get("parameters", []) + operation.get("parameters", [])

    for p in all_params:
        if not isinstance(p, dict):
            continue
        name = p.get("name", "")
        location = p.get("in", "query")
        key = f"{location}:{name}"
        if key in seen:
            continue
        seen.add(key)

        loc_map = {
            "path": ParameterLocation.PATH,
            "query": ParameterLocation.QUERY,
            "header": ParameterLocation.HEADER,
            "cookie": ParameterLocation.COOKIE,
        }

        params.append(
            Parameter(
                name=name,
                location=loc_map.get(location, ParameterLocation.QUERY),
                required=p.get("required", False),
                param_type=p.get("schema", {}).get("type", "string"),
                description=p.get("description"),
            )
        )

    return params


def _detect_auth_type(
    operation: dict[str, Any],
    global_security: list[dict[str, Any]],
    security_schemes: dict[str, Any],
) -> AuthType:
    """Detect auth type from operation or global security."""
    security = operation.get("security", global_security)
    if not security:
        return AuthType.NONE

    for sec_req in security:
        if not isinstance(sec_req, dict):
            continue
        for scheme_name in sec_req:
            scheme = security_schemes.get(scheme_name, {})
            scheme_type = scheme.get("type", "")
            if scheme_type == "http":
                sub = scheme.get("scheme", "").lower()
                if sub == "bearer":
                    return AuthType.BEARER
                if sub == "basic":
                    return AuthType.BASIC
            elif scheme_type == "apiKey":
                return AuthType.API_KEY
            elif scheme_type == "oauth2":
                return AuthType.OAUTH2

    return AuthType.UNKNOWN


def _infer_risk_tier(method: str) -> str:
    """Infer risk tier from HTTP method."""
    method_upper = method.upper()
    if method_upper == "GET":
        return "low"
    if method_upper in ("POST", "PUT", "PATCH"):
        return "medium"
    if method_upper == "DELETE":
        return "high"
    return "low"
