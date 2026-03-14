"""Endpoint aggregation and deduplication."""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any
from urllib.parse import parse_qsl, urlparse

from toolwright.core.normalize.path_normalizer import PathNormalizer, VarianceNormalizer
from toolwright.core.normalize.tagger import AutoTagger
from toolwright.core.risk_keywords import (
    CRITICAL_PATH_KEYWORDS,
    HIGH_RISK_PATH_KEYWORDS,
    RISK_ORDER,
)
from toolwright.models.capture import CaptureSession, HttpExchange
from toolwright.models.endpoint import AuthType, Endpoint, Parameter, ParameterLocation

# Static asset extensions to exclude from endpoint aggregation.
# .json is intentionally excluded — it's a valid API response format.
_STATIC_ASSET_EXTENSIONS = re.compile(
    r"\.(js|css|map|png|jpg|jpeg|gif|svg|webp|avif|ico|woff|woff2|ttf|eot|otf)$",
    re.IGNORECASE,
)

_PLACEHOLDER_RE = re.compile(r"\{([^}]+)\}")



def _is_static_asset(path: str) -> bool:
    """Return True if the path points to a static asset file."""
    # Strip query string before checking extension
    clean = path.split("?")[0]
    return bool(_STATIC_ASSET_EXTENSIONS.search(clean))


