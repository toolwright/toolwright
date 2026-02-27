"""OpenAPI 3.1 contract generator."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from toolwright.models.endpoint import Endpoint
from toolwright.models.scope import Scope
from toolwright.utils.schema_version import CURRENT_SCHEMA_VERSION


class ContractCompiler:
    """Compile endpoints into an OpenAPI 3.1 specification."""

    def __init__(
        self,
        title: str = "Generated API",
        version: str = "1.0.0",
        description: str | None = None,
    ) -> None:
        """Initialize the contract compiler.

        Args:
            title: API title for the spec
            version: API version
            description: Optional API description
        """
        self.title = title
        self.version = version
        self.description = description

    def compile(
        self,
        endpoints: list[Endpoint],
        scope: Scope | None = None,
        capture_id: str | None = None,
        generated_at: datetime | None = None,
    ) -> dict[str, Any]:
        """Compile endpoints into an OpenAPI 3.1 specification.

        Args:
            endpoints: List of endpoints to include
            scope: Optional scope that was applied
            capture_id: Optional capture session ID

        Returns:
            OpenAPI 3.1 specification as dict
        """
        # Group endpoints by host
        by_host: dict[str, list[Endpoint]] = defaultdict(list)
        for endpoint in endpoints:
            by_host[endpoint.host].append(endpoint)

        # Build servers list
        servers = [
            {"url": f"https://{host}", "description": f"{host} server"}
            for host in sorted(by_host.keys())
        ]

        # Build paths
        paths = self._build_paths(endpoints)

        # Build components (schemas)
        components = self._build_components(endpoints)

        # Build spec
        spec: dict[str, Any] = {
            "openapi": "3.1.0",
            "info": {
                "title": self.title,
                "version": self.version,
            },
            "servers": servers,
            "paths": paths,
            "x-toolwright": {
                "schema_version": CURRENT_SCHEMA_VERSION,
            },
        }

        if self.description:
            spec["info"]["description"] = self.description

        # Add Toolwright metadata
        timestamp = generated_at or datetime.now(UTC)

        spec["info"]["x-toolwright"] = {
            "generated_at": timestamp.isoformat(),
            "schema_version": CURRENT_SCHEMA_VERSION,
        }
        if capture_id:
            spec["info"]["x-toolwright"]["capture_id"] = capture_id
        if scope:
            spec["info"]["x-toolwright"]["scope"] = scope.name

        if components:
            spec["components"] = components

        return spec

    def _build_paths(self, endpoints: list[Endpoint]) -> dict[str, Any]:
        """Build the paths section of the spec."""
        paths: dict[str, dict[str, Any]] = defaultdict(dict)

        sorted_endpoints = sorted(
            endpoints,
            key=lambda ep: (ep.host, ep.method.upper(), ep.path, ep.signature_id),
        )
        for endpoint in sorted_endpoints:
            path = endpoint.path
            method = endpoint.method.lower()

            operation = self._build_operation(endpoint)
            paths[path][method] = operation

        return dict(paths)

    def _build_operation(self, endpoint: Endpoint) -> dict[str, Any]:
        """Build an operation object for an endpoint."""
        operation: dict[str, Any] = {
            "operationId": endpoint.tool_id or self._generate_operation_id(endpoint),
            "summary": self._generate_summary(endpoint),
        }

        # Add Toolwright metadata
        operation["x-toolwright"] = {
            "stable_id": endpoint.stable_id,
            "signature_id": endpoint.signature_id,
            "risk_tier": endpoint.risk_tier,
            "observation_count": endpoint.observation_count,
        }

        if endpoint.is_state_changing:
            operation["x-toolwright"]["state_changing"] = True
        if endpoint.is_auth_related:
            operation["x-toolwright"]["auth_related"] = True
        if endpoint.has_pii:
            operation["x-toolwright"]["has_pii"] = True

        # Parameters
        parameters = self._build_parameters(endpoint)
        if parameters:
            operation["parameters"] = parameters

        # Request body
        if endpoint.request_body_schema or endpoint.request_examples:
            operation["requestBody"] = self._build_request_body(endpoint)

        # Responses
        operation["responses"] = self._build_responses(endpoint)

        # Tags based on path
        tags = self._extract_tags(endpoint)
        if tags:
            operation["tags"] = tags

        return operation

    def _build_parameters(self, endpoint: Endpoint) -> list[dict[str, Any]]:
        """Build parameter objects for an endpoint."""
        parameters = []

        for param in sorted(
            endpoint.parameters,
            key=lambda p: (p.location.value, p.name),
        ):
            param_obj: dict[str, Any] = {
                "name": param.name,
                "in": param.location.value,
                "required": param.required,
                "schema": {"type": param.param_type},
            }

            if param.description:
                param_obj["description"] = param.description
            if param.example is not None:
                param_obj["example"] = param.example
            if param.pattern:
                param_obj["schema"]["pattern"] = param.pattern

            parameters.append(param_obj)

        return parameters

    def _build_request_body(self, endpoint: Endpoint) -> dict[str, Any]:
        """Build request body object for an endpoint."""
        content_type = endpoint.request_content_type or "application/json"

        content: dict[str, Any] = {}

        if endpoint.request_body_schema:
            content["schema"] = endpoint.request_body_schema

        if endpoint.request_examples:
            # Use first example
            content["example"] = endpoint.request_examples[0]

        return {
            "content": {
                content_type: content,
            },
        }

    def _build_responses(self, endpoint: Endpoint) -> dict[str, Any]:
        """Build responses object for an endpoint."""
        responses: dict[str, Any] = {}

        if endpoint.response_status_codes:
            for status in endpoint.response_status_codes:
                response: dict[str, Any] = {
                    "description": self._get_status_description(status),
                }

                # Add content for success responses
                if 200 <= status < 300:
                    content_type = endpoint.response_content_type or "application/json"
                    content: dict[str, Any] = {}

                    if endpoint.response_body_schema:
                        content["schema"] = endpoint.response_body_schema

                    if endpoint.response_examples:
                        content["example"] = endpoint.response_examples[0]

                    if content:
                        response["content"] = {content_type: content}

                responses[str(status)] = response
        else:
            # Default response if no status codes observed
            responses["200"] = {"description": "Successful response"}

        return responses

    def _build_components(self, _endpoints: list[Endpoint]) -> dict[str, Any]:
        """Build the components section with reusable schemas."""
        # For now, we don't extract reusable schemas
        # This could be enhanced to detect common schemas across endpoints
        return {}

    def _generate_operation_id(self, endpoint: Endpoint) -> str:
        """Generate an operation ID for an endpoint."""
        from toolwright.utils.naming import generate_tool_name

        return generate_tool_name(endpoint.method, endpoint.path)

    def _generate_summary(self, endpoint: Endpoint) -> str:
        """Generate a summary for an endpoint.

        Includes verb, resource name, and top response fields.
        """
        method = endpoint.method.upper()
        path = endpoint.path

        # Extract resource name from path
        segments = [s for s in path.split("/") if s and not s.startswith("{")]
        if segments:
            resource = segments[-1].replace("_", " ").replace("-", " ").title()
        else:
            resource = "Resource"

        verb_map = {
            "GET": "Get",
            "POST": "Create",
            "PUT": "Update",
            "PATCH": "Partially update",
            "DELETE": "Delete",
            "HEAD": "Check",
        }

        verb = verb_map.get(method, method.title())

        # Check for collection vs single resource
        if method == "GET" and not path.rstrip("/").endswith("}"):
            verb = "List"

        base = f"{verb} {resource}"

        # Append top response fields
        fields_hint = self._response_fields_hint(endpoint)
        if fields_hint:
            base += f". Returns: {fields_hint}"

        return base

    @staticmethod
    def _response_fields_hint(endpoint: Endpoint, max_fields: int = 5) -> str:
        """Extract top response field names from schema."""
        schema = endpoint.response_body_schema
        if not schema or not isinstance(schema, dict):
            return ""
        props = schema.get("properties", {})
        if not props:
            return ""
        fields = list(props.keys())[:max_fields]
        return ", ".join(fields)

    def _extract_tags(self, endpoint: Endpoint) -> list[str]:
        """Extract tags from endpoint path."""
        segments = endpoint.path.strip("/").split("/")

        # Skip common prefixes
        skip = {"api", "v1", "v2", "v3", "rest", "public", "private"}

        for segment in segments:
            if segment.lower() not in skip and not segment.startswith("{"):
                return [segment]

        return []

    def _get_status_description(self, status: int) -> str:
        """Get description for HTTP status code."""
        descriptions = {
            200: "Successful response",
            201: "Resource created",
            204: "No content",
            400: "Bad request",
            401: "Unauthorized",
            403: "Forbidden",
            404: "Not found",
            405: "Method not allowed",
            409: "Conflict",
            422: "Unprocessable entity",
            429: "Too many requests",
            500: "Internal server error",
            502: "Bad gateway",
            503: "Service unavailable",
        }

        return descriptions.get(status, f"Response with status {status}")

    def to_yaml(self, spec: dict[str, Any]) -> str:
        """Serialize spec to YAML string.

        Args:
            spec: OpenAPI spec dict

        Returns:
            YAML string
        """
        import yaml

        return yaml.dump(spec, default_flow_style=False, allow_unicode=True, sort_keys=False)

    def to_json(self, spec: dict[str, Any]) -> str:
        """Serialize spec to JSON string.

        Args:
            spec: OpenAPI spec dict

        Returns:
            JSON string
        """
        import json

        return json.dumps(spec, indent=2)
