"""WorkItem model for the Toolwright Control Plane.

A WorkItem is a first-class object representing something that requires
human input. It has a lifecycle (status transitions) and is the unit
of interaction in the console.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class WorkItemKind(str, Enum):
    TOOL_APPROVAL = "tool_approval"
    CONFIRMATION = "confirmation"
    REPAIR_PATCH = "repair_patch"
    CIRCUIT_BREAKER = "circuit_breaker"
    RULE_DRAFT = "rule_draft"
    CAPABILITY_REQUEST = "capability_request"


class WorkItemStatus(str, Enum):
    OPEN = "open"
    APPROVED = "approved"
    DENIED = "denied"
    APPLIED = "applied"
    DISMISSED = "dismissed"
    EXPIRED = "expired"


@dataclass
class WorkItemAction:
    action_id: str
    label: str
    style: str = "default"  # "primary", "danger", "default"
    confirm_text: Optional[str] = None


@dataclass
class WorkItem:
    """A work item requiring human input.

    IDs are NOT auto-generated. Factories produce deterministic IDs
    so reconnects, restarts, and repeated signals do not create duplicates.
    """

    id: str = ""
    kind: WorkItemKind = WorkItemKind.TOOL_APPROVAL
    status: WorkItemStatus = WorkItemStatus.OPEN

    # What this is about
    subject_id: str = ""
    subject_label: str = ""
    subject_detail: str = ""

    # Risk and urgency
    risk_tier: str = "medium"
    is_blocking: bool = False
    blocking_session_id: Optional[str] = None

    # Evidence: minimum context needed to decide
    evidence: dict[str, Any] = field(default_factory=dict)

    # Available actions
    actions: list[WorkItemAction] = field(default_factory=list)

    # Timestamps
    created_at: float = field(default_factory=time.time)
    resolved_at: Optional[float] = None
    expires_at: Optional[float] = None

    # Audit
    resolved_by: Optional[str] = None
    resolution_reason: Optional[str] = None

    def is_terminal(self) -> bool:
        return self.status in (
            WorkItemStatus.APPROVED,
            WorkItemStatus.DENIED,
            WorkItemStatus.APPLIED,
            WorkItemStatus.DISMISSED,
            WorkItemStatus.EXPIRED,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind.value,
            "status": self.status.value,
            "subject_id": self.subject_id,
            "subject_label": self.subject_label,
            "subject_detail": self.subject_detail,
            "risk_tier": self.risk_tier,
            "is_blocking": self.is_blocking,
            "blocking_session_id": self.blocking_session_id,
            "evidence": self.evidence,
            "actions": [
                {
                    "action_id": a.action_id,
                    "label": a.label,
                    "style": a.style,
                    "confirm_text": a.confirm_text,
                }
                for a in self.actions
            ],
            "created_at": self.created_at,
            "resolved_at": self.resolved_at,
            "expires_at": self.expires_at,
            "resolved_by": self.resolved_by,
            "resolution_reason": self.resolution_reason,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorkItem:
        return cls(
            id=data["id"],
            kind=WorkItemKind(data["kind"]),
            status=WorkItemStatus(data["status"]),
            subject_id=data.get("subject_id", ""),
            subject_label=data.get("subject_label", ""),
            subject_detail=data.get("subject_detail", ""),
            risk_tier=data.get("risk_tier", "medium"),
            is_blocking=data.get("is_blocking", False),
            blocking_session_id=data.get("blocking_session_id"),
            evidence=data.get("evidence", {}),
            actions=[WorkItemAction(**a) for a in data.get("actions", [])],
            created_at=data.get("created_at", 0),
            resolved_at=data.get("resolved_at"),
            expires_at=data.get("expires_at"),
            resolved_by=data.get("resolved_by"),
            resolution_reason=data.get("resolution_reason"),
        )
