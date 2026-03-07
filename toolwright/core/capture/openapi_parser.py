"""OpenAPI specification parser for importing API definitions.

This module parses OpenAPI 3.0/3.1 specifications and converts them into
CaptureSession objects, allowing users to bootstrap tools from existing
API documentation.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from toolwright.models.capture import (
    CaptureSession,
    CaptureSource,
    HttpExchange,
    HTTPMethod,
)


class OpenAPIParser:
    """Parse OpenAPI specifications into CaptureSession objects.

    Supports OpenAPI 3.0.x and 3.1.x specifications in JSON or YAML format.
    """

    SUPPORTED_VERSIONS = ("3.0", "3.1")

    def __init__(self, allowed_hosts: list[str] | None = None) -> None:
        """Initialize parser with allowed hosts.

        Args:
            allowed_hosts: List of allowed host patterns (optional for OpenAPI)
        """
        self._initial_allowed_hosts = list(allowed_hosts or [])
        self.allowed_hosts = list(self._initial_allowed_hosts)
        self.warnings: list[str] = []
        self.stats = {
            "total_paths": 0,
            "total_operations": 0,
            "imported": 0,
            "skipped": 0,
        }

    def parse_file(self, path: Path, name: str | None = None) -> CaptureSession:
        """Parse an OpenAPI spec file into a CaptureSession.

        Args:
            path: Path to OpenAPI spec (JSON or YAML)
            name: Optional name for the session

        Returns:
            CaptureSession containing synthetic exchanges from the spec
        """
        self.warnings = []
        self.stats = {
            "total_paths": 0,
            "total_operations": 0,
            "imported": 0,
            "skipped": 0,
        }
        # Reset parser host state for each parse invocation.
        self.allowed_hosts = list(self._initial_allowed_hosts)

        # Load spec
        spec = self._load_spec(path)

        # Validate version
        self._validate_version(spec)

        # Extract server info
        servers = spec.get("servers", [])
        default_host = self._extract_host(servers)

        # If allowed_hosts not set, use servers from spec
        if not self.allowed_hosts and default_host:
            self.allowed_hosts = [default_host]

        # Create session
        session = CaptureSession(
            name=name or spec.get("info", {}).get("title", path.stem),
            description=spec.get("info", {}).get("description"),
            source=CaptureSource.MANUAL,  # OpenAPI is effectively manual input
            source_file=str(path),
            allowed_hosts=self.allowed_hosts,
        )

        # Parse paths
        paths = spec.get("paths", {})
        self.stats["total_paths"] = len(paths)

        for path_template, path_item in paths.items():
            exchanges = self._parse_path_item(
                path_template, path_item, default_host, spec
            )
            session.exchanges.extend(exchanges)

        # If no allowlist was inferred or provided, pin to discovered exchange host(s)
        # so first_party scopes remain compile-safe for relative server specs.
        if not session.allowed_hosts and session.exchanges:
            session.allowed_hosts = sorted({exchange.host for exchange in session.exchanges})
            self.allowed_hosts = list(session.allowed_hosts)
            self.warnings.append(
                "OpenAPI servers used relative URLs; defaulted allowed_hosts to "
                f"{', '.join(session.allowed_hosts)}. Pass --allowed-hosts to override."
            )

        # Update stats
        session.total_requests = len(session.exchanges)
        session.warnings = self.warnings

        return session

    def _load_spec(self, path: Path) -> dict[str, Any]:
        """Load OpenAPI spec from file."""
        content = path.read_text()

        result: dict[str, Any]
        if path.suffix in (".yaml", ".yml"):
            result = yaml.safe_load(content)
        elif path.suffix == ".json":
            result = json.loads(content)
        else:
            # Try YAML first, then JSON
            try:
                result = yaml.safe_load(content)
            except yaml.YAMLError:
                result = json.loads(content)
        return result

    def _validate_version(self, spec: dict[str, Any]) -> None:
        """Validate OpenAPI version."""
        openapi_version = spec.get("openapi", "")

        if not openapi_version:
            # Check for Swagger 2.0
            if spec.get("swagger", "").startswith("2"):
                raise ValueError(
                    "Swagger 2.0 is not supported. Please convert to OpenAPI 3.x"
                )
            raise ValueError("Missing 'openapi' version field")

        major_minor = ".".join(openapi_version.split(".")[:2])
        if major_minor not in self.SUPPORTED_VERSIONS:
            self.warnings.append(
                f"OpenAPI version {openapi_version} may not be fully supported"
            )

    def _extract_host(self, servers: list[dict[str, Any]]) -> str:
        """Extract default host from servers list."""
        if not servers:
            return ""

        url = servers[0].get("url", "")

        # Handle relative URLs
        if url.startswith("/"):
            return ""

        # Extract host from URL
        from urllib.parse import urlparse

        parsed = urlparse(url)
        return parsed.netloc or ""

    def _parse_path_item(
        self,
        path_template: str,
        path_item: dict[str, Any],
        default_host: str,
        spec: dict[str, Any],
    ) -> list[HttpExchange]:
        """Parse a path item into exchanges."""
        exchanges = []

        # HTTP methods to check
        http_methods = ["get", "post", "put", "patch", "delete", "options", "head"]

        for method in http_methods:
            if method not in path_item:
                continue

            operation = path_item[method]
            self.stats["total_operations"] += 1

            try:
                exchange = self._create_exchange(
                    method=method.upper(),
                    path_template=path_template,
                    operation=operation,
                    path_item=path_item,
                    default_host=default_host,
                    spec=spec,
                )
                exchanges.append(exchange)
                self.stats["imported"] += 1
            except Exception as e:
                self.warnings.append(f"Failed to parse {method.upper()} {path_template}: {e}")
                self.stats["skipped"] += 1

        return exchanges

    def _create_exchange(
        self,
        method: str,
        path_template: str,
        operation: dict[str, Any],
        path_item: dict[str, Any],
        default_host: str,
        spec: dict[str, Any],
    ) -> HttpExchange:
        """Create an HttpExchange from an OpenAPI operation."""
        from urllib.parse import urlencode

        # Build URL
        host = self._resolve_exchange_host(default_host)
        url = f"https://{host}{path_template}"

        # Extract parameters
        parameters = self._collect_parameters(operation, path_item)
        request_headers = self._extract_headers(parameters)

        # Append query parameters to URL so the normalize pipeline sees them
        query_params = self._extract_query_params(parameters)
        if query_params:
            url = f"{url}?{urlencode(query_params)}"

        # Extract request body schema
        request_body_json = self._extract_request_body(operation, spec)

        # Extract response
        response_status, response_body_json = self._extract_response(operation, spec)

        # Create exchange
        exchange = HttpExchange(
            url=url,
            method=HTTPMethod(method),
            host=host,
            path=path_template,
            request_headers=request_headers,
            request_body_json=request_body_json,
            response_status=response_status,
            response_body_json=response_body_json,
            response_content_type="application/json",
            timestamp=datetime.now(UTC),
            source=CaptureSource.MANUAL,
            notes={
                "openapi_operation_id": operation.get("operationId"),
                "openapi_summary": operation.get("summary"),
                "openapi_description": operation.get("description"),
                "openapi_tags": operation.get("tags", []),
                "openapi_deprecated": operation.get("deprecated", False),
            },
        )

        return exchange

    def _resolve_exchange_host(self, default_host: str) -> str:
        """Resolve host used for synthetic exchanges."""
        if default_host:
            return default_host
        for pattern in self.allowed_hosts:
            if pattern and not any(token in pattern for token in ("*", "?", "[")):
                return pattern
        return "api.example.com"

    def _collect_parameters(
        self,
        operation: dict[str, Any],
        path_item: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Collect parameters from operation and path item."""
        # Parameters can be defined at path level or operation level
        path_params = path_item.get("parameters", [])
        op_params = operation.get("parameters", [])

        # Operation params override path params
        params_by_name: dict[str, dict[str, Any]] = {}
        for param in path_params + op_params:
            key = f"{param.get('in', 'query')}:{param.get('name', '')}"
            params_by_name[key] = param

        return list(params_by_name.values())

    def _extract_headers(self, parameters: list[dict[str, Any]]) -> dict[str, str]:
        """Extract header parameters."""
        headers: dict[str, str] = {}

        for param in parameters:
            if param.get("in") == "header":
                name = param.get("name", "")
                # Use example value or generate placeholder
                example = self._get_example_value(param)
                headers[name] = str(example) if example else f"<{name}>"

        return headers

    def _extract_query_params(self, parameters: list[dict[str, Any]]) -> dict[str, str]:
        """Extract query parameters with example/default values."""
        query: dict[str, str] = {}

        for param in parameters:
            if param.get("in") == "query":
                name = param.get("name", "")
                example = self._get_example_value(param)
                query[name] = str(example) if example is not None else ""

        return query

    def _extract_request_body(
        self, operation: dict[str, Any], spec: dict[str, Any]
    ) -> dict[str, Any] | list[Any] | None:
        """Extract request body schema."""
        request_body = operation.get("requestBody")
        if not request_body:
            return None

        content = request_body.get("content", {})

        # Prefer JSON content
        for content_type in ["application/json", "application/x-www-form-urlencoded"]:
            if content_type in content:
                schema = content[content_type].get("schema", {})
                return self._schema_to_example(schema, spec)

        return None

    def _extract_response(
        self, operation: dict[str, Any], spec: dict[str, Any]
    ) -> tuple[int, dict[str, Any] | list[Any] | None]:
        """Extract response status and body."""
        responses = operation.get("responses", {})

        # Look for success responses
        for status_code in ["200", "201", "202", "204"]:
            if status_code in responses:
                response = responses[status_code]
                content = response.get("content", {})

                if "application/json" in content:
                    schema = content["application/json"].get("schema", {})
                    example = self._schema_to_example(schema, spec)
                    return int(status_code), example

                return int(status_code), None

        # Default to 200
        return 200, None

    def _schema_to_example(
        self, schema: dict[str, Any], spec: dict[str, Any]
    ) -> dict[str, Any] | list[Any] | None:
        """Convert a schema to an example value."""
        # Resolve $ref
        if "$ref" in schema:
            schema = self._resolve_ref(schema["$ref"], spec)

        # Check for example (return as-is for nested schema resolution)
        if "example" in schema:
            example: Any = schema["example"]
            return example  # type: ignore[no-any-return]

        schema_type = schema.get("type")

        if schema_type == "object":
            properties = schema.get("properties", {})
            result: dict[str, Any] = {}
            for prop_name, prop_schema in properties.items():
                prop_value = self._schema_to_example(prop_schema, spec)
                if prop_value is not None:
                    result[prop_name] = prop_value
                else:
                    result[prop_name] = self._get_default_for_type(prop_schema)
            return result if result else None

        elif schema_type == "array":
            items = schema.get("items", {})
            item_example = self._schema_to_example(items, spec)
            return [item_example] if item_example else []

        return None

    def _resolve_ref(self, ref: str, spec: dict[str, Any]) -> dict[str, Any]:
        """Resolve a $ref pointer."""
        if not ref.startswith("#/"):
            self.warnings.append(f"External $ref not supported: {ref}")
            return {}

        # Parse JSON pointer
        path = ref[2:].split("/")
        current = spec

        for part in path:
            # Handle JSON pointer escaping
            part = part.replace("~1", "/").replace("~0", "~")
            if isinstance(current, dict):
                current = current.get(part, {})
            else:
                return {}

        return current if isinstance(current, dict) else {}

    def _get_example_value(self, param: dict[str, Any]) -> Any:
        """Get example value for a parameter."""
        if "example" in param:
            return param["example"]

        if "examples" in param:
            examples = param["examples"]
            if examples:
                first_example: dict[str, Any] = next(iter(examples.values()), {})
                return first_example.get("value")

        schema = param.get("schema", {})
        if "example" in schema:
            return schema["example"]
        if "default" in schema:
            return schema["default"]

        return None

    def _get_default_for_type(self, schema: dict[str, Any]) -> Any:
        """Get a default value for a schema type."""
        schema_type = schema.get("type", "string")
        schema_format = schema.get("format", "")

        defaults = {
            "string": "string",
            "integer": 0,
            "number": 0.0,
            "boolean": False,
            "array": [],
            "object": {},
        }

        # Format-specific defaults for strings
        string_format_defaults = {
            "date": "2024-01-01",
            "date-time": "2024-01-01T00:00:00Z",
            "email": "user@example.com",
            "uri": "https://example.com",
            "uuid": "00000000-0000-0000-0000-000000000000",
        }

        if schema_type == "string" and schema_format in string_format_defaults:
            return string_format_defaults[schema_format]

        return defaults.get(schema_type, "")


def parse_openapi_file(
    path: str | Path,
    allowed_hosts: list[str] | None = None,
    name: str | None = None,
) -> CaptureSession:
    """Convenience function to parse an OpenAPI file.

    Args:
        path: Path to OpenAPI spec
        allowed_hosts: Optional list of allowed hosts
        name: Optional session name

    Returns:
        CaptureSession with synthetic exchanges
    """
    parser = OpenAPIParser(allowed_hosts=allowed_hosts)
    return parser.parse_file(Path(path), name=name)
