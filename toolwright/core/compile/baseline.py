"""Baseline snapshot generator for drift detection."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from toolwright.models.endpoint import Endpoint
from toolwright.models.scope import Scope
from toolwright.utils.schema_version import CURRENT_SCHEMA_VERSION


class BaselineGenerator:
    """Generate baseline snapshots for drift detection."""

    def generate(
        self,
        endpoints: list[Endpoint],
        scope: Scope | None = None,
        capture_id: str | None = None,
        generated_at: datetime | None = None,
    ) -> dict[str, Any]:
        """Generate a baseline snapshot from endpoints.

        Args:
            endpoints: List of endpoints to snapshot
            scope: Optional scope that was applied
            capture_id: Optional capture session ID

        Returns:
            Baseline snapshot as dict
        """
        # Build endpoint snapshots
        sorted_endpoints = sorted(
            endpoints,
            key=lambda ep: (ep.host, ep.method.upper(), ep.path, ep.signature_id),
        )

        endpoint_snapshots = []
        for endpoint in sorted_endpoints:
            snapshot = self._snapshot_endpoint(endpoint)
            endpoint_snapshots.append(snapshot)

        baseline: dict[str, Any] = {
            "version": "1.0.0",
            "schema_version": CURRENT_SCHEMA_VERSION,
            "generated_at": (generated_at or datetime.now(UTC)).isoformat(),
            "endpoint_count": len(sorted_endpoints),
            "endpoints": endpoint_snapshots,
        }

        if capture_id:
            baseline["capture_id"] = capture_id

        if scope:
            baseline["scope"] = scope.name

        # Add summary statistics
        baseline["summary"] = self._build_summary(sorted_endpoints)

        return baseline

    def _snapshot_endpoint(self, endpoint: Endpoint) -> dict[str, Any]:
        """Create a snapshot of an endpoint for drift comparison.

        Args:
            endpoint: Endpoint to snapshot

        Returns:
            Endpoint snapshot dict
        """
        return {
            # Identity
            "stable_id": endpoint.stable_id,
            "signature_id": endpoint.signature_id,
            "tool_id": endpoint.tool_id,
            "tool_version": endpoint.tool_version,
            # Location
            "method": endpoint.method,
            "path": endpoint.path,
            "host": endpoint.host,
            # Parameters
            "parameters": [
                {
                    "name": p.name,
                    "location": p.location.value,
                    "type": p.param_type,
                    "required": p.required,
                }
                for p in sorted(
                    endpoint.parameters,
                    key=lambda param: (param.location.value, param.name),
                )
            ],
            # Request
            "request_content_type": endpoint.request_content_type,
            "request_schema": endpoint.request_body_schema,
            # Response
            "response_status_codes": endpoint.response_status_codes,
            "response_content_type": endpoint.response_content_type,
            "response_schema": endpoint.response_body_schema,
            # Classification
            "auth_type": endpoint.auth_type.value,
            "is_first_party": endpoint.is_first_party,
            "is_state_changing": endpoint.is_state_changing,
            "is_auth_related": endpoint.is_auth_related,
            "has_pii": endpoint.has_pii,
            "risk_tier": endpoint.risk_tier,
            # Metadata
            "observation_count": endpoint.observation_count,
        }

    def _build_summary(self, endpoints: list[Endpoint]) -> dict[str, Any]:
        """Build summary statistics for the baseline.

        Args:
            endpoints: List of endpoints

        Returns:
            Summary statistics dict
        """
        hosts = set()
        methods: dict[str, int] = {}
        risk_tiers: dict[str, int] = {}

        state_changing = 0
        auth_related = 0
        has_pii = 0

        for endpoint in endpoints:
            hosts.add(endpoint.host)

            method = endpoint.method
            methods[method] = methods.get(method, 0) + 1

            tier = endpoint.risk_tier
            risk_tiers[tier] = risk_tiers.get(tier, 0) + 1

            if endpoint.is_state_changing:
                state_changing += 1
            if endpoint.is_auth_related:
                auth_related += 1
            if endpoint.has_pii:
                has_pii += 1

        return {
            "host_count": len(hosts),
            "hosts": sorted(hosts),
            "methods": dict(sorted(methods.items())),
            "risk_tiers": dict(sorted(risk_tiers.items())),
            "state_changing_count": state_changing,
            "auth_related_count": auth_related,
            "pii_count": has_pii,
        }

    def to_json(self, baseline: dict[str, Any]) -> str:
        """Serialize baseline to JSON string.

        Args:
            baseline: Baseline dict

        Returns:
            JSON string
        """
        import json

        return json.dumps(baseline, indent=2)
