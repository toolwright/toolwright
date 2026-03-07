"""Tests for control plane action handlers."""

import asyncio
import json
import time

import pytest

from toolwright.mcp.event_store import EventStore
from toolwright.models.work_item import (
    WorkItem,
    WorkItemAction,
    WorkItemKind,
    WorkItemStatus,
)


# ---------------------------------------------------------------------------
# Helpers / Mocks
# ---------------------------------------------------------------------------


def _make_store(tmp_path):
    return EventStore(state_dir=tmp_path)


class MockLockfileManager:
    def __init__(self):
        self.approved = []
        self.rejected = []
        self.saved = 0

    def approve(self, tool_id, approved_by=None):
        self.approved.append(tool_id)
        return True

    def reject(self, tool_id, reason=None):
        self.rejected.append(tool_id)
        return True

    def save(self):
        self.saved += 1


class MockConfirmationStore:
    def __init__(self):
        self.granted = []
        self.denied = []

    def grant(self, token_id):
        self.granted.append(token_id)
        return True

    def deny(self, token_id, reason=None):
        self.denied.append(token_id)
        return True


class MockCircuitBreaker:
    def __init__(self):
        self.killed = []
        self.enabled = []

    def kill_tool(self, tool_id, reason=""):
        self.killed.append(tool_id)

    def enable_tool(self, tool_id):
        self.enabled.append(tool_id)


class MockRequest:
    """Minimal Starlette Request mock."""

    def __init__(self, body=None, path_params=None, query_params=None):
        self._body = json.dumps(body or {}).encode()
        self.path_params = path_params or {}
        self.query_params = query_params or {}

    async def json(self):
        return json.loads(self._body)


def _setup_ctx(tmp_path, **kwargs):
    from toolwright.mcp.action_handlers import ActionContext, set_context

    store = _make_store(tmp_path)
    ctx = ActionContext(
        event_store=store,
        lockfile_manager=kwargs.get("lockfile_manager", MockLockfileManager()),
        confirmation_store=kwargs.get("confirmation_store", MockConfirmationStore()),
        circuit_breaker=kwargs.get("circuit_breaker", MockCircuitBreaker()),
    )
    set_context(ctx)
    return ctx


def _make_approval_item(tool_id="get_users"):
    return WorkItem(
        id=f"wi_approval_{tool_id}",
        kind=WorkItemKind.TOOL_APPROVAL,
        subject_id=tool_id,
        subject_label=tool_id,
        evidence={"method": "GET", "path": f"/api/{tool_id}"},
        actions=[
            WorkItemAction("approve", "Approve", style="primary"),
            WorkItemAction("block", "Block", style="danger"),
        ],
    )


def _make_confirmation_item(token_id="token_1"):
    return WorkItem(
        id=f"wi_confirm_{token_id}",
        kind=WorkItemKind.CONFIRMATION,
        subject_id=token_id,
        subject_label="delete_repo",
        is_blocking=True,
        evidence={"tool_id": "delete_repo"},
        actions=[
            WorkItemAction("confirm", "Confirm", style="primary"),
            WorkItemAction("deny", "Deny", style="danger"),
        ],
    )


def _make_breaker_item(tool_id="flaky_api"):
    return WorkItem(
        id=f"wi_breaker_{tool_id}",
        kind=WorkItemKind.CIRCUIT_BREAKER,
        subject_id=tool_id,
        subject_label=tool_id,
        evidence={"failure_count": 5, "last_error": "timeout"},
        actions=[
            WorkItemAction("enable", "Re-enable", style="primary"),
            WorkItemAction("kill", "Kill", style="danger"),
        ],
    )


# ---------------------------------------------------------------------------
# Gate Allow
# ---------------------------------------------------------------------------


