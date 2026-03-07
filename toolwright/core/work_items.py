"""WorkItem factory functions with deterministic IDs.

All factories produce deterministic IDs so that reconnects, restarts,
and repeated signals do not create duplicates.
"""

from __future__ import annotations

import time

from toolwright.models.work_item import (
    WorkItem,
    WorkItemAction,
    WorkItemKind,
)


def create_tool_approval_item(
    tool_id: str,
    method: str,
    path: str,
    risk_tier: str,
    description: str,
) -> WorkItem:
    return WorkItem(
        id=f"wi_approval_{tool_id}",
        kind=WorkItemKind.TOOL_APPROVAL,
        subject_id=tool_id,
        subject_label=tool_id,
        subject_detail=f"{method} {path}",
        risk_tier=risk_tier,
        evidence={
            "method": method,
            "path": path,
            "description": description,
            "risk_tier": risk_tier,
        },
        actions=[
            WorkItemAction("approve", "Approve", style="primary"),
            WorkItemAction(
                "block",
                "Block",
                style="danger",
                confirm_text=f"Block {tool_id}?",
            ),
        ],
    )


def create_confirmation_item(
    token_id: str,
    tool_id: str,
    arguments: dict,
    risk_tier: str,
    session_id: str | None = None,
    session_context: str | None = None,
) -> WorkItem:
    return WorkItem(
        id=f"wi_confirm_{token_id}",
        kind=WorkItemKind.CONFIRMATION,
        subject_id=token_id,
        subject_label=tool_id,
        subject_detail=f"Agent requesting: {tool_id}",
        risk_tier=risk_tier,
        is_blocking=True,
        blocking_session_id=session_id,
        evidence={
            "tool_id": tool_id,
            "arguments": arguments,
            "session_context": session_context,
        },
        actions=[
            WorkItemAction("confirm", "Confirm", style="primary"),
            WorkItemAction("deny", "Deny", style="danger"),
        ],
        expires_at=time.time() + 300,
    )


def create_circuit_breaker_item(
    tool_id: str,
    failure_count: int,
    last_error: str,
    state: str,
) -> WorkItem:
    return WorkItem(
        id=f"wi_breaker_{tool_id}",
        kind=WorkItemKind.CIRCUIT_BREAKER,
        subject_id=tool_id,
        subject_label=tool_id,
        subject_detail=f"Circuit breaker OPEN after {failure_count} failures",
        risk_tier="high",
        evidence={
            "failure_count": failure_count,
            "last_error": last_error,
            "state": state,
        },
        actions=[
            WorkItemAction("enable", "Re-enable", style="primary"),
            WorkItemAction(
                "kill",
                "Kill Permanently",
                style="danger",
                confirm_text=f"Permanently kill {tool_id}?",
            ),
        ],
    )


def create_repair_patch_item(
    patch_id: str,
    tool_id: str,
    change_type: str,
    field_name: str,
    detail: str,
    severity: str,
) -> WorkItem:
    return WorkItem(
        id=f"wi_patch_{patch_id}",
        kind=WorkItemKind.REPAIR_PATCH,
        subject_id=patch_id,
        subject_label=f"{tool_id}: {field_name}",
        subject_detail=detail,
        risk_tier="high" if severity == "MANUAL" else "medium",
        evidence={
            "tool_id": tool_id,
            "change_type": change_type,
            "field": field_name,
            "severity": severity,
            "detail": detail,
        },
        actions=[
            WorkItemAction("apply", "Apply Patch", style="primary"),
            WorkItemAction("dismiss", "Dismiss", style="default"),
        ],
    )


def create_rule_draft_item(
    rule_id: str,
    kind: str,
    description: str,
    target_tool_ids: list[str] | None,
    config: dict,
    created_by: str,
) -> WorkItem:
    targets = target_tool_ids or []
    return WorkItem(
        id=f"wi_rule_{rule_id}",
        kind=WorkItemKind.RULE_DRAFT,
        subject_id=rule_id,
        subject_label=f"{kind}: {description[:60]}",
        subject_detail=f"Targets: {', '.join(targets) if targets else 'all'}",
        evidence={
            "rule_kind": kind,
            "description": description,
            "target_tool_ids": targets,
            "config": config,
            "created_by": created_by,
        },
        actions=[
            WorkItemAction("activate", "Activate Rule", style="primary"),
            WorkItemAction("dismiss", "Reject", style="danger"),
        ],
    )


def create_capability_request_item(
    proposal_id: str,
    host: str,
    endpoint_count: int,
) -> WorkItem:
    return WorkItem(
        id=f"wi_cap_{proposal_id}",
        kind=WorkItemKind.CAPABILITY_REQUEST,
        subject_id=proposal_id,
        subject_label=f"New API: {host}",
        subject_detail=f"{endpoint_count} endpoints discovered",
        evidence={
            "host": host,
            "endpoint_count": endpoint_count,
            "proposal_id": proposal_id,
        },
        actions=[
            WorkItemAction("approve", "Approve & Mint", style="primary"),
            WorkItemAction("dismiss", "Reject", style="danger"),
        ],
    )
