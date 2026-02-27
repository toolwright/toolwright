"""Plan report generation."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from toolwright.core.approval import LockfileManager, compute_artifacts_digest_from_paths
from toolwright.core.approval.snapshot import load_snapshot_digest
from toolwright.core.toolpack import load_toolpack, resolve_toolpack_paths
from toolwright.models.plan import (
    PlanArtifactInfo,
    PlanBaselineInfo,
    PlanChanges,
    PlanEvidence,
    PlanPolicyChange,
    PlanReport,
    PlanSchemaChange,
    PlanSummary,
    PlanToolChange,
    PlanToolpackInfo,
    PlanToolsetChange,
)
from toolwright.utils.canonical import canonical_json
from toolwright.utils.digests import canonical_json_bytes, load_artifact_payload


@dataclass(frozen=True)
class ArtifactBundle:
    tools: Path
    toolsets: Path
    policy: Path
    baseline: Path


def build_plan(
    *,
    toolpack_path: Path,
    baseline_path: Path | None = None,
) -> PlanReport:
    toolpack = load_toolpack(toolpack_path)
    resolved = resolve_toolpack_paths(toolpack=toolpack, toolpack_path=toolpack_path)
    toolpack_root = toolpack_path.resolve().parent

    lockfile_path = resolved.approved_lockfile_path or resolved.pending_lockfile_path
    if lockfile_path is None or not lockfile_path.exists():
        raise ValueError("lockfile missing; run toolwright gate sync")

    manager = LockfileManager(lockfile_path)
    lockfile = manager.load()

    baseline_bundle, snapshot_dir, snapshot_digest = _resolve_baseline(
        toolpack_root=toolpack_root,
        lockfile_snapshot_dir=lockfile.baseline_snapshot_dir,
        lockfile_snapshot_digest=lockfile.baseline_snapshot_digest,
        baseline_path=baseline_path,
    )

    current_bundle = ArtifactBundle(
        tools=resolved.tools_path,
        toolsets=resolved.toolsets_path,
        policy=resolved.policy_path,
        baseline=resolved.baseline_path,
    )

    current_digest = compute_artifacts_digest_from_paths(
        tools_path=current_bundle.tools,
        toolsets_path=current_bundle.toolsets,
        policy_path=current_bundle.policy,
    )
    baseline_digest = compute_artifacts_digest_from_paths(
        tools_path=baseline_bundle.tools,
        toolsets_path=baseline_bundle.toolsets,
        policy_path=baseline_bundle.policy,
    )

    tool_changes, schema_changes = _diff_tools(
        baseline_bundle.tools, current_bundle.tools
    )
    policy_changes = _diff_policy(
        baseline_bundle.policy, current_bundle.policy
    )
    toolset_changes = _diff_toolsets(
        baseline_bundle.toolsets, current_bundle.toolsets
    )

    evidence = _build_evidence(
        lockfile.evidence_summary_sha256,
        resolved.evidence_summary_sha256_path,
    )

    summary = PlanSummary(
        tools_added=len([c for c in tool_changes if c.change_type == "added"]),
        tools_removed=len([c for c in tool_changes if c.change_type == "removed"]),
        tools_modified=len([c for c in tool_changes if c.change_type == "modified"]),
        schemas_changed=len(schema_changes),
        policy_changed=len(policy_changes),
        toolsets_changed=len(toolset_changes),
        evidence_changed=evidence.changed,
        has_changes=bool(
            tool_changes or schema_changes or policy_changes or toolset_changes or evidence.changed
        ),
    )

    return PlanReport(
        toolpack=PlanToolpackInfo(
            id=toolpack.toolpack_id,
            schema_version=toolpack.schema_version,
            runtime_mode=toolpack.runtime.mode if toolpack.runtime else "local",
        ),
        baseline=PlanBaselineInfo(
            resolved=True,
            snapshot_dir=str(snapshot_dir),
            snapshot_digest=snapshot_digest,
        ),
        artifacts=PlanArtifactInfo(
            current_digest=current_digest,
            baseline_digest=baseline_digest,
        ),
        summary=summary,
        changes=PlanChanges(
            tools=sorted(tool_changes, key=lambda c: c.tool_id),
            schemas=sorted(schema_changes, key=lambda c: c.tool_id),
            policy=sorted(policy_changes, key=lambda c: c.rule_id),
            toolsets=sorted(toolset_changes, key=lambda c: c.toolset),
        ),
        evidence=evidence,
        warnings=[],
    )


def render_plan_json(plan: PlanReport) -> str:
    payload = plan.model_dump(mode="json")
    return canonical_json(payload)


def render_plan_md(plan: PlanReport) -> str:
    summary = plan.summary
    lines = [
        "# Toolwright Plan",
        "",
        f"Toolpack: {plan.toolpack.id}",
        f"Runtime: {plan.toolpack.runtime_mode}",
        f"Baseline snapshot: {plan.baseline.snapshot_dir}",
        "",
        "## Summary",
        f"- Tools added: {summary.tools_added}",
        f"- Tools removed: {summary.tools_removed}",
        f"- Tools modified: {summary.tools_modified}",
        f"- Schemas changed: {summary.schemas_changed}",
        f"- Policy changed: {summary.policy_changed}",
        f"- Toolsets changed: {summary.toolsets_changed}",
        f"- Evidence changed: {str(summary.evidence_changed).lower()}",
        "",
        "## Changes",
        "### Tools",
    ]

    if plan.changes.tools:
        for tool_change in plan.changes.tools:
            lines.append(
                f"- [{tool_change.change_type}] {tool_change.tool_id} ({tool_change.name})"
            )
    else:
        lines.append("- none")

    lines.append("")
    lines.append("### Schemas")
    if plan.changes.schemas:
        for schema_change in plan.changes.schemas:
            lines.append(f"- [{schema_change.change_type}] {schema_change.tool_id}")
    else:
        lines.append("- none")

    lines.append("")
    lines.append("### Policy")
    if plan.changes.policy:
        for policy_change in plan.changes.policy:
            lines.append(f"- [{policy_change.change_type}] {policy_change.rule_id}")
    else:
        lines.append("- none")

    lines.append("")
    lines.append("### Toolsets")
    if plan.changes.toolsets:
        for toolset_change in plan.changes.toolsets:
            added = (
                ", ".join(toolset_change.added_actions)
                if toolset_change.added_actions
                else "none"
            )
            removed = (
                ", ".join(toolset_change.removed_actions)
                if toolset_change.removed_actions
                else "none"
            )
            lines.append(f"- {toolset_change.toolset}: +[{added}] -[{removed}]")
    else:
        lines.append("- none")

    lines.append("")
    lines.append("### Evidence")
    lines.append(f"- expected: {plan.evidence.expected_hash or 'none'}")
    lines.append(f"- actual: {plan.evidence.actual_hash or 'none'}")
    lines.append(f"- changed: {str(plan.evidence.changed).lower()}")

    return "\n".join(lines) + "\n"


def render_plan_github_md(plan: PlanReport) -> str:
    """Render a GitHub-friendly markdown summary for PR comments."""
    summary = plan.summary
    status = "✅ No gated changes detected" if not summary.has_changes else "⚠️ Changes detected"
    evidence_status = "changed" if summary.evidence_changed else "unchanged"

    lines = [
        "# Toolwright Diff (GitHub)",
        "",
        f"**Toolpack:** `{plan.toolpack.id}`",
        f"**Runtime:** `{plan.toolpack.runtime_mode}`",
        f"**Baseline:** `{plan.baseline.snapshot_dir}`",
        f"**Status:** {status}",
        "",
        "## Summary",
        "",
        "| Signal | Count |",
        "| --- | ---: |",
        f"| Tools added | {summary.tools_added} |",
        f"| Tools removed | {summary.tools_removed} |",
        f"| Tools modified | {summary.tools_modified} |",
        f"| Schemas changed | {summary.schemas_changed} |",
        f"| Policy rules changed | {summary.policy_changed} |",
        f"| Toolsets changed | {summary.toolsets_changed} |",
        f"| Evidence | {evidence_status} |",
        "",
        "## Tool Changes",
    ]

    if plan.changes.tools:
        lines.extend(
            [
                "",
                "| Change | Tool ID | Name |",
                "| --- | --- | --- |",
            ]
        )
        for tool_change in plan.changes.tools:
            lines.append(
                f"| `{tool_change.change_type}` | `{tool_change.tool_id}` | `{tool_change.name}` |"
            )
    else:
        lines.extend(["", "- none"])

    lines.append("")
    lines.append("## Schema Changes")
    if plan.changes.schemas:
        lines.extend(
            [
                "",
                "| Change | Tool ID |",
                "| --- | --- |",
            ]
        )
        for schema_change in plan.changes.schemas:
            lines.append(f"| `{schema_change.change_type}` | `{schema_change.tool_id}` |")
    else:
        lines.extend(["", "- none"])

    lines.append("")
    lines.append("## Policy Changes")
    if plan.changes.policy:
        lines.extend(
            [
                "",
                "| Change | Rule ID |",
                "| --- | --- |",
            ]
        )
        for policy_change in plan.changes.policy:
            lines.append(f"| `{policy_change.change_type}` | `{policy_change.rule_id}` |")
    else:
        lines.extend(["", "- none"])

    lines.append("")
    lines.append("## Toolset Changes")
    if plan.changes.toolsets:
        lines.extend(
            [
                "",
                "| Toolset | Added | Removed |",
                "| --- | --- | --- |",
            ]
        )
        for toolset_change in plan.changes.toolsets:
            added = ", ".join(toolset_change.added_actions) if toolset_change.added_actions else "none"
            removed = ", ".join(toolset_change.removed_actions) if toolset_change.removed_actions else "none"
            lines.append(f"| `{toolset_change.toolset}` | `{added}` | `{removed}` |")
    else:
        lines.extend(["", "- none"])

    lines.append("")
    lines.append("## Evidence")
    lines.append("")
    lines.append(f"- expected: `{plan.evidence.expected_hash or 'none'}`")
    lines.append(f"- actual: `{plan.evidence.actual_hash or 'none'}`")
    lines.append(f"- changed: `{str(plan.evidence.changed).lower()}`")

    return "\n".join(lines) + "\n"


def _resolve_baseline(
    *,
    toolpack_root: Path,
    lockfile_snapshot_dir: str | None,
    lockfile_snapshot_digest: str | None,
    baseline_path: Path | None,
) -> tuple[ArtifactBundle, str, str]:
    if baseline_path:
        bundle, snapshot_dir_str, snapshot_digest = _resolve_baseline_from_path(
            toolpack_root, baseline_path
        )
        return bundle, snapshot_dir_str, snapshot_digest

    if not lockfile_snapshot_dir or not lockfile_snapshot_digest:
        raise ValueError(
            "No baseline found. Run 'toolwright gate snapshot' first, "
            "or pass '--baseline <snapshot_dir>' to compare against a specific baseline."
        )

    snapshot_dir_path = toolpack_root / lockfile_snapshot_dir
    if not snapshot_dir_path.exists():
        raise ValueError(
            "No baseline found. Run 'toolwright gate snapshot' first, "
            "or pass '--baseline <snapshot_dir>' to compare against a specific baseline."
        )

    digest = load_snapshot_digest(snapshot_dir_path)
    if digest != lockfile_snapshot_digest:
        raise ValueError("baseline snapshot digest mismatch; re-run toolwright gate snapshot")

    bundle = ArtifactBundle(
        tools=snapshot_dir_path / "tools.json",
        toolsets=snapshot_dir_path / "toolsets.yaml",
        policy=snapshot_dir_path / "policy.yaml",
        baseline=snapshot_dir_path / "baseline.json",
    )
    return bundle, lockfile_snapshot_dir, lockfile_snapshot_digest


def _resolve_baseline_from_path(
    toolpack_root: Path, baseline_path: Path
) -> tuple[ArtifactBundle, str, str]:
    def _relative_snapshot_dir(snapshot_dir: Path) -> str:
        try:
            return str(snapshot_dir.relative_to(toolpack_root))
        except ValueError as exc:
            raise ValueError("baseline snapshot must be inside toolpack root") from exc

    if baseline_path.is_file() and baseline_path.name == "toolpack.yaml":
        toolpack = load_toolpack(baseline_path)
        resolved = resolve_toolpack_paths(toolpack=toolpack, toolpack_path=baseline_path)
        lockfile_path = resolved.approved_lockfile_path or resolved.pending_lockfile_path
        if lockfile_path is None or not lockfile_path.exists():
            raise ValueError("baseline lockfile missing")
        manager = LockfileManager(lockfile_path)
        lockfile = manager.load()
        if not lockfile.baseline_snapshot_dir or not lockfile.baseline_snapshot_digest:
            raise ValueError("baseline snapshot missing; run toolwright gate snapshot")
        snapshot_dir = baseline_path.parent / lockfile.baseline_snapshot_dir
        digest = load_snapshot_digest(snapshot_dir)
        if digest != lockfile.baseline_snapshot_digest:
            raise ValueError("baseline snapshot digest mismatch")
        bundle = ArtifactBundle(
            tools=snapshot_dir / "tools.json",
            toolsets=snapshot_dir / "toolsets.yaml",
            policy=snapshot_dir / "policy.yaml",
            baseline=snapshot_dir / "baseline.json",
        )
        return bundle, _relative_snapshot_dir(snapshot_dir), digest

    if baseline_path.is_dir():
        snapshot_dir = baseline_path
        digest = load_snapshot_digest(snapshot_dir)
        bundle = ArtifactBundle(
            tools=snapshot_dir / "tools.json",
            toolsets=snapshot_dir / "toolsets.yaml",
            policy=snapshot_dir / "policy.yaml",
            baseline=snapshot_dir / "baseline.json",
        )
        return bundle, _relative_snapshot_dir(snapshot_dir), digest

    if baseline_path.is_file() and baseline_path.name == "tools.json":
        snapshot_dir = baseline_path.parent
        digest = load_snapshot_digest(snapshot_dir)
        bundle = ArtifactBundle(
            tools=baseline_path,
            toolsets=snapshot_dir / "toolsets.yaml",
            policy=snapshot_dir / "policy.yaml",
            baseline=snapshot_dir / "baseline.json",
        )
        return bundle, _relative_snapshot_dir(snapshot_dir), digest

    raise ValueError("Invalid baseline path")


def _tool_id(action: dict[str, Any]) -> str:
    return (
        str(action.get("tool_id"))
        or str(action.get("signature_id"))
        or str(action.get("id"))
        or str(action.get("name"))
    )


def _endpoint_signature(action: dict[str, Any]) -> str:
    return str(action.get("signature_id") or _tool_id(action))


def _schema_digest(action: dict[str, Any]) -> str:
    payload = {
        "input_schema": action.get("input_schema") or {},
        "output_schema": action.get("output_schema") or {},
    }
    return digest_bytes(payload)


def _tool_digest(action: dict[str, Any]) -> str:
    payload = dict(action)
    payload.pop("input_schema", None)
    payload.pop("output_schema", None)
    return digest_bytes(payload)


def digest_bytes(payload: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def _diff_tools(
    baseline_tools_path: Path, current_tools_path: Path
) -> tuple[list[PlanToolChange], list[PlanSchemaChange]]:
    baseline_payload = load_artifact_payload(baseline_tools_path)
    current_payload = load_artifact_payload(current_tools_path)

    baseline_actions = { _tool_id(a): a for a in baseline_payload.get("actions", []) }
    current_actions = { _tool_id(a): a for a in current_payload.get("actions", []) }

    tool_changes: list[PlanToolChange] = []
    schema_changes: list[PlanSchemaChange] = []

    for tool_id, action in sorted(current_actions.items()):
        if tool_id not in baseline_actions:
            tool_changes.append(
                PlanToolChange(
                    tool_id=tool_id,
                    name=str(action.get("name", tool_id)),
                    change_type="added",
                    endpoint_signature=_endpoint_signature(action),
                    schema_after_digest=_schema_digest(action),
                    tool_after_digest=_tool_digest(action),
                )
            )
            schema_changes.append(
                PlanSchemaChange(
                    tool_id=tool_id,
                    change_type="added",
                    after_digest=_schema_digest(action),
                )
            )
            continue

        baseline_action = baseline_actions[tool_id]
        before_schema = _schema_digest(baseline_action)
        after_schema = _schema_digest(action)
        before_tool = _tool_digest(baseline_action)
        after_tool = _tool_digest(action)

        if before_schema != after_schema or before_tool != after_tool:
            tool_changes.append(
                PlanToolChange(
                    tool_id=tool_id,
                    name=str(action.get("name", tool_id)),
                    change_type="modified",
                    endpoint_signature=_endpoint_signature(action),
                    schema_before_digest=before_schema,
                    schema_after_digest=after_schema,
                    tool_before_digest=before_tool,
                    tool_after_digest=after_tool,
                )
            )
        if before_schema != after_schema:
            schema_changes.append(
                PlanSchemaChange(
                    tool_id=tool_id,
                    change_type="modified",
                    before_digest=before_schema,
                    after_digest=after_schema,
                )
            )

    for tool_id, action in sorted(baseline_actions.items()):
        if tool_id in current_actions:
            continue
        tool_changes.append(
            PlanToolChange(
                tool_id=tool_id,
                name=str(action.get("name", tool_id)),
                change_type="removed",
                endpoint_signature=_endpoint_signature(action),
                schema_before_digest=_schema_digest(action),
                tool_before_digest=_tool_digest(action),
            )
        )
        schema_changes.append(
            PlanSchemaChange(
                tool_id=tool_id,
                change_type="removed",
                before_digest=_schema_digest(action),
            )
        )

    return tool_changes, schema_changes


def _diff_policy(
    baseline_policy_path: Path, current_policy_path: Path
) -> list[PlanPolicyChange]:
    baseline_payload = load_artifact_payload(baseline_policy_path)
    current_payload = load_artifact_payload(current_policy_path)

    baseline_rules = {
        str(rule.get("id")): rule for rule in baseline_payload.get("rules", [])
    }
    current_rules = {
        str(rule.get("id")): rule for rule in current_payload.get("rules", [])
    }

    changes: list[PlanPolicyChange] = []

    for rule_id, rule in sorted(current_rules.items()):
        if rule_id not in baseline_rules:
            changes.append(
                PlanPolicyChange(
                    rule_id=rule_id,
                    change_type="added",
                    after_digest=_digest_rule(rule),
                )
            )
            continue
        before = _digest_rule(baseline_rules[rule_id])
        after = _digest_rule(rule)
        if before != after:
            changes.append(
                PlanPolicyChange(
                    rule_id=rule_id,
                    change_type="modified",
                    before_digest=before,
                    after_digest=after,
                )
            )

    for rule_id, rule in sorted(baseline_rules.items()):
        if rule_id in current_rules:
            continue
        changes.append(
            PlanPolicyChange(
                rule_id=rule_id,
                change_type="removed",
                before_digest=_digest_rule(rule),
            )
        )

    return changes


def _diff_toolsets(
    baseline_toolsets_path: Path, current_toolsets_path: Path
) -> list[PlanToolsetChange]:
    baseline_payload = load_artifact_payload(baseline_toolsets_path)
    current_payload = load_artifact_payload(current_toolsets_path)

    baseline_sets = baseline_payload.get("toolsets", {}) or {}
    current_sets = current_payload.get("toolsets", {}) or {}

    changes: list[PlanToolsetChange] = []
    for name in sorted(set(baseline_sets) | set(current_sets)):
        baseline_actions = set(baseline_sets.get(name, {}).get("actions", []) or [])
        current_actions = set(current_sets.get(name, {}).get("actions", []) or [])
        added = sorted(current_actions - baseline_actions)
        removed = sorted(baseline_actions - current_actions)
        if added or removed:
            changes.append(
                PlanToolsetChange(
                    toolset=name,
                    added_actions=added,
                    removed_actions=removed,
                )
            )
    return changes


def _digest_rule(rule: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(rule).encode("utf-8")).hexdigest()


def _build_evidence(
    expected_hash: str | None, actual_path: Path | None
) -> PlanEvidence:
    actual_hash = None
    if actual_path and actual_path.exists():
        actual_hash = actual_path.read_text().strip()
    missing = {
        "expected_missing": expected_hash is None,
        "actual_missing": actual_hash is None,
    }
    return PlanEvidence(
        expected_hash=expected_hash,
        actual_hash=actual_hash,
        changed=bool(expected_hash and actual_hash and expected_hash != actual_hash),
        missing=missing,
    )