class TestGateAllow:
    def test_approve_single_tool(self, tmp_path):
        from toolwright.mcp.action_handlers import handle_gate_allow

        ctx = _setup_ctx(tmp_path)
        ctx.event_store.publish_work_item(_make_approval_item("get_users"))

        req = MockRequest(body={"tool_ids": ["get_users"]})
        loop = asyncio.new_event_loop()
        resp = loop.run_until_complete(handle_gate_allow(req))
        loop.close()

        data = json.loads(resp.body)
        assert data["ok"] is True
        assert data["results"][0]["ok"] is True
        assert data["results"][0]["work_item"]["status"] == "approved"
        assert "get_users" in ctx.lockfile_manager.approved
        ctx.event_store.close()

    def test_approve_bulk(self, tmp_path):
        from toolwright.mcp.action_handlers import handle_gate_allow

        ctx = _setup_ctx(tmp_path)
        ctx.event_store.publish_work_item(_make_approval_item("a"))
        ctx.event_store.publish_work_item(_make_approval_item("b"))

        req = MockRequest(body={"tool_ids": ["a", "b"]})
        loop = asyncio.new_event_loop()
        resp = loop.run_until_complete(handle_gate_allow(req))
        loop.close()

        data = json.loads(resp.body)
        assert data["ok"] is True
        assert len(data["results"]) == 2
        assert all(r["ok"] for r in data["results"])
        ctx.event_store.close()

    def test_approve_not_found(self, tmp_path):
        from toolwright.mcp.action_handlers import handle_gate_allow

        ctx = _setup_ctx(tmp_path)
        req = MockRequest(body={"tool_ids": ["nonexistent"]})
        loop = asyncio.new_event_loop()
        resp = loop.run_until_complete(handle_gate_allow(req))
        loop.close()

        data = json.loads(resp.body)
        assert data["ok"] is False
        assert data["results"][0]["error"] == "not_found"
        ctx.event_store.close()

    def test_approve_idempotent(self, tmp_path):
        from toolwright.mcp.action_handlers import handle_gate_allow

        ctx = _setup_ctx(tmp_path)
        ctx.event_store.publish_work_item(_make_approval_item("x"))

        req = MockRequest(body={"tool_ids": ["x"]})
        loop = asyncio.new_event_loop()
        loop.run_until_complete(handle_gate_allow(req))
        resp = loop.run_until_complete(handle_gate_allow(req))
        loop.close()

        data = json.loads(resp.body)
        assert data["ok"] is True
        ctx.event_store.close()


# ---------------------------------------------------------------------------
# Gate Block
# ---------------------------------------------------------------------------


class TestGateBlock:
    def test_block_tool(self, tmp_path):
        from toolwright.mcp.action_handlers import handle_gate_block

        ctx = _setup_ctx(tmp_path)
        ctx.event_store.publish_work_item(_make_approval_item("danger_tool"))

        req = MockRequest(body={"tool_id": "danger_tool"})
        loop = asyncio.new_event_loop()
        resp = loop.run_until_complete(handle_gate_block(req))
        loop.close()

        data = json.loads(resp.body)
        assert data["ok"] is True
        assert data["work_item"]["status"] == "denied"
        assert "danger_tool" in ctx.lockfile_manager.rejected
        ctx.event_store.close()


# ---------------------------------------------------------------------------
# Confirm Grant / Deny
# ---------------------------------------------------------------------------


class TestConfirmation:
    def test_grant_confirmation(self, tmp_path):
        from toolwright.mcp.action_handlers import handle_confirm_grant

        ctx = _setup_ctx(tmp_path)
        ctx.event_store.publish_work_item(_make_confirmation_item("t1"))

        req = MockRequest(body={"work_item_id": "wi_confirm_t1"})
        loop = asyncio.new_event_loop()
        resp = loop.run_until_complete(handle_confirm_grant(req))
        loop.close()

        data = json.loads(resp.body)
        assert data["ok"] is True
        assert data["work_item"]["status"] == "approved"
        assert "t1" in ctx.confirmation_store.granted
        ctx.event_store.close()

    def test_deny_confirmation(self, tmp_path):
        from toolwright.mcp.action_handlers import handle_confirm_deny

        ctx = _setup_ctx(tmp_path)
        ctx.event_store.publish_work_item(_make_confirmation_item("t2"))

        req = MockRequest(body={"work_item_id": "wi_confirm_t2"})
        loop = asyncio.new_event_loop()
        resp = loop.run_until_complete(handle_confirm_deny(req))
        loop.close()

        data = json.loads(resp.body)
        assert data["ok"] is True
        assert data["work_item"]["status"] == "denied"
        assert "t2" in ctx.confirmation_store.denied
        ctx.event_store.close()