class EndpointAggregator:
    """Aggregate HTTP exchanges into normalized endpoints."""

    # Headers that indicate authentication
    AUTH_HEADERS = {
        "authorization": AuthType.BEARER,
        "x-api-key": AuthType.API_KEY,
        "x-auth-token": AuthType.BEARER,
        "cookie": AuthType.COOKIE,
    }

    # Path patterns that suggest auth-related endpoints
    AUTH_PATH_PATTERNS = (
        "/login",
        "/logout",
        "/signin",
        "/signout",
        "/auth",
        "/oauth",
        "/token",
        "/refresh",
        "/session",
        "/register",
        "/signup",
        "/password",
        "/reset",
        "/verify",
        "/confirm",
        "/2fa",
        "/mfa",
        "/otp",
    )

    # Field names that suggest PII
    # Strong PII indicators: always signal PII regardless of context
    PII_FIELDS = {
        "email",
        "phone",
        "ssn",
        "social_security",
        "address",
        "dob",
        "date_of_birth",
        "birthday",
        "first_name",
        "last_name",
        "full_name",
        "credit_card",
        "card_number",
        "cvv",
        "passport",
        "license",
        "salary",
        "income",
    }

    # Ambiguous fields: only signal PII when combined with a strong PII field.
    # 'name' alone is too common (product name, project name, etc.) to be a
    # reliable PII indicator.
    AMBIGUOUS_PII_FIELDS = {"name"}

    def __init__(self, first_party_hosts: list[str] | None = None) -> None:
        """Initialize aggregator.

        Args:
            first_party_hosts: List of first-party host patterns
        """
        self.first_party_hosts = first_party_hosts or []
        self.path_normalizer = PathNormalizer()
        self.variance_normalizer = VarianceNormalizer(self.path_normalizer)
        self.tagger = AutoTagger()

    def aggregate(self, session: CaptureSession) -> list[Endpoint]:
        """Aggregate a capture session into endpoints.

        Args:
            session: CaptureSession to aggregate

        Returns:
            List of aggregated Endpoint objects
        """
        # Pre-filter: remove static asset requests
        exchanges = [e for e in session.exchanges if not _is_static_asset(e.path)]

        # First pass: learn path patterns
        paths_by_method: dict[str, list[str]] = defaultdict(list)
        for exchange in exchanges:
            paths_by_method[exchange.method.value].append(exchange.path)

        for method, paths in paths_by_method.items():
            self.variance_normalizer.learn_from_paths(paths, method)

        # Second pass: group exchanges by normalized endpoint
        grouped: dict[tuple[str, str, str], list[HttpExchange]] = defaultdict(list)

        for exchange in exchanges:
            normalized_path = self.variance_normalizer.normalize_path(
                exchange.path, exchange.method.value
            )
            key = (exchange.method.value, exchange.host, normalized_path)
            grouped[key].append(exchange)

        # Create endpoints
        endpoints: list[Endpoint] = []
        for (method, host, path), exchanges in grouped.items():
            endpoint = self._create_endpoint(method, host, path, exchanges, session)
            endpoints.append(endpoint)

        # Canonical ordering keeps downstream artifacts deterministic.
        return sorted(
            endpoints,
            key=lambda ep: (ep.host, ep.method.upper(), ep.path, ep.signature_id),
        )

    def _create_endpoint(
        self,
        method: str,
        host: str,
        path: str,
        exchanges: list[HttpExchange],
        session: CaptureSession,
    ) -> Endpoint:
        """Create an Endpoint from grouped exchanges."""
        # Use first exchange as representative
        representative = exchanges[0]

        # Collect all observed data
        status_codes: set[int] = set()
        request_content_types: set[str] = set()
        response_content_types: set[str] = set()
        all_query_params: dict[str, set[str]] = defaultdict(set)
        request_body_samples: list[dict[str, Any]] = []
        response_body_samples: list[dict[str, Any]] = []
        request_root_types: set[str] = set()
        response_root_types: set[str] = set()
        request_array_elements: list[Any] = []
        response_array_elements: list[Any] = []

        for exchange in exchanges:
            if exchange.response_status:
                status_codes.add(exchange.response_status)
            if exchange.response_content_type:
                response_content_types.add(exchange.response_content_type.split(";")[0])

            # Extract query params
            parsed = urlparse(exchange.url)
            if parsed.query:
                for key, value in parse_qsl(parsed.query, keep_blank_values=True):
                    all_query_params[key].add(value)

            # Collect body samples for schema inference.
            #
            # Note: request_examples/response_examples are typed as list[dict], so we keep dict
            # samples (and dict items inside list bodies) for examples. Separately, we keep a
            # small sample of list elements so we can infer *top-level array* schemas correctly.
            if exchange.request_body_json:
                request_root_types.add(self._type_string(exchange.request_body_json))
                if isinstance(exchange.request_body_json, dict):
                    request_body_samples.append(exchange.request_body_json)
                elif isinstance(exchange.request_body_json, list):
                    request_array_elements.extend(exchange.request_body_json[:10])
                    for item in exchange.request_body_json[:3]:
                        if isinstance(item, dict):
                            request_body_samples.append(item)
            if exchange.response_body_json:
                response_root_types.add(self._type_string(exchange.response_body_json))
                if isinstance(exchange.response_body_json, dict):
                    response_body_samples.append(exchange.response_body_json)
                elif isinstance(exchange.response_body_json, list):
                    response_array_elements.extend(exchange.response_body_json[:10])
                    for item in exchange.response_body_json[:3]:
                        if isinstance(item, dict):
                            response_body_samples.append(item)

        # Extract path parameters
        path_params = self._extract_path_params(path)

        # Check for OpenAPI parameter schemas from the representative exchange
        openapi_param_schemas: dict[str, dict[str, Any]] = representative.notes.get(
            "openapi_parameter_schemas", {}
        )

        # Build parameters list
        parameters: list[Parameter] = []

        for param_name in path_params:
            schema_meta = openapi_param_schemas.get(param_name, {})
            parameters.append(
                Parameter(
                    name=param_name,
                    location=ParameterLocation.PATH,
                    required=True,
                    param_type=schema_meta.get("type", "string"),
                    json_schema=schema_meta if schema_meta else None,
                )
            )

        for param_name, values in all_query_params.items():
            schema_meta = openapi_param_schemas.get(param_name, {})
            if schema_meta and "type" in schema_meta:
                # Use OpenAPI schema type (authoritative)
                param_type = schema_meta["type"]
            else:
                # Fall back to inference from observed values
                param_type = self._infer_param_type(values)
            parameters.append(
                Parameter(
                    name=param_name,
                    location=ParameterLocation.QUERY,
                    param_type=param_type,
                    example=next(iter(values), None),
                    json_schema=schema_meta if schema_meta else None,
                )
            )

        # Detect auth
        auth_type, auth_header = self._detect_auth(representative)

        # Detect if auth-related endpoint
        is_auth_related = any(p in path.lower() for p in self.AUTH_PATH_PATTERNS)

        # Detect if has PII
        has_pii = self._detect_pii(request_body_samples, response_body_samples)

        # Determine if first-party
        is_first_party = self._is_first_party(host, session.allowed_hosts)

        # Check for OpenAPI request body metadata
        openapi_body_meta: dict[str, Any] = representative.notes.get(
            "openapi_request_body_meta", {}
        )

        # Infer request schema
        request_schema = None
        if request_root_types:
            if request_root_types == {"array"}:
                request_schema = self._infer_array_schema(request_array_elements)
            elif request_root_types == {"object"} and request_body_samples:
                request_schema = self._infer_schema(
                    request_body_samples,
                    openapi_required=openapi_body_meta.get("required_fields"),
                    openapi_field_schemas=openapi_body_meta.get("field_schemas"),
                )
            else:
                request_oneof: list[dict[str, Any]] = []
                for root_type in sorted(request_root_types):
                    if root_type == "object" and request_body_samples:
                        request_oneof.append(self._infer_schema(
                            request_body_samples,
                            openapi_required=openapi_body_meta.get("required_fields"),
                            openapi_field_schemas=openapi_body_meta.get("field_schemas"),
                        ))
                    elif root_type == "array":
                        request_oneof.append(self._infer_array_schema(request_array_elements))
                    else:
                        request_oneof.append({"type": root_type})
                request_schema = {"oneOf": request_oneof}

        # Infer response schema
        response_schema = None
        if response_root_types:
            if response_root_types == {"array"}:
                response_schema = self._infer_array_schema(response_array_elements)
            elif response_root_types == {"object"} and response_body_samples:
                response_schema = self._infer_schema(response_body_samples)
            else:
                response_oneof: list[dict[str, Any]] = []
                for root_type in sorted(response_root_types):
                    if root_type == "object" and response_body_samples:
                        response_oneof.append(self._infer_schema(response_body_samples))
                    elif root_type == "array":
                        response_oneof.append(self._infer_array_schema(response_array_elements))
                    else:
                        response_oneof.append({"type": root_type})
                response_schema = {"oneOf": response_oneof}

        # Determine risk tier
        risk_tier = self._determine_risk_tier(
            method=method,
            path=path,
            is_auth_related=is_auth_related,
            has_pii=has_pii,
            is_first_party=is_first_party,
        )

        # Build tags from path segments and endpoint classification
        tags = self._extract_tags(
            path=path,
            method=method,
            is_auth_related=is_auth_related,
            has_pii=has_pii,
        )

        endpoint = Endpoint(
            method=method,
            path=path,
            host=host,
            url=f"https://{host}{path}",
            parameters=parameters,
            tags=tags,
            request_content_type=next(iter(request_content_types), None),
            request_body_schema=request_schema,
            request_examples=request_body_samples[:3],  # Keep up to 3 examples
            response_status_codes=sorted(status_codes),
            response_content_type=next(iter(response_content_types), None),
            response_body_schema=response_schema,
            response_examples=response_body_samples[:3],
            auth_type=auth_type,
            auth_header=auth_header,
            is_first_party=is_first_party,
            is_state_changing=method in ("POST", "PUT", "PATCH", "DELETE"),
            is_auth_related=is_auth_related,
            has_pii=has_pii,
            risk_tier=risk_tier,
            first_seen=min((e.timestamp for e in exchanges if e.timestamp), default=None),
            last_seen=max((e.timestamp for e in exchanges if e.timestamp), default=None),
            observation_count=len(exchanges),
            exchange_ids=[e.id for e in exchanges],
        )

        # Enrich with auto-tagger (adds domain/semantic tags from path, fields, HTTP semantics)
        endpoint.tags = self.tagger.classify(endpoint)

        return endpoint

    def _extract_tags(
        self,
        path: str,
        method: str,
        is_auth_related: bool,
        has_pii: bool,
    ) -> list[str]:
        """Extract semantic tags from endpoint attributes."""
        tags: list[str] = []

        # First meaningful path segment (skip common prefixes)
        skip = {"api", "v1", "v2", "v3", "rest", "public", "private"}
        for segment in path.strip("/").split("/"):
            if segment.lower() not in skip and not segment.startswith("{"):
                tags.append(segment.lower())
                break

        # Read/write classification
        if method in ("POST", "PUT", "PATCH", "DELETE"):
            tags.append("write")
        else:
            tags.append("read")

        # Auth tag
        if is_auth_related:
            tags.append("auth")

        # PII tag
        if has_pii:
            tags.append("pii")

        return tags

    def _extract_path_params(self, path: str) -> list[str]:
        """Extract parameter names from a path template."""
        params: list[str] = []
        seen: set[str] = set()
        for segment in path.split("/"):
            for name in _PLACEHOLDER_RE.findall(segment):
                if not name or name in seen:
                    continue
                seen.add(name)
                params.append(name)
        return params

    def _detect_auth(
        self, exchange: HttpExchange
    ) -> tuple[AuthType, str | None]:
        """Detect authentication type from exchange headers."""
        for header, auth_type in self.AUTH_HEADERS.items():
            if header in {h.lower() for h in exchange.request_headers}:
                # Get the actual header name (preserving case)
                actual_header = next(
                    (h for h in exchange.request_headers if h.lower() == header), None
                )
                return auth_type, actual_header

        return AuthType.NONE, None

    def _detect_pii(
        self,
        request_samples: list[dict[str, Any]],
        response_samples: list[dict[str, Any]],
    ) -> bool:
        """Detect if samples contain PII fields."""
        all_samples = request_samples + response_samples
        return any(self._has_pii_fields(sample) for sample in all_samples)

    def _has_pii_fields(self, obj: Any) -> bool:
        """Recursively check for PII field names.

        Strong PII fields (email, phone, ssn, etc.) always trigger.
        Ambiguous fields (name) only trigger when a strong PII field
        is also present in the same object tree.
        """
        field_names: set[str] = set()
        self._collect_field_names(obj, field_names, depth=0)
        lower_names = {f.lower() for f in field_names}
        return bool(lower_names & self.PII_FIELDS)

    def _collect_field_names(
        self, obj: Any, names: set[str], depth: int = 0
    ) -> None:
        """Recursively collect all field names from a nested structure."""
        if depth > 10:
            return
        if isinstance(obj, dict):
            for key in obj:
                names.add(key)
                self._collect_field_names(obj[key], names, depth + 1)
        elif isinstance(obj, list):
            for item in obj:
                self._collect_field_names(item, names, depth + 1)

    def _is_first_party(self, host: str, allowed_hosts: list[str]) -> bool:
        """Check if host is first-party."""
        import fnmatch

        for pattern in allowed_hosts or self.first_party_hosts:
            if pattern.startswith("*."):
                suffix = pattern[1:]
                if host == pattern[2:] or host.endswith(suffix):
                    return True
            elif fnmatch.fnmatch(host, pattern) or host == pattern:
                return True

        return bool(allowed_hosts or self.first_party_hosts)

    def _infer_param_type(self, values: set[str]) -> str:
        """Infer parameter type from observed values."""
        if not values:
            return "string"

        # Check if all values are numeric
        if all(v.isdigit() for v in values):
            return "integer"

        # Check if all values are boolean-like
        bool_values = {"true", "false", "1", "0", "yes", "no"}
        if all(v.lower() in bool_values for v in values):
            return "boolean"

        return "string"

    def _infer_schema(
        self,
        samples: list[dict[str, Any]],
        _depth: int = 0,
        openapi_required: list[str] | None = None,
        openapi_field_schemas: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Infer JSON schema from multiple samples via multi-sample merge.

        Tracks all observed types per field across samples, computes required
        from field presence, and emits oneOf for mixed-type fields.

        When OpenAPI metadata is available (openapi_required, openapi_field_schemas),
        uses it as authoritative source for required fields and field types.
        """
        if not samples or _depth > 20:
            return {"type": "object"}

        # Track types and sub-samples per field across all samples
        field_types: dict[str, list[str]] = defaultdict(list)
        field_presence: dict[str, int] = defaultdict(int)
        # For nested objects, collect sub-samples per field
        field_obj_samples: dict[str, list[dict[str, Any]]] = defaultdict(list)
        # For arrays, collect all elements per field
        field_arr_elements: dict[str, list[Any]] = defaultdict(list)

        total = len(samples)

        for sample in samples:
            for key, value in sample.items():
                field_presence[key] += 1
                type_str = self._type_string(value)
                field_types[key].append(type_str)

                if isinstance(value, dict):
                    field_obj_samples[key].append(value)
                elif isinstance(value, list):
                    field_arr_elements[key].extend(value)

        # Build properties
        properties: dict[str, dict[str, Any]] = {}
        for key in sorted(field_types):
            observed = field_types[key]
            unique_types = sorted(set(observed))

            if len(unique_types) == 1:
                # Single type across all samples
                t = unique_types[0]
                if t == "object" and field_obj_samples.get(key):
                    properties[key] = self._infer_schema(
                        field_obj_samples[key], _depth + 1
                    )
                elif t == "array":
                    properties[key] = self._infer_array_schema(
                        field_arr_elements.get(key, []), _depth + 1
                    )
                else:
                    properties[key] = {"type": t}
            else:
                # Mixed types -> oneOf
                oneof_items: list[dict[str, Any]] = []
                for t in unique_types:
                    if t == "object" and field_obj_samples.get(key):
                        oneof_items.append(
                            self._infer_schema(field_obj_samples[key], _depth + 1)
                        )
                    elif t == "array":
                        oneof_items.append(
                            self._infer_array_schema(
                                field_arr_elements.get(key, []), _depth + 1
                            )
                        )
                    else:
                        oneof_items.append({"type": t})
                properties[key] = {"oneOf": oneof_items}

        # Apply OpenAPI field type overrides when available
        if openapi_field_schemas:
            for field_name, field_meta in openapi_field_schemas.items():
                if field_name in properties:
                    prop = properties[field_name]
                    if isinstance(prop, dict) and "type" in field_meta:
                        prop["type"] = field_meta["type"]
                    if isinstance(prop, dict) and "enum" in field_meta:
                        prop["enum"] = field_meta["enum"]

        schema: dict[str, Any] = {"type": "object", "properties": properties}

        # Use OpenAPI required fields when available (authoritative),
        # otherwise infer from field presence across samples
        if openapi_required is not None:
            required = sorted(r for r in openapi_required if r in properties)
        else:
            required = sorted(k for k, count in field_presence.items() if count == total)
        if required:
            schema["required"] = required

        return schema

    def _infer_array_schema(
        self, elements: list[Any], _depth: int = 0
    ) -> dict[str, Any]:
        """Infer schema for an array field from all observed elements."""
        if not elements or _depth > 20:
            return {"type": "array"}

        # Collect types from all elements
        elem_types: set[str] = set()
        obj_samples: list[dict[str, Any]] = []
        arr_elements: list[Any] = []

        for elem in elements:
            elem_types.add(self._type_string(elem))
            if isinstance(elem, dict):
                obj_samples.append(elem)
            elif isinstance(elem, list):
                arr_elements.extend(elem)

        sorted_types = sorted(elem_types)

        if len(sorted_types) == 1:
            t = sorted_types[0]
            if t == "object" and obj_samples:
                items = self._infer_schema(obj_samples, _depth)
            elif t == "array":
                items = self._infer_array_schema(arr_elements, _depth)
            else:
                items = {"type": t}
        else:
            oneof: list[dict[str, Any]] = []
            for t in sorted_types:
                if t == "object" and obj_samples:
                    oneof.append(self._infer_schema(obj_samples, _depth))
                elif t == "array":
                    oneof.append(self._infer_array_schema(arr_elements, _depth))
                else:
                    oneof.append({"type": t})
            items = {"oneOf": oneof}

        return {"type": "array", "items": items}

    @staticmethod
    def _type_string(value: Any) -> str:
        """Return the JSON Schema type string for a Python value."""
        if value is None:
            return "null"
        if isinstance(value, bool):
            return "boolean"
        if isinstance(value, int):
            return "integer"
        if isinstance(value, float):
            return "number"
        if isinstance(value, str):
            return "string"
        if isinstance(value, list):
            return "array"
        if isinstance(value, dict):
            return "object"
        return "string"

    def _infer_type(self, value: Any, _depth: int = 0) -> dict[str, Any]:
        """Infer JSON schema type for a single value."""
        if value is None:
            return {"type": "null"}
        if isinstance(value, bool):
            return {"type": "boolean"}
        if isinstance(value, int):
            return {"type": "integer"}
        if isinstance(value, float):
            return {"type": "number"}
        if isinstance(value, str):
            return {"type": "string"}
        if isinstance(value, list):
            if value:
                return self._infer_array_schema(value, _depth + 1)
            return {"type": "array"}
        if isinstance(value, dict):
            return self._infer_schema([value], _depth + 1)

        return {"type": "string"}

    def _determine_risk_tier(
        self,
        method: str,
        path: str,
        is_auth_related: bool,
        has_pii: bool,
        is_first_party: bool,
    ) -> str:
        """Determine risk tier, capping read-only methods at medium."""
        tier = self._classify_risk(method, path, is_auth_related, has_pii, is_first_party)
        if method.upper() in ("GET", "HEAD", "OPTIONS") and RISK_ORDER.get(tier, 0) > RISK_ORDER["medium"]:
            tier = "medium"
        return tier

    def _classify_risk(
        self,
        method: str,
        path: str,
        is_auth_related: bool,
        has_pii: bool,
        is_first_party: bool,
    ) -> str:
        """Classify raw risk tier based on method, path, and context."""
        if is_auth_related:
            return "critical"

        if CRITICAL_PATH_KEYWORDS.search(path):
            return "critical"

        if HIGH_RISK_PATH_KEYWORDS.search(path):
            return "high"

        if method in ("DELETE",):
            return "high"

        if method in ("POST", "PUT", "PATCH"):
            if has_pii:
                return "high"
            return "medium"

        if has_pii:
            return "low"

        if not is_first_party:
            return "medium"

        return "safe"
