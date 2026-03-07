"""Tool manifest generator for agent consumption."""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from typing import Any

from toolwright.models.endpoint import Endpoint
from toolwright.models.flow import FlowGraph
from toolwright.models.scope import Scope
from toolwright.utils.naming import generate_tool_name, resolve_collision
from toolwright.utils.schema_version import CURRENT_SCHEMA_VERSION


class ToolManifestGenerator:
    """Generate tool manifests from endpoints for agent consumption."""

    # Risk tier to confirmation mapping
    CONFIRMATION_MAP = {
        "safe": "never",
        "low": "never",
        "medium": "on_risk",
        "high": "always",
        "critical": "always",
    }

    # Default rate limits by risk tier
    RATE_LIMIT_MAP = {
        "safe": 120,
        "low": 60,
        "medium": 30,
        "high": 10,
        "critical": 5,
    }

    def __init__(
        self,
        name: str = "Generated Tools",
        description: str | None = None,
        default_rate_limit: int | None = None,
    ) -> None:
        """Initialize the tool manifest generator.

        Args:
            name: Name for the tool manifest
            description: Optional description
            default_rate_limit: Default rate limit per minute
        """
        self.name = name
        self.description = description
        self.default_rate_limit = default_rate_limit

    def generate(
        self,
        endpoints: list[Endpoint],
        scope: Scope | None = None,
        capture_id: str | None = None,
        generated_at: datetime | None = None,
        flow_graph: FlowGraph | None = None,
    ) -> dict[str, Any]:
        """Generate a tool manifest from endpoints.

        Args:
            endpoints: List of endpoints to convert to actions
            scope: Optional scope that was applied
            capture_id: Optional capture session ID

        Returns:
            Tool manifest as dict
        """
        sorted_endpoints = sorted(
            endpoints,
            key=lambda ep: (ep.host, ep.method.upper(), ep.path, ep.signature_id),
        )

        # Collect unique hosts
        hosts = sorted({ep.host for ep in sorted_endpoints})

        # Generate actions with unique names
        actions = []
        used_names: set[str] = set()
        sig_to_name: dict[str, str] = {}

        for endpoint in sorted_endpoints:
            endpoint_actions = self._actions_from_endpoint(endpoint, used_names)
            for idx, action in enumerate(endpoint_actions):
                if scope:
                    action["scopes"] = [scope.name]
                actions.append(action)
                signature_key = str(action.get("signature_id") or action.get("tool_id") or action["name"])
                sig_to_name[signature_key] = action["name"]
                if idx == 0:
                    # Preserve flow mapping from endpoint signature to at least one generated action.
                    endpoint_signature = endpoint.signature_id or endpoint.tool_id or action["name"]
                    sig_to_name.setdefault(endpoint_signature, action["name"])

        # Enrich with flow metadata (depends_on / enables)
        if flow_graph:
            self._apply_flow_metadata(actions, flow_graph, sig_to_name)

        manifest: dict[str, Any] = {
            "version": "1.0.0",
            "schema_version": CURRENT_SCHEMA_VERSION,
            "name": self.name,
            "generated_at": (generated_at or datetime.now(UTC)).isoformat(),
            "allowed_hosts": hosts,
            "actions": actions,
        }

        if self.description:
            manifest["description"] = self.description

        if capture_id:
            manifest["capture_id"] = capture_id

        if scope:
            manifest["scope"] = scope.name
            manifest["default_confirmation"] = (
                "always" if scope.confirmation_required else "on_risk"
            )
            if scope.rate_limit_per_minute:
                manifest["default_rate_limit"] = scope.rate_limit_per_minute

        if self.default_rate_limit:
            manifest["default_rate_limit"] = self.default_rate_limit

        return manifest

    def _actions_from_endpoint(
        self,
        endpoint: Endpoint,
        used_names: set[str],
    ) -> list[dict[str, Any]]:
        """Create one or more actions from an endpoint."""
        graphql_operations = self._extract_graphql_operations(endpoint)
        if not graphql_operations:
            return [self._action_from_endpoint(endpoint, used_names)]
        graphql_operation_types = self._infer_graphql_operation_types(endpoint)

        return [
            self._action_from_endpoint(
                endpoint,
                used_names,
                graphql_operation_name=operation_name,
                graphql_operation_type=graphql_operation_types.get(operation_name),
            )
            for operation_name in graphql_operations
        ]

    def _action_from_endpoint(
        self,
        endpoint: Endpoint,
        used_names: set[str],
        graphql_operation_name: str | None = None,
        graphql_operation_type: str | None = None,
    ) -> dict[str, Any]:
        """Create an action from an endpoint.

        Args:
            endpoint: Endpoint to convert
            used_names: Set of already-used action names

        Returns:
            Action dict
        """
        # Generate unique name
        base_name = self._base_action_name(
            endpoint,
            graphql_operation_name,
            graphql_operation_type,
        )
        name = resolve_collision(base_name, used_names, endpoint.host)
        used_names.add(name)

        # Build input schema
        input_schema, wrapper_key = self._build_input_schema(endpoint)
        fixed_body: dict[str, Any] | None = None
        if graphql_operation_name:
            fixed_body = self._graphql_fixed_body(endpoint, graphql_operation_name)
            self._apply_fixed_body_schema(input_schema, fixed_body)

        # Build output schema
        output_schema = endpoint.response_body_schema

        # Determine confirmation requirement
        confirmation = self.CONFIRMATION_MAP.get(endpoint.risk_tier, "on_risk")
        if endpoint.is_state_changing and confirmation == "never":
            confirmation = "on_risk"

        # Determine rate limit
        rate_limit = self.RATE_LIMIT_MAP.get(endpoint.risk_tier, 30)
        signature = endpoint.signature_id
        if graphql_operation_name:
            signature = self._graphql_operation_signature(endpoint, graphql_operation_name)

        action: dict[str, Any] = {
            "id": name,
            "tool_id": signature,
            "name": name,
            "description": self._generate_description(
                endpoint,
                graphql_operation_name,
                graphql_operation_type,
            ),
            "endpoint_id": endpoint.stable_id,
            "signature_id": signature,
            "method": endpoint.method,
            "path": endpoint.path,
            "host": endpoint.host,
            "input_schema": input_schema,
            "risk_tier": endpoint.risk_tier,
            "confirmation_required": confirmation,
            "rate_limit_per_minute": rate_limit,
            "tags": self._extract_tags(endpoint, graphql_operation_type),
        }
        if graphql_operation_name:
            action["graphql_operation_name"] = graphql_operation_name
            if fixed_body:
                action["fixed_body"] = fixed_body
        if graphql_operation_type:
            action["graphql_operation_type"] = graphql_operation_type

        if output_schema:
            action["output_schema"] = output_schema

        if wrapper_key:
            action["request_body_wrapper"] = wrapper_key

        return action

    def _build_input_schema(self, endpoint: Endpoint) -> tuple[dict[str, Any], str | None]:
        """Build JSON Schema for action input.

        Args:
            endpoint: Endpoint to build schema for

        Returns:
            Tuple of (JSON Schema dict, wrapper_key or None)
        """
        properties: dict[str, Any] = {}
        required: list[str] = []

        # Add parameters
        sorted_parameters = sorted(
            endpoint.parameters,
            key=lambda p: (p.location.value, p.name),
        )

        for param in sorted_parameters:
            prop: dict[str, Any] = {
                "type": param.param_type,
            }

            if param.description:
                prop["description"] = param.description
            if param.example is not None:
                prop["example"] = param.example
            if param.pattern:
                prop["pattern"] = param.pattern
            if param.default is not None:
                prop["default"] = param.default

            if self._is_nextjs_build_id_param(endpoint, param.name, param.location.value):
                # Next.js build IDs are deployment-derived and should never be user-supplied.
                prop.setdefault(
                    "description",
                    "Derived Next.js build ID (auto-resolved at runtime).",
                )
                prop["x-toolwright-resolver"] = {
                    "name": "nextjs_build_id",
                    "source": "runtime",
                    "description": "Resolve Next.js build ID from __NEXT_DATA__ before request execution.",
                }
                properties[param.name] = prop
                # Do not mark derived parameters as required.
                continue

            properties[param.name] = prop

            if param.required:
                required.append(param.name)

        # Add body schema properties if present, detecting envelope wrappers
        wrapper_key: str | None = None
        if endpoint.request_body_schema:
            body_props = endpoint.request_body_schema.get("properties", {})
            body_required = endpoint.request_body_schema.get("required", [])

            # Detect envelope wrapper: exactly 1 top-level property whose type
            # is "object" with its own sub-properties.
            if len(body_props) == 1:
                only_key = next(iter(body_props))
                only_val = body_props[only_key]
                if (
                    isinstance(only_val, dict)
                    and only_val.get("type") == "object"
                    and only_val.get("properties")
                ):
                    # Envelope detected: flatten inner properties
                    wrapper_key = only_key
                    inner_props = only_val.get("properties", {})
                    inner_required = only_val.get("required", [])
                    for prop_name, prop_schema in inner_props.items():
                        if prop_name not in properties:
                            properties[prop_name] = prop_schema
                            if prop_name in inner_required:
                                required.append(prop_name)

            # No envelope detected: add body props directly
            if wrapper_key is None:
                for prop_name, prop_schema in body_props.items():
                    if prop_name not in properties:
                        properties[prop_name] = prop_schema
                        if prop_name in body_required:
                            required.append(prop_name)

        schema: dict[str, Any] = {
            "type": "object",
            "properties": properties,
        }

        if required:
            schema["required"] = sorted(set(required))

        return schema, wrapper_key

    # Endpoints that are not collections despite being GET without trailing {param}
    _SINGLETON_SEGMENTS = {"health", "status", "ping", "ready", "alive", "version", "info", "me", "self", "whoami"}

    # POST endpoints that perform queries rather than creating resources
    _QUERY_SEGMENTS = {"search", "query", "graphql", "filter", "lookup", "find"}

    def _generate_description(
        self,
        endpoint: Endpoint,
        graphql_operation_name: str | None = None,
        graphql_operation_type: str | None = None,
    ) -> str:
        """Generate an agent-friendly description for an action.

        Includes: verb + resource, path parameters, top response fields,
        risk warnings. Fixes pluralization and article issues.
        """
        method = endpoint.method.upper()
        path = endpoint.path

        # Extract resource name
        segments = [s for s in path.split("/") if s and not s.startswith("{")]
        resource = segments[-1].replace("_", " ").replace("-", " ") if segments else "resource"

        # Detect collection vs single resource
        is_collection = not path.rstrip("/").endswith("}")

        # Singularize for non-collection endpoints
        singular = self._singularize(resource)

        # Path parameter names
        path_params = [s[1:-1] for s in path.split("/") if s.startswith("{") and s.endswith("}")]

        # Check for singleton/utility endpoints
        last_segment = segments[-1].lower() if segments else ""
        is_singleton = last_segment in self._SINGLETON_SEGMENTS
        is_query = last_segment in self._QUERY_SEGMENTS

        # Build description
        # Detect parent resource for nested collections (e.g., /albums/{id}/photos)
        parent_resource = None
        if is_collection and path_params:
            # Find the segment before the last {param}
            parts = path.strip("/").split("/")
            for i, part in enumerate(parts):
                if part.startswith("{") and part.endswith("}") and i > 0:
                    candidate = parts[i - 1]
                    if not candidate.startswith("{"):
                        parent_resource = self._singularize(
                            candidate.replace("_", " ").replace("-", " ")
                        )

        if method == "GET":
            if is_singleton:
                base = f"Check {resource} status"
            elif is_collection and parent_resource:
                base = f"List {resource} for {self._article(parent_resource)} {parent_resource}"
            elif is_collection:
                base = f"List all {resource}"
            elif path_params:
                base = f"Retrieve {self._article(singular)} {singular} by {{{path_params[-1]}}}"
            else:
                base = f"Retrieve {singular}"
        elif method == "POST":
            if is_query:
                if graphql_operation_name:
                    if graphql_operation_type in {"query", "mutation", "subscription"}:
                        base = f"Run GraphQL {graphql_operation_type} {graphql_operation_name}"
                    else:
                        base = f"Run GraphQL operation {graphql_operation_name}"
                else:
                    base = f"Search via {resource}"
            else:
                base = f"Create {self._article(singular, new=True)} new {singular}"
        elif method == "PUT":
            if path_params:
                base = f"Update {self._article(singular)} {singular} by {{{path_params[-1]}}}"
            else:
                base = f"Update {singular}"
        elif method == "PATCH":
            if path_params:
                base = f"Partially update {self._article(singular)} {singular} by {{{path_params[-1]}}}"
            else:
                base = f"Partially update {singular}"
        elif method == "DELETE":
            if path_params:
                base = f"Delete {self._article(singular)} {singular} by {{{path_params[-1]}}}"
            else:
                base = f"Delete {singular}"
        else:
            base = f"{method} {resource}"

        # Append top response fields
        fields_hint = self._response_fields_hint(endpoint)
        if fields_hint:
            base += f". Returns: {fields_hint}"

        # Add risk warning if needed
        if endpoint.risk_tier in ("high", "critical"):
            base += f" (Risk: {endpoint.risk_tier})"

        if endpoint.is_auth_related:
            base += " [Auth]"

        # Prepend "Use this to..." guidance based on domain tags
        guidance = self._tag_guidance(endpoint.tags)
        if guidance:
            base = f"Use this to {guidance}. {base}"

        return base

    def _apply_flow_metadata(
        self,
        actions: list[dict[str, Any]],
        flow_graph: FlowGraph,
        sig_to_name: dict[str, str],
    ) -> None:
        """Add depends_on / enables fields and dependency hints to actions."""
        name_to_action: dict[str, dict[str, Any]] = {a["name"]: a for a in actions}

        for edge in flow_graph.edges:
            source_name = sig_to_name.get(edge.source_id)
            target_name = sig_to_name.get(edge.target_id)
            if not source_name or not target_name:
                continue
            if source_name not in name_to_action or target_name not in name_to_action:
                continue

            # Source enables target
            source_action = name_to_action[source_name]
            source_action.setdefault("enables", [])
            if target_name not in source_action["enables"]:
                source_action["enables"].append(target_name)

            # Target depends on source
            target_action = name_to_action[target_name]
            target_action.setdefault("depends_on", [])
            if source_name not in target_action["depends_on"]:
                target_action["depends_on"].append(source_name)

            # Add dependency hint to target description
            desc = target_action.get("description", "")
            hint = f" (Call {source_name} first to obtain {edge.linking_field})"
            if hint not in desc:
                target_action["description"] = desc + hint

    # Domain tag -> guidance phrase
    _TAG_GUIDANCE_MAP: dict[str, str] = {
        "commerce": "browse or manage commerce data",
        "users": "access or manage user information",
        "auth": "handle authentication",
        "admin": "perform admin operations",
        "search": "search or query data",
        "content": "access or manage content",
        "notifications": "manage notifications or alerts",
    }

    def _tag_guidance(self, tags: list[str]) -> str:
        """Return a 'Use this to ...' guidance phrase based on domain tags."""
        for tag in tags:
            if tag in self._TAG_GUIDANCE_MAP:
                return self._TAG_GUIDANCE_MAP[tag]
        return ""

    @staticmethod
    def _singularize(word: str) -> str:
        """Naive singularization for resource names."""
        w = word.strip()
        if w.endswith("ies"):
            return w[:-3] + "y"
        if w.endswith("ses") or w.endswith("xes") or w.endswith("zes"):
            return w[:-2]
        if w.endswith("s") and not w.endswith("ss"):
            return w[:-1]
        return w

    # Words starting with vowel letters that use consonant sounds ("a user", "a union")
    _CONSONANT_SOUND_PREFIXES = {"uni", "use", "user", "usa", "util", "unic", "uran"}

    @staticmethod
    def _article(word: str, new: bool = False) -> str:
        """Return 'a' or 'an' based on the word's initial sound."""
        if new:
            return "a"
        w = word.strip().lower()
        first = w[:1]
        if first in "aeiou":
            # Check for consonant-sound exceptions (user, utility, etc.)
            for prefix in ToolManifestGenerator._CONSONANT_SOUND_PREFIXES:
                if w.startswith(prefix):
                    return "a"
            return "an"
        return "a"

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

    def _extract_tags(
        self,
        endpoint: Endpoint,
        graphql_operation_type: str | None = None,
    ) -> list[str]:
        """Extract tags from endpoint."""
        tags: list[str] = []

        # Extract from path
        segments = endpoint.path.strip("/").split("/")
        skip = {"api", "v1", "v2", "v3", "rest", "public", "private"}

        for segment in segments:
            if segment.lower() not in skip and not segment.startswith("{"):
                tags.append(segment)
                break

        # Add risk-based tags
        if graphql_operation_type == "query":
            tags.append("read")
        elif endpoint.is_state_changing:
            tags.append("write")
        else:
            tags.append("read")

        if endpoint.is_auth_related:
            tags.append("auth")

        if endpoint.has_pii:
            tags.append("pii")

        return tags

    def _extract_graphql_operations(self, endpoint: Endpoint) -> list[str]:
        """Return sorted unique GraphQL operation names observed for an endpoint."""
        if endpoint.method.upper() != "POST":
            return []
        if "/graphql" not in endpoint.path.lower():
            return []

        operations: set[str] = set()
        for sample in endpoint.request_examples:
            if not isinstance(sample, dict):
                continue
            raw_name = sample.get("operationName")
            if not isinstance(raw_name, str):
                continue
            operation_name = raw_name.strip()
            if operation_name:
                operations.add(operation_name)

        return sorted(operations)

    def _infer_graphql_operation_types(self, endpoint: Endpoint) -> dict[str, str]:
        """Infer GraphQL operation type by operationName from captured samples."""
        operation_types: dict[str, set[str]] = {}
        observed_operation_names: set[str] = set()

        for sample in endpoint.request_examples:
            if not isinstance(sample, dict):
                continue
            raw_name = sample.get("operationName")
            if not isinstance(raw_name, str):
                continue
            operation_name = raw_name.strip()
            if not operation_name:
                continue
            observed_operation_names.add(operation_name)
            operation_type = self._graphql_operation_type_from_sample(sample)
            if not operation_type:
                continue
            operation_types.setdefault(operation_name, set()).add(operation_type)

        resolved: dict[str, str] = {}
        for operation_name, candidates in operation_types.items():
            # Conservative precedence if conflicting samples are observed.
            if "mutation" in candidates:
                resolved[operation_name] = "mutation"
                continue
            if "subscription" in candidates:
                resolved[operation_name] = "subscription"
                continue
            if "query" in candidates:
                resolved[operation_name] = "query"

        # Fall back to operationName heuristics for persisted-query captures that
        # do not include raw GraphQL document text.
        for operation_name in observed_operation_names:
            if operation_name in resolved:
                continue
            heuristic_type = self._graphql_operation_type_from_name(operation_name)
            if heuristic_type:
                resolved[operation_name] = heuristic_type

        return resolved

    def _graphql_operation_type_from_sample(self, sample: dict[str, Any]) -> str | None:
        """Infer operation type from a single GraphQL request example."""
        query_raw = sample.get("query")
        if not isinstance(query_raw, str):
            return None

        query = query_raw.strip()
        if not query:
            return None

        # Anonymous shorthand `{ viewer { id } }` implies query.
        if query.startswith("{"):
            return "query"

        # Strip leading comment-only lines before checking operation keyword.
        candidate_lines = []
        for line in query.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            candidate_lines.append(stripped)
        candidate = " ".join(part for part in candidate_lines if part).lower()
        if not candidate:
            return None

        for operation_type in ("mutation", "subscription", "query"):
            if candidate.startswith(operation_type):
                return operation_type

        return None

    def _graphql_operation_type_from_name(self, operation_name: str) -> str | None:
        """Best-effort type inference from operationName tokens."""
        tokens = [t for t in self._to_snake_case(operation_name).split("_") if t]
        if not tokens:
            return None

        write_tokens = {
            "add",
            "apply",
            "bid",
            "cancel",
            "checkout",
            "claim",
            "confirm",
            "create",
            "delete",
            "insert",
            "log",
            "mark",
            "mutate",
            "patch",
            "place",
            "post",
            "record",
            "remove",
            "replace",
            "save",
            "set",
            "submit",
            "track",
            "update",
            "upsert",
            "write",
        }
        read_tokens = {
            "detail",
            "fetch",
            "find",
            "get",
            "history",
            "list",
            "lookup",
            "read",
            "recent",
            "recently",
            "recommended",
            "search",
            "view",
            "viewed",
        }

        if any(token in write_tokens for token in tokens):
            return "mutation"
        if any(token in read_tokens for token in tokens):
            return "query"
        return None

    def _base_action_name(
        self,
        endpoint: Endpoint,
        graphql_operation_name: str | None,
        graphql_operation_type: str | None,
    ) -> str:
        """Resolve action base name for endpoint and optional GraphQL operation."""
        if graphql_operation_name:
            op = self._to_snake_case(graphql_operation_name)
            if graphql_operation_type == "mutation":
                prefix = "mutate"
            elif graphql_operation_type == "subscription":
                prefix = "subscribe"
            else:
                prefix = "query"
            if op:
                return f"{prefix}_{op}"
            return prefix
        return endpoint.tool_id or generate_tool_name(endpoint.method, endpoint.path)

    def _graphql_operation_signature(self, endpoint: Endpoint, graphql_operation_name: str) -> str:
        """Create a stable signature for a GraphQL operation-specific action."""
        base = endpoint.signature_id or endpoint.compute_signature_id()
        canonical = f"{base}:graphql:{graphql_operation_name}"
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]

    def _apply_fixed_body_schema(self, schema: dict[str, Any], fixed_body: dict[str, Any]) -> None:
        """Constrain input schema for fixed body fields applied automatically at runtime."""
        properties = schema.setdefault("properties", {})
        required_raw = schema.get("required")
        required = (
            {str(item) for item in required_raw if isinstance(item, str)}
            if isinstance(required_raw, list)
            else set()
        )

        for key, value in sorted(fixed_body.items()):
            existing = properties.get(key)
            field_schema = dict(existing) if isinstance(existing, dict) else {}
            field_schema.setdefault("type", self._json_type_name(value))
            field_schema["enum"] = [value]
            field_schema["default"] = value
            field_schema.setdefault(
                "description",
                "Fixed value populated automatically at runtime.",
            )
            properties[key] = field_schema
            required.discard(key)

        if required:
            schema["required"] = sorted(required)
        else:
            schema.pop("required", None)

    def _graphql_fixed_body(self, endpoint: Endpoint, graphql_operation_name: str) -> dict[str, Any]:
        """Build fixed GraphQL request fields for an operation-scoped action."""
        fixed: dict[str, Any] = {"operationName": graphql_operation_name}

        query_texts: set[str] = set()
        extensions_payloads: dict[str, dict[str, Any]] = {}

        for sample in endpoint.request_examples:
            if not isinstance(sample, dict):
                continue
            raw_name = sample.get("operationName")
            if not isinstance(raw_name, str) or raw_name.strip() != graphql_operation_name:
                continue

            query_raw = sample.get("query")
            if isinstance(query_raw, str):
                query = query_raw.strip()
                if query:
                    query_texts.add(query)

            extensions_raw = sample.get("extensions")
            if isinstance(extensions_raw, dict) and extensions_raw:
                import json

                key = json.dumps(extensions_raw, sort_keys=True)
                extensions_payloads.setdefault(key, extensions_raw)

        if len(query_texts) == 1:
            fixed["query"] = next(iter(query_texts))

        if len(extensions_payloads) == 1:
            fixed["extensions"] = next(iter(extensions_payloads.values()))

        return fixed

    @staticmethod
    def _json_type_name(value: Any) -> str:
        if value is None:
            return "string"
        if isinstance(value, bool):
            return "boolean"
        if isinstance(value, int) and not isinstance(value, bool):
            return "integer"
        if isinstance(value, float):
            return "number"
        if isinstance(value, dict):
            return "object"
        if isinstance(value, list):
            return "array"
        return "string"

    @staticmethod
    def _is_nextjs_build_id_param(endpoint: Endpoint, name: str, location: str) -> bool:
        """Return True for Next.js buildId-style path parameters."""
        if location != "path":
            return False
        candidate = name.lower()
        if candidate not in {"token", "build_id", "buildid"}:
            return False
        path = endpoint.path.lower()
        return f"/_next/data/{{{candidate}}}/" in path

    @staticmethod
    def _to_snake_case(value: str) -> str:
        """Normalize an operation name to snake_case."""
        value = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value)
        value = value.replace("-", "_")
        value = value.replace(" ", "_")
        value = re.sub(r"[^A-Za-z0-9_]+", "_", value)
        value = re.sub(r"_+", "_", value)
        return value.strip("_").lower()

    def to_json(self, manifest: dict[str, Any]) -> str:
        """Serialize manifest to JSON string.

        Args:
            manifest: Tool manifest dict

        Returns:
            JSON string
        """
        import json

        return json.dumps(manifest, indent=2)