# ---------------------------------------------------------------------------
# Kill / Enable
# ---------------------------------------------------------------------------


class TestCircuitBreakerActions:
    def test_kill_tool(self, tmp_path):
        from toolwright.mcp.action_handlers import handle_kill_tool

        ctx = _setup_ctx(tmp_path)
        ctx.event_store.publish_work_item(_make_breaker_item("flaky"))

        req = MockRequest(body={"work_item_id": "wi_breaker_flaky"})
        loop = asyncio.new_event_loop()
        resp = loop.run_until_complete(handle_kill_tool(req))
        loop.close()

        data = json.loads(resp.body)
        assert data["ok"] is True
        assert data["work_item"]["status"] == "dismissed"
        assert "flaky" in ctx.circuit_breaker.killed
        ctx.event_store.close()

    def test_enable_tool(self, tmp_path):
        from toolwright.mcp.action_handlers import handle_enable_tool

        ctx = _setup_ctx(tmp_path)
        ctx.event_store.publish_work_item(_make_breaker_item("flaky"))

        req = MockRequest(body={"work_item_id": "wi_breaker_flaky"})
        loop = asyncio.new_event_loop()
        resp = loop.run_until_complete(handle_enable_tool(req))
        loop.close()

        data = json.loads(resp.body)
        assert data["ok"] is True
        assert data["work_item"]["status"] == "approved"
        assert "flaky" in ctx.circuit_breaker.enabled
        ctx.event_store.close()


# ---------------------------------------------------------------------------
# Work Items GET endpoints
# ---------------------------------------------------------------------------


class TestWorkItemEndpoints:
    def test_list_work_items(self, tmp_path):
        from toolwright.mcp.action_handlers import handle_list_work_items

        ctx = _setup_ctx(tmp_path)
        ctx.event_store.publish_work_item(_make_approval_item("a"))
        ctx.event_store.publish_work_item(_make_approval_item("b"))

        req = MockRequest(query_params={})
        loop = asyncio.new_event_loop()
        resp = loop.run_until_complete(handle_list_work_items(req))
        loop.close()

        data = json.loads(resp.body)
        assert len(data["items"]) == 2
        ctx.event_store.close()

    def test_get_work_item(self, tmp_path):
        from toolwright.mcp.action_handlers import handle_get_work_item

        ctx = _setup_ctx(tmp_path)
        ctx.event_store.publish_work_item(_make_approval_item("x"))

        req = MockRequest(path_params={"item_id": "wi_approval_x"})
        loop = asyncio.new_event_loop()
        resp = loop.run_until_complete(handle_get_work_item(req))
        loop.close()

        data = json.loads(resp.body)
        assert data["work_item"]["id"] == "wi_approval_x"
        ctx.event_store.close()

    def test_get_work_item_not_found(self, tmp_path):
        from toolwright.mcp.action_handlers import handle_get_work_item

        ctx = _setup_ctx(tmp_path)
        req = MockRequest(path_params={"item_id": "nonexistent"})
        loop = asyncio.new_event_loop()
        resp = loop.run_until_complete(handle_get_work_item(req))
        loop.close()

        assert resp.status_code == 404
        ctx.event_store.close()

    def test_status_counts(self, tmp_path):
        from toolwright.mcp.action_handlers import handle_status_counts

        ctx = _setup_ctx(tmp_path)
        ctx.event_store.publish_work_item(_make_approval_item("a"))
        ctx.event_store.publish_work_item(_make_confirmation_item("t1"))

        req = MockRequest()
        loop = asyncio.new_event_loop()
        resp = loop.run_until_complete(handle_status_counts(req))
        loop.close()

        data = json.loads(resp.body)
        assert data["open"] == 2
        assert data["blocking"] == 1
        ctx.event_store.close()
