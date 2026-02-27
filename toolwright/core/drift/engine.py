"""Drift detection engine."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from toolwright.models.drift import DriftItem, DriftReport, DriftSeverity, DriftType
from toolwright.models.endpoint import Endpoint
from toolwright.models.flow import FlowGraph
from toolwright.utils.schema_version import CURRENT_SCHEMA_VERSION, resolve_generated_at


class DriftEngine:
    """Engine for detecting drift between endpoint sets."""

    def __init__(self) -> None:
        """Initialize drift engine state."""
        self._deterministic = False

    def compare(
        self,
        from_endpoints: list[Endpoint],
        to_endpoints: list[Endpoint],
        from_capture_id: str | None = None,
        to_capture_id: str | None = None,
        deterministic: bool = False,
        flow_graph: FlowGraph | None = None,
    ) -> DriftReport:
        """Compare two sets of endpoints for drift.

        Args:
            from_endpoints: Original/baseline endpoints
            to_endpoints: New/current endpoints
            from_capture_id: Optional ID of from capture
            to_capture_id: Optional ID of to capture

        Returns:
            DriftReport with all detected drifts
        """
        self._deterministic = deterministic
        drifts: list[DriftItem] = []

        # Build lookup maps
        from_map = self._build_endpoint_map(from_endpoints)
        to_map = self._build_endpoint_map(to_endpoints)

        # Detect removed endpoints
        for key, endpoint in from_map.items():
            if key not in to_map:
                drifts.append(self._create_removal_drift(endpoint))

        # Detect added and modified endpoints
        for key, endpoint in to_map.items():
            if key not in from_map:
                drifts.append(self._create_addition_drift(endpoint))
            else:
                # Endpoint exists in both - check for modifications
                old_endpoint = from_map[key]
                modification_drifts = self._detect_modifications(old_endpoint, endpoint)
                drifts.extend(modification_drifts)

        # Flow-aware drift: flag broken flows
        if flow_graph:
            flow_drifts = self._detect_flow_drift(
                from_endpoints, to_endpoints, flow_graph
            )
            drifts.extend(flow_drifts)

        return self._create_report(
            drifts,
            from_capture_id=from_capture_id,
            to_capture_id=to_capture_id,
        )

    def compare_to_baseline(
        self,
        baseline: dict[str, Any],
        endpoints: list[Endpoint],
        deterministic: bool = False,
    ) -> DriftReport:
        """Compare endpoints against a baseline snapshot.

        Args:
            baseline: Baseline snapshot dict
            endpoints: Current endpoints

        Returns:
            DriftReport with detected drifts
        """
        self._deterministic = deterministic
        drifts: list[DriftItem] = []

        # Convert baseline snapshots to comparable format
        baseline_map = {}
        for snap in baseline.get("endpoints", []):
            key = self._snapshot_to_key(snap)
            baseline_map[key] = snap

        # Build current endpoint map
        current_map = {}
        for ep in endpoints:
            key = (ep.host, ep.method.upper(), ep.path)
            current_map[key] = ep

        # Detect removed endpoints
        for key, snap in baseline_map.items():
            if key not in current_map:
                drifts.append(self._create_removal_drift_from_snapshot(snap))

        # Detect added and modified endpoints
        for key, endpoint in current_map.items():
            if key not in baseline_map:
                drifts.append(self._create_addition_drift(endpoint))
            else:
                snap = baseline_map[key]
                modification_drifts = self._detect_modifications_from_snapshot(
                    snap, endpoint
                )
                drifts.extend(modification_drifts)

        return self._create_report(
            drifts,
            from_baseline_id=baseline.get("capture_id"),
        )

    def _drift_id(
        self,
        *,
        drift_type: DriftType,
        severity: DriftSeverity,
        endpoint_id: str | None,
        method: str | None,
        path: str | None,
        title: str,
        description: str,
        before: Any | None = None,
        after: Any | None = None,
    ) -> str:
        """Generate a drift item ID."""
        if not self._deterministic:
            return f"d_{uuid.uuid4().hex[:8]}"

        payload = {
            "type": drift_type.value,
            "severity": severity.value,
            "endpoint_id": endpoint_id,
            "method": method,
            "path": path,
            "title": title,
            "description": description,
            "before": before,
            "after": after,
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        digest = hashlib.sha256(canonical.encode()).hexdigest()[:12]
        return f"d_{digest}"

    def _make_drift_item(
        self,
        *,
        drift_type: DriftType,
        severity: DriftSeverity,
        endpoint_id: str | None,
        method: str | None,
        path: str | None,
        title: str,
        description: str,
        before: Any | None = None,
        after: Any | None = None,
        recommendation: str | None = None,
    ) -> DriftItem:
        """Build drift item with deterministic/non-deterministic ID semantics."""
        return DriftItem(
            id=self._drift_id(
                drift_type=drift_type,
                severity=severity,
                endpoint_id=endpoint_id,
                method=method,
                path=path,
                title=title,
                description=description,
                before=before,
                after=after,
            ),
            type=drift_type,
            severity=severity,
            endpoint_id=endpoint_id,
            path=path,
            method=method,
            title=title,
            description=description,
            before=before,
            after=after,
            recommendation=recommendation,
        )

    def _report_id(
        self,
        *,
        drifts: list[DriftItem],
        from_capture_id: str | None,
        to_capture_id: str | None,
        from_baseline_id: str | None,
    ) -> str:
        """Generate drift report ID."""
        if not self._deterministic:
            return f"drift_{datetime.now(UTC).strftime('%Y%m%d')}_{uuid.uuid4().hex[:8]}"

        payload = {
            "from_capture_id": from_capture_id,
            "to_capture_id": to_capture_id,
            "from_baseline_id": from_baseline_id,
            "drift_ids": [d.id for d in drifts],
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        digest = hashlib.sha256(canonical.encode()).hexdigest()[:12]
        return f"drift_{digest}"

    def _build_endpoint_map(
        self, endpoints: list[Endpoint]
    ) -> dict[tuple[str, str, str], Endpoint]:
        """Build a map of (host, method, path) -> endpoint."""
        return {
            (ep.host, ep.method.upper(), ep.path): ep
            for ep in endpoints
        }

    def _snapshot_to_key(self, snap: dict[str, Any]) -> tuple[str, str, str]:
        """Convert snapshot to lookup key."""
        return (snap["host"], snap["method"].upper(), snap["path"])

    def _create_removal_drift(self, endpoint: Endpoint) -> DriftItem:
        """Create a drift item for a removed endpoint."""
        return self._make_drift_item(
            drift_type=DriftType.BREAKING,
            severity=DriftSeverity.CRITICAL,
            endpoint_id=endpoint.stable_id,
            path=endpoint.path,
            method=endpoint.method,
            title="Endpoint removed",
            description=f"{endpoint.method} {endpoint.path} was removed",
            before={"method": endpoint.method, "path": endpoint.path},
            after=None,
            recommendation="Restore endpoint or update consumers",
        )

    def _create_removal_drift_from_snapshot(self, snap: dict[str, Any]) -> DriftItem:
        """Create a drift item for a removed endpoint from snapshot."""
        return self._make_drift_item(
            drift_type=DriftType.BREAKING,
            severity=DriftSeverity.CRITICAL,
            endpoint_id=snap.get("stable_id"),
            path=snap["path"],
            method=snap["method"],
            title="Endpoint removed",
            description=f"{snap['method']} {snap['path']} was removed",
            before={"method": snap["method"], "path": snap["path"]},
            after=None,
            recommendation="Restore endpoint or update consumers",
        )

    def _create_addition_drift(self, endpoint: Endpoint) -> DriftItem:
        """Create a drift item for an added endpoint."""
        # Determine if this is risky or additive
        is_risky = (
            endpoint.is_state_changing
            or endpoint.method.upper() in ("POST", "PUT", "PATCH", "DELETE")
        )

        if is_risky:
            return self._make_drift_item(
                drift_type=DriftType.RISK,
                severity=DriftSeverity.WARNING,
                endpoint_id=endpoint.stable_id,
                path=endpoint.path,
                method=endpoint.method,
                title="New state-changing endpoint",
                description=f"{endpoint.method} {endpoint.path} was added",
                before=None,
                after={"method": endpoint.method, "path": endpoint.path},
                recommendation="Review and add to policy before enabling",
            )
        else:
            return self._make_drift_item(
                drift_type=DriftType.ADDITIVE,
                severity=DriftSeverity.INFO,
                endpoint_id=endpoint.stable_id,
                path=endpoint.path,
                method=endpoint.method,
                title="New read-only endpoint",
                description=f"{endpoint.method} {endpoint.path} was added",
                before=None,
                after={"method": endpoint.method, "path": endpoint.path},
            )

    def _detect_modifications(
        self, old: Endpoint, new: Endpoint
    ) -> list[DriftItem]:
        """Detect modifications between two versions of the same endpoint."""
        drifts = []

        # Auth type change
        if old.auth_type != new.auth_type:
            drifts.append(
                self._make_drift_item(
                    drift_type=DriftType.AUTH,
                    severity=DriftSeverity.CRITICAL,
                    endpoint_id=new.stable_id,
                    path=new.path,
                    method=new.method,
                    title="Auth type changed",
                    description=f"Auth changed from {old.auth_type.value} to {new.auth_type.value}",
                    before={"auth_type": old.auth_type.value},
                    after={"auth_type": new.auth_type.value},
                    recommendation="Update client authentication",
                )
            )

        # Risk tier change
        if old.risk_tier != new.risk_tier:
            # Only report if risk increased
            risk_order = ["safe", "low", "medium", "high", "critical"]
            old_idx = risk_order.index(old.risk_tier) if old.risk_tier in risk_order else 0
            new_idx = risk_order.index(new.risk_tier) if new.risk_tier in risk_order else 0
            if new_idx > old_idx:
                drifts.append(
                    self._make_drift_item(
                        drift_type=DriftType.RISK,
                        severity=DriftSeverity.WARNING,
                        endpoint_id=new.stable_id,
                        path=new.path,
                        method=new.method,
                        title="Risk tier escalated",
                        description=f"Risk changed from {old.risk_tier} to {new.risk_tier}",
                        before={"risk_tier": old.risk_tier},
                        after={"risk_tier": new.risk_tier},
                    )
                )

        # Parameter changes
        old_params = {p.name: p for p in old.parameters}
        new_params = {p.name: p for p in new.parameters}

        for name, param in new_params.items():
            if name not in old_params:
                severity = DriftSeverity.WARNING if param.required else DriftSeverity.INFO
                drifts.append(
                    self._make_drift_item(
                        drift_type=DriftType.PARAMETER,
                        severity=severity,
                        endpoint_id=new.stable_id,
                        path=new.path,
                        method=new.method,
                        title=f"Parameter added: {name}",
                        description=f"New {'required ' if param.required else ''}parameter '{name}' added",
                        before=None,
                        after={"name": name, "required": param.required},
                    )
                )

        for name in old_params:
            if name not in new_params:
                drifts.append(
                    self._make_drift_item(
                        drift_type=DriftType.PARAMETER,
                        severity=DriftSeverity.INFO,
                        endpoint_id=new.stable_id,
                        path=new.path,
                        method=new.method,
                        title=f"Parameter removed: {name}",
                        description=f"Parameter '{name}' was removed",
                        before={"name": name},
                        after=None,
                    )
                )

        # Response schema changes
        if old.response_body_schema and new.response_body_schema:
            schema_drifts = self._detect_schema_drift(
                old.response_body_schema,
                new.response_body_schema,
                new,
                is_response=True,
            )
            drifts.extend(schema_drifts)

        # Request schema changes
        if old.request_body_schema and new.request_body_schema:
            schema_drifts = self._detect_schema_drift(
                old.request_body_schema,
                new.request_body_schema,
                new,
                is_response=False,
            )
            drifts.extend(schema_drifts)

        return drifts

    def _detect_modifications_from_snapshot(
        self, snap: dict[str, Any], endpoint: Endpoint
    ) -> list[DriftItem]:
        """Detect modifications between snapshot and endpoint."""
        drifts = []

        # Auth type change
        snap_auth = snap.get("auth_type", "none")
        if snap_auth != endpoint.auth_type.value:
            drifts.append(
                self._make_drift_item(
                    drift_type=DriftType.AUTH,
                    severity=DriftSeverity.CRITICAL,
                    endpoint_id=endpoint.stable_id,
                    path=endpoint.path,
                    method=endpoint.method,
                    title="Auth type changed",
                    description=f"Auth changed from {snap_auth} to {endpoint.auth_type.value}",
                    before={"auth_type": snap_auth},
                    after={"auth_type": endpoint.auth_type.value},
                    recommendation="Update client authentication",
                )
            )

        # Risk tier change
        snap_risk = snap.get("risk_tier", "low")
        if snap_risk != endpoint.risk_tier:
            risk_order = ["safe", "low", "medium", "high", "critical"]
            old_idx = risk_order.index(snap_risk) if snap_risk in risk_order else 0
            new_idx = risk_order.index(endpoint.risk_tier) if endpoint.risk_tier in risk_order else 0
            if new_idx > old_idx:
                drifts.append(
                    self._make_drift_item(
                        drift_type=DriftType.RISK,
                        severity=DriftSeverity.WARNING,
                        endpoint_id=endpoint.stable_id,
                        path=endpoint.path,
                        method=endpoint.method,
                        title="Risk tier escalated",
                        description=f"Risk changed from {snap_risk} to {endpoint.risk_tier}",
                        before={"risk_tier": snap_risk},
                        after={"risk_tier": endpoint.risk_tier},
                    )
                )

        # Parameter changes
        snap_params = {p["name"]: p for p in snap.get("parameters", [])}
        new_params = {p.name: p for p in endpoint.parameters}

        for name, param in new_params.items():
            if name not in snap_params:
                severity = DriftSeverity.WARNING if param.required else DriftSeverity.INFO
                drifts.append(
                    self._make_drift_item(
                        drift_type=DriftType.PARAMETER,
                        severity=severity,
                        endpoint_id=endpoint.stable_id,
                        path=endpoint.path,
                        method=endpoint.method,
                        title=f"Parameter added: {name}",
                        description=f"New {'required ' if param.required else ''}parameter '{name}' added",
                        before=None,
                        after={"name": name, "required": param.required},
                    )
                )

        for name in snap_params:
            if name not in new_params:
                drifts.append(
                    self._make_drift_item(
                        drift_type=DriftType.PARAMETER,
                        severity=DriftSeverity.INFO,
                        endpoint_id=endpoint.stable_id,
                        path=endpoint.path,
                        method=endpoint.method,
                        title=f"Parameter removed: {name}",
                        description=f"Parameter '{name}' was removed",
                        before={"name": name},
                        after=None,
                    )
                )

        # Schema changes
        if snap.get("response_schema") and endpoint.response_body_schema:
            schema_drifts = self._detect_schema_drift(
                snap["response_schema"],
                endpoint.response_body_schema,
                endpoint,
                is_response=True,
            )
            drifts.extend(schema_drifts)

        return drifts

    def _detect_schema_drift(
        self,
        old_schema: dict[str, Any],
        new_schema: dict[str, Any],
        endpoint: Endpoint,
        is_response: bool = True,
    ) -> list[DriftItem]:
        """Detect schema drift between old and new schemas."""
        drifts = []

        # Simple property comparison for object schemas
        if (
            old_schema.get("type") == "object"
            and new_schema.get("type") == "object"
        ):
            old_props = set(old_schema.get("properties", {}).keys())
            new_props = set(new_schema.get("properties", {}).keys())

            # Removed properties
            removed = old_props - new_props
            if removed and is_response:
                # Removing response fields is breaking
                for prop in removed:
                    drifts.append(
                        self._make_drift_item(
                            drift_type=DriftType.BREAKING,
                            severity=DriftSeverity.ERROR,
                            endpoint_id=endpoint.stable_id,
                            path=endpoint.path,
                            method=endpoint.method,
                            title=f"Response field removed: {prop}",
                            description=f"Field '{prop}' removed from response",
                            before={"field": prop},
                            after=None,
                            recommendation="Update consumers to handle missing field",
                        )
                    )
            elif removed and not is_response:
                # Removing request fields is non-breaking (maybe)
                for prop in removed:
                    drifts.append(
                        self._make_drift_item(
                            drift_type=DriftType.SCHEMA,
                            severity=DriftSeverity.INFO,
                            endpoint_id=endpoint.stable_id,
                            path=endpoint.path,
                            method=endpoint.method,
                            title=f"Request field removed: {prop}",
                            description=f"Field '{prop}' removed from request",
                            before={"field": prop},
                            after=None,
                        )
                    )

            # Added properties
            added = new_props - old_props
            if added and not is_response:
                # Adding required request fields is potentially breaking
                new_required = set(new_schema.get("required", []))
                for prop in added:
                    if prop in new_required:
                        drifts.append(
                            self._make_drift_item(
                                drift_type=DriftType.BREAKING,
                                severity=DriftSeverity.WARNING,
                                endpoint_id=endpoint.stable_id,
                                path=endpoint.path,
                                method=endpoint.method,
                                title=f"Required request field added: {prop}",
                                description=f"New required field '{prop}' added to request",
                                before=None,
                                after={"field": prop, "required": True},
                                recommendation="Update callers to provide this field",
                            )
                        )
                    else:
                        drifts.append(
                            self._make_drift_item(
                                drift_type=DriftType.SCHEMA,
                                severity=DriftSeverity.INFO,
                                endpoint_id=endpoint.stable_id,
                                path=endpoint.path,
                                method=endpoint.method,
                                title=f"Optional request field added: {prop}",
                                description=f"New optional field '{prop}' added to request",
                                before=None,
                                after={"field": prop, "required": False},
                            )
                        )
            elif added and is_response:
                # Adding response fields is non-breaking
                for prop in added:
                    drifts.append(
                        self._make_drift_item(
                            drift_type=DriftType.SCHEMA,
                            severity=DriftSeverity.INFO,
                            endpoint_id=endpoint.stable_id,
                            path=endpoint.path,
                            method=endpoint.method,
                            title=f"Response field added: {prop}",
                            description=f"New field '{prop}' added to response",
                            before=None,
                            after={"field": prop},
                        )
                    )

        return drifts

    def _detect_flow_drift(
        self,
        from_endpoints: list[Endpoint],
        to_endpoints: list[Endpoint],
        flow_graph: FlowGraph,
    ) -> list[DriftItem]:
        """Detect broken flows when endpoints in a flow are removed/changed."""
        drifts: list[DriftItem] = []

        from_sigs = {ep.signature_id for ep in from_endpoints if ep.signature_id}
        to_sigs = {ep.signature_id for ep in to_endpoints if ep.signature_id}
        removed_sigs = from_sigs - to_sigs

        if not removed_sigs:
            return drifts

        # For each removed endpoint, check if it participates in any flow
        for removed_sig in removed_sigs:
            # Check as source (other endpoints depend on its output)
            downstream = flow_graph.edges_from(removed_sig)
            for edge in downstream:
                if edge.target_id in to_sigs:
                    # Target still exists but its dependency was removed
                    drifts.append(
                        self._make_drift_item(
                            drift_type=DriftType.BREAKING,
                            severity=DriftSeverity.WARNING,
                            endpoint_id=edge.target_id,
                            path=None,
                            method=None,
                            title="Flow broken: dependency removed",
                            description=(
                                f"Endpoint {removed_sig} was removed, "
                                f"breaking a flow to {edge.target_id} "
                                f"(linked by '{edge.linking_field}')"
                            ),
                            before={"flow_source": removed_sig},
                            after=None,
                            recommendation="Restore the removed endpoint or update the dependent endpoint",
                        )
                    )

            # Check as target (other endpoints enable it)
            upstream = flow_graph.edges_to(removed_sig)
            for edge in upstream:
                if edge.source_id in to_sigs:
                    # Source still exists but its downstream was removed
                    drifts.append(
                        self._make_drift_item(
                            drift_type=DriftType.BREAKING,
                            severity=DriftSeverity.WARNING,
                            endpoint_id=edge.source_id,
                            path=None,
                            method=None,
                            title="Flow broken: downstream removed",
                            description=(
                                f"Endpoint {removed_sig} was removed, "
                                f"breaking a flow from {edge.source_id} "
                                f"(linked by '{edge.linking_field}')"
                            ),
                            before={"flow_target": removed_sig},
                            after=None,
                            recommendation="Review whether the flow is still needed",
                        )
                    )

        return drifts

    def _create_report(
        self,
        drifts: list[DriftItem],
        from_capture_id: str | None = None,
        to_capture_id: str | None = None,
        from_baseline_id: str | None = None,
    ) -> DriftReport:
        """Create a drift report from detected drifts."""
        ordered_drifts = sorted(
            drifts,
            key=lambda d: (
                d.type.value,
                d.severity.value,
                d.method or "",
                d.path or "",
                d.title,
                d.description,
            ),
        )

        # Count by type
        breaking = sum(1 for d in ordered_drifts if d.type == DriftType.BREAKING)
        auth = sum(1 for d in ordered_drifts if d.type == DriftType.AUTH)
        risk = sum(1 for d in ordered_drifts if d.type == DriftType.RISK)
        additive = sum(1 for d in ordered_drifts if d.type == DriftType.ADDITIVE)
        schema = sum(1 for d in ordered_drifts if d.type == DriftType.SCHEMA)
        parameter = sum(1 for d in ordered_drifts if d.type == DriftType.PARAMETER)
        unknown = sum(1 for d in ordered_drifts if d.type == DriftType.UNKNOWN)

        # Determine flags and exit code
        has_breaking = breaking > 0 or auth > 0
        requires_review = has_breaking or risk > 0

        if has_breaking:
            exit_code = 2
        elif risk > 0:
            exit_code = 1
        else:
            exit_code = 0

        report_generated_at = resolve_generated_at(deterministic=self._deterministic)
        return DriftReport(
            id=self._report_id(
                drifts=ordered_drifts,
                from_capture_id=from_capture_id,
                to_capture_id=to_capture_id,
                from_baseline_id=from_baseline_id,
            ),
            schema_version=CURRENT_SCHEMA_VERSION,
            generated_at=report_generated_at,
            from_capture_id=from_capture_id,
            to_capture_id=to_capture_id,
            from_baseline_id=from_baseline_id,
            total_drifts=len(ordered_drifts),
            breaking_count=breaking,
            auth_count=auth,
            risk_count=risk,
            additive_count=additive,
            schema_count=schema,
            parameter_count=parameter,
            unknown_count=unknown,
            drifts=ordered_drifts,
            has_breaking_changes=has_breaking,
            requires_review=requires_review,
            exit_code=exit_code,
        )

    def to_json(self, report: DriftReport) -> str:
        """Serialize drift report to JSON.

        Args:
            report: DriftReport to serialize

        Returns:
            JSON string
        """
        return report.model_dump_json(indent=2)

    def to_markdown(self, report: DriftReport) -> str:
        """Generate a Markdown report.

        Args:
            report: DriftReport to render

        Returns:
            Markdown string
        """
        lines = [
            "# Drift Report",
            "",
            f"**ID:** {report.id}",
            f"**Generated:** {report.generated_at.isoformat()}",
            "",
        ]

        if report.from_capture_id:
            lines.append(f"**From Capture:** {report.from_capture_id}")
        if report.to_capture_id:
            lines.append(f"**To Capture:** {report.to_capture_id}")
        if report.from_baseline_id:
            lines.append(f"**Baseline:** {report.from_baseline_id}")

        lines.extend([
            "",
            "## Summary",
            "",
            f"- **Total Drifts:** {report.total_drifts}",
            f"- **Breaking Changes:** {report.breaking_count}",
            f"- **Auth Changes:** {report.auth_count}",
            f"- **Risk Changes:** {report.risk_count}",
            f"- **Additive:** {report.additive_count}",
            f"- **Schema Changes:** {report.schema_count}",
            f"- **Parameter Changes:** {report.parameter_count}",
            "",
            f"**Has Breaking Changes:** {'Yes' if report.has_breaking_changes else 'No'}",
            f"**Requires Review:** {'Yes' if report.requires_review else 'No'}",
            f"**Exit Code:** {report.exit_code}",
            "",
        ])

        if report.drifts:
            lines.extend([
                "## Drifts",
                "",
            ])

            # Group by type
            by_type: dict[DriftType, list[DriftItem]] = {}
            for drift in report.drifts:
                by_type.setdefault(drift.type, []).append(drift)

            for drift_type, items in by_type.items():
                lines.extend([
                    f"### {drift_type.value.upper()} ({len(items)})",
                    "",
                ])

                for item in items:
                    lines.extend([
                        f"#### {item.title}",
                        "",
                        f"- **Severity:** {item.severity.value}",
                        f"- **Endpoint:** `{item.method} {item.path}`",
                        f"- **Description:** {item.description}",
                    ])
                    if item.recommendation:
                        lines.append(f"- **Recommendation:** {item.recommendation}")
                    lines.append("")

        return "\n".join(lines)
