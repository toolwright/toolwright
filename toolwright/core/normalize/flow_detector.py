"""Flow detection engine for API sequence analysis.

Detects data dependencies between endpoints by analyzing which response
fields could feed into other endpoints' request parameters (path, query, body).
"""

from __future__ import annotations

from typing import Any

from toolwright.models.endpoint import Endpoint
from toolwright.models.flow import FlowEdge, FlowGraph

# Generic fields that appear everywhere and would produce noise
_GENERIC_FIELDS = {
    "type", "status", "state", "created_at", "updated_at",
    "deleted_at", "timestamp", "version", "count", "total",
    "page", "limit", "offset", "sort", "order", "format",
    "locale", "language", "currency", "description", "name",
    "title", "label", "value", "key", "data", "result",
    "results", "items", "error", "message", "code",
}


class FlowDetector:
    """Detect data flow dependencies between endpoints."""

    def detect(self, endpoints: list[Endpoint]) -> FlowGraph:
        """Analyze endpoints and return a flow graph of dependencies.

        For each endpoint's response schema fields, check if any other
        endpoint's request params have matching field names.
        """
        edges: list[FlowEdge] = []

        for source in endpoints:
            source_id = source.signature_id or source.tool_id or source.stable_id or source.id
            response_fields = self._extract_response_fields(source)
            if not response_fields:
                continue

            for target in endpoints:
                target_id = target.signature_id or target.tool_id or target.stable_id or target.id
                if source_id == target_id:
                    continue

                target_params = self._extract_target_params(target)
                if not target_params:
                    continue

                for field_name in response_fields:
                    if field_name in _GENERIC_FIELDS:
                        continue

                    # Exact match
                    if field_name in target_params:
                        edges.append(FlowEdge(
                            source_id=source_id,
                            target_id=target_id,
                            linking_field=field_name,
                            confidence=0.9,
                        ))
                        continue

                    # Suffix match: source has "id", target has "product_id"
                    # or source path has /products and target has "product_id"
                    for param_name in target_params:
                        if self._is_suffix_match(
                            field_name, param_name, source.path
                        ):
                            edges.append(FlowEdge(
                                source_id=source_id,
                                target_id=target_id,
                                linking_field=param_name,
                                confidence=0.6,
                            ))

        # Deduplicate: keep highest confidence per (source, target) pair
        edges = self._deduplicate_edges(edges)

        return FlowGraph(edges=edges)

    def _extract_response_fields(self, ep: Endpoint) -> set[str]:
        """Extract field names from response schema (top-level + array items)."""
        return self._collect_fields(ep.response_body_schema)

    def _extract_target_params(self, ep: Endpoint) -> set[str]:
        """Extract all parameter names a target endpoint expects."""
        params: set[str] = set()

        # Path and query parameters
        for param in ep.parameters:
            params.add(param.name)

        # Request body fields
        params |= self._collect_fields(ep.request_body_schema)

        return params

    def _collect_fields(
        self, schema: dict[str, Any] | None, depth: int = 0
    ) -> set[str]:
        """Collect field names from a JSON Schema, including array items."""
        if not schema or not isinstance(schema, dict) or depth > 5:
            return set()

        # Root array responses like [{"id": 1, ...}, ...] should contribute item fields.
        if schema.get("type") == "array":
            items = schema.get("items", {})
            if isinstance(items, dict):
                return self._collect_fields(items, depth + 1)
            return set()

        # Mixed-root schemas (object vs array) should still yield usable field names.
        oneof = schema.get("oneOf")
        if isinstance(oneof, list):
            merged: set[str] = set()
            for sub in oneof:
                if isinstance(sub, dict):
                    merged |= self._collect_fields(sub, depth + 1)
            return merged

        fields: set[str] = set()
        props = schema.get("properties", {})
        if not isinstance(props, dict):
            return fields

        for key, value in props.items():
            fields.add(key)
            if not isinstance(value, dict):
                continue
            # Recurse into array items
            items = value.get("items", {})
            if isinstance(items, dict):
                fields |= self._collect_fields(items, depth + 1)

        return fields

    def _is_suffix_match(
        self, response_field: str, param_name: str, source_path: str
    ) -> bool:
        """Check if param_name is a qualified version of response_field.

        For example: response_field="id", param_name="product_id",
        source_path="/api/v1/products" -> True (products produces product_id).
        """
        if response_field != "id":
            return False

        if not param_name.endswith("_id"):
            return False

        # Extract the prefix from param_name: "product_id" -> "product"
        prefix = param_name[:-3]  # remove "_id"
        if not prefix:
            return False

        # Check if the source path contains a segment matching the prefix
        segments = [
            s.lower().rstrip("s")  # naive depluralize
            for s in source_path.strip("/").split("/")
            if s and not s.startswith("{")
        ]

        return prefix.lower() in segments

    def _deduplicate_edges(self, edges: list[FlowEdge]) -> list[FlowEdge]:
        """Keep the highest-confidence edge per (source, target) pair."""
        best: dict[tuple[str, str], FlowEdge] = {}
        for edge in edges:
            key = (edge.source_id, edge.target_id)
            if key not in best or edge.confidence > best[key].confidence:
                best[key] = edge
        return sorted(
            best.values(),
            key=lambda e: (-e.confidence, e.source_id, e.target_id),
        )
