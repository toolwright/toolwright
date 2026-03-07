"""Tests for WorkItem model and factory functions."""

import time

import pytest

from toolwright.core.work_items import (
    create_capability_request_item,
    create_circuit_breaker_item,
    create_confirmation_item,
    create_repair_patch_item,
    create_rule_draft_item,
    create_tool_approval_item,
)
from toolwright.models.work_item import (
    WorkItem,
    WorkItemAction,
    WorkItemKind,
    WorkItemStatus,
)


# ---------------------------------------------------------------------------
# Model basics
# ---------------------------------------------------------------------------


class TestWorkItemModel:
    def test_default_status_is_open(self):
        item = WorkItem(id="test_1", kind=WorkItemKind.TOOL_APPROVAL)
        assert item.status == WorkItemStatus.OPEN

    def test_is_terminal_for_open(self):
        item = WorkItem(id="test_1")
        assert not item.is_terminal()

    @pytest.mark.parametrize(
        "status",
        [
            WorkItemStatus.APPROVED,
            WorkItemStatus.DENIED,
            WorkItemStatus.APPLIED,
            WorkItemStatus.DISMISSED,
            WorkItemStatus.EXPIRED,
        ],
    )
    def test_is_terminal_for_terminal_states(self, status):
        item = WorkItem(id="test_1", status=status)
        assert item.is_terminal()

    def test_to_dict_roundtrip(self):
        item = WorkItem(
            id="wi_test_1",
            kind=WorkItemKind.CONFIRMATION,
            status=WorkItemStatus.OPEN,
            subject_id="token_abc",
            subject_label="get_users",
            subject_detail="Agent requesting: get_users",
            risk_tier="high",
            is_blocking=True,
            blocking_session_id="sess_123",
            evidence={"tool_id": "get_users", "arguments": {"page": 1}},
            actions=[
                WorkItemAction("confirm", "Confirm", style="primary"),
                WorkItemAction(
                    "deny", "Deny", style="danger", confirm_text="Really deny?"
                ),
            ],
            created_at=1000.0,
            expires_at=1300.0,
        )

        d = item.to_dict()
        restored = WorkItem.from_dict(d)

        assert restored.id == item.id
        assert restored.kind == item.kind
        assert restored.status == item.status
        assert restored.subject_id == item.subject_id
        assert restored.subject_label == item.subject_label
        assert restored.is_blocking is True
        assert restored.blocking_session_id == "sess_123"
        assert restored.evidence == item.evidence
        assert len(restored.actions) == 2
        assert restored.actions[0].action_id == "confirm"
        assert restored.actions[1].confirm_text == "Really deny?"
        assert restored.created_at == 1000.0
        assert restored.expires_at == 1300.0

    def test_from_dict_defaults(self):
        minimal = {"id": "wi_x", "kind": "tool_approval", "status": "open"}
        item = WorkItem.from_dict(minimal)
        assert item.subject_id == ""
        assert item.risk_tier == "medium"
        assert item.is_blocking is False
        assert item.evidence == {}
        assert item.actions == []

    def test_resolved_fields(self):
        item = WorkItem(id="test_1")
        item.status = WorkItemStatus.APPROVED
        item.resolved_at = time.time()
        item.resolved_by = "console"
        item.resolution_reason = "Approved by operator"

        d = item.to_dict()
        assert d["resolved_by"] == "console"
        assert d["resolution_reason"] == "Approved by operator"


# ---------------------------------------------------------------------------
# Factory functions
# ---------------------------------------------------------------------------


class TestFactories:
    def test_tool_approval_deterministic_id(self):
        item = create_tool_approval_item(
            "get_users", "GET", "/users", "low", "List users"
        )
        assert item.id == "wi_approval_get_users"
        assert item.kind == WorkItemKind.TOOL_APPROVAL
        assert item.status == WorkItemStatus.OPEN
        assert item.risk_tier == "low"
        assert item.subject_detail == "GET /users"
        assert len(item.actions) == 2
        assert item.actions[0].action_id == "approve"
        assert item.actions[1].action_id == "block"

    def test_confirmation_blocking_with_expiry(self):
        before = time.time()
        item = create_confirmation_item(
            token_id="cfrmv1_abc",
            tool_id="delete_repo",
            arguments={"repo": "test"},
            risk_tier="critical",
            session_id="sess_1",
            session_context="Agent wants to delete repo",
        )
        assert item.id == "wi_confirm_cfrmv1_abc"
        assert item.kind == WorkItemKind.CONFIRMATION
        assert item.is_blocking is True
        assert item.blocking_session_id == "sess_1"
        assert item.expires_at is not None
        assert item.expires_at >= before + 299  # ~300s TTL

    def test_circuit_breaker_high_risk(self):
        item = create_circuit_breaker_item(
            "flaky_api", 5, "Connection timeout", "open"
        )
        assert item.id == "wi_breaker_flaky_api"
        assert item.kind == WorkItemKind.CIRCUIT_BREAKER
        assert item.risk_tier == "high"
        assert item.evidence["failure_count"] == 5
        assert "Re-enable" in [a.label for a in item.actions]
        assert "Kill Permanently" in [a.label for a in item.actions]

    def test_repair_patch_manual_severity(self):
        item = create_repair_patch_item(
            "patch_1", "get_users", "schema_changed", "response_body",
            "New field added", "MANUAL"
        )
        assert item.id == "wi_patch_patch_1"
        assert item.risk_tier == "high"

    def test_repair_patch_approval_severity(self):
        item = create_repair_patch_item(
            "patch_2", "get_users", "schema_changed", "response_body",
            "Field type changed", "APPROVAL_REQUIRED"
        )
        assert item.risk_tier == "medium"

    def test_rule_draft(self):
        item = create_rule_draft_item(
            "rule_1", "prerequisite", "Must call auth before delete",
            ["delete_user"], {"required": ["auth_login"]}, "agent"
        )
        assert item.id == "wi_rule_rule_1"
        assert item.kind == WorkItemKind.RULE_DRAFT
        assert "prerequisite" in item.subject_label
        assert item.evidence["created_by"] == "agent"

    def test_rule_draft_no_targets(self):
        item = create_rule_draft_item(
            "rule_2", "rate", "Max 10/min", None, {"max": 10}, "agent"
        )
        assert "all" in item.subject_detail

    def test_capability_request(self):
        item = create_capability_request_item(
            "prop_1", "api.stripe.com", 42
        )
        assert item.id == "wi_cap_prop_1"
        assert item.kind == WorkItemKind.CAPABILITY_REQUEST
        assert "stripe" in item.subject_label
        assert "42 endpoints" in item.subject_detail


# ---------------------------------------------------------------------------
# Idempotency: same factory inputs produce same ID
# ---------------------------------------------------------------------------


class TestDeterministicIds:
    def test_same_tool_approval_same_id(self):
        a = create_tool_approval_item("x", "GET", "/x", "low", "desc")
        b = create_tool_approval_item("x", "GET", "/x", "low", "desc")
        assert a.id == b.id

    def test_different_tool_approval_different_id(self):
        a = create_tool_approval_item("x", "GET", "/x", "low", "desc")
        b = create_tool_approval_item("y", "GET", "/y", "low", "desc")
        assert a.id != b.id
