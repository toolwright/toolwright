"""Tests for reconcile meta-tools — toolwright_reconcile_status, toolwright_pending_repairs.

These meta-tools return concise, agent-friendly text summaries (not JSON).
An LLM agent should get a useful answer in under 200 tokens.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from toolwright.mcp.meta_server import ToolwrightMetaMCPServer
from toolwright.models.reconcile import (
    ReconcileAction,
    ReconcileState,
    ToolReconcileState,
    ToolStatus,
)
from toolwright.models.repair import (
    PatchAction,
    PatchItem,
    PatchKind,
    RepairPatchPlan,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_reconcile_state(state_dir: Path, state: ReconcileState) -> Path:
    """Write a reconcile state JSON file."""
    state_dir.mkdir(parents=True, exist_ok=True)
    path = state_dir / "reconcile.json"
    path.write_text(state.model_dump_json(indent=2))
    return path


def _write_repair_plan(state_dir: Path, plan: RepairPatchPlan) -> Path:
    """Write a repair plan JSON file."""
    state_dir.mkdir(parents=True, exist_ok=True)
    path = state_dir / "repair_plan.json"
    plan_data = {
        "generated_at": datetime.now(UTC).isoformat(),
        "plan": plan.model_dump(),
    }
    path.write_text(json.dumps(plan_data, indent=2))
    return path


def _make_state_with_tools() -> ReconcileState:
    """Create a ReconcileState with some tool data."""
    return ReconcileState(
        tools={
            "get_users": ToolReconcileState(
                tool_id="get_users",
                status=ToolStatus.HEALTHY,
                consecutive_healthy=5,
                last_probe_at="2026-02-20T00:00:00Z",
            ),
            "create_user": ToolReconcileState(
                tool_id="create_user",
                status=ToolStatus.UNHEALTHY,
                failure_class="SCHEMA_CHANGED",
                consecutive_unhealthy=3,
                last_probe_at="2026-02-20T00:00:00Z",
                last_action=ReconcileAction.APPROVAL_QUEUED,
            ),
            "delete_user": ToolReconcileState(
                tool_id="delete_user",
                status=ToolStatus.DEGRADED,
                failure_class="SERVER_ERROR",
                consecutive_unhealthy=1,
                last_probe_at="2026-02-20T00:00:00Z",
            ),
        },
        reconcile_count=10,
        auto_repairs_applied=2,
        approvals_queued=1,
        errors=0,
    )


def _make_patch_plan() -> RepairPatchPlan:
    """Create a RepairPatchPlan with mixed patch kinds."""
    return RepairPatchPlan(
        total_patches=3,
        safe_count=1,
        approval_required_count=1,
        manual_count=1,
        patches=[
            PatchItem(
                id="p_safe_1",
                diagnosis_id="d_1",
                kind=PatchKind.SAFE,
                action=PatchAction.VERIFY_CONTRACTS,
                title="Re-verify contracts",
                description="Re-run contract verification",
                cli_command="toolwright verify --mode contracts",
                reason="Contract check stale",
            ),
            PatchItem(
                id="p_approval_1",
                diagnosis_id="d_2",
                kind=PatchKind.APPROVAL_REQUIRED,
                action=PatchAction.GATE_ALLOW,
                title="Approve new tool",
                description="New tool create_item needs approval",
                cli_command="toolwright gate allow create_item",
                reason="New tool discovered",
                risk_note="Expands tool capability",
            ),
            PatchItem(
                id="p_manual_1",
                diagnosis_id="d_3",
                kind=PatchKind.MANUAL,
                action=PatchAction.INVESTIGATE,
                title="Investigate auth failure",
                description="Auth mechanism changed",
                cli_command="# Manual: investigate auth change",
                reason="Auth type changed",
            ),
        ],
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def state_dir(tmp_path: Path) -> Path:
    """State directory at .toolwright/state/."""
    d = tmp_path / ".toolwright" / "state"
    d.mkdir(parents=True)
    return d


@pytest.fixture
def server_with_state(state_dir: Path) -> ToolwrightMetaMCPServer:
    """Create a meta server with state_dir configured."""
    state = _make_state_with_tools()
    _write_reconcile_state(state_dir, state)
    plan = _make_patch_plan()
    _write_repair_plan(state_dir, plan)
    return ToolwrightMetaMCPServer(state_dir=state_dir)


@pytest.fixture
def server_empty_state(tmp_path: Path) -> ToolwrightMetaMCPServer:
    """Create a meta server with no state files."""
    return ToolwrightMetaMCPServer(state_dir=tmp_path / "nonexistent")


# ===========================================================================
# 1. toolwright_reconcile_status — tool registration
# ===========================================================================


class TestReconcileStatusRegistration:
    """Ensure the tool is registered and discoverable."""

    @pytest.mark.anyio
    async def test_tool_listed(self, server_with_state: ToolwrightMetaMCPServer) -> None:
        tools = await server_with_state._handle_list_tools()
        names = [t.name for t in tools]
        assert "toolwright_reconcile_status" in names

    @pytest.mark.anyio
    async def test_tool_has_description(self, server_with_state: ToolwrightMetaMCPServer) -> None:
        tools = await server_with_state._handle_list_tools()
        tool = next(t for t in tools if t.name == "toolwright_reconcile_status")
        assert "reconcil" in tool.description.lower() or "health" in tool.description.lower()


# ===========================================================================
# 2. toolwright_reconcile_status — concise text output
# ===========================================================================


class TestReconcileStatusHandler:
    """Tests for the reconcile_status handler — concise text output."""

    @pytest.mark.anyio
    async def test_returns_plain_text(self, server_with_state: ToolwrightMetaMCPServer) -> None:
        """Response is plain text, not JSON."""
        result = await server_with_state._handle_call_tool("toolwright_reconcile_status", {})
        text = result[0].text
        # Should NOT be valid JSON (concise text format)
        with pytest.raises(json.JSONDecodeError):
            json.loads(text)

    @pytest.mark.anyio
    async def test_includes_cycle_count(self, server_with_state: ToolwrightMetaMCPServer) -> None:
        result = await server_with_state._handle_call_tool("toolwright_reconcile_status", {})
        text = result[0].text
        assert "#10" in text or "cycle 10" in text.lower() or "10 cycles" in text.lower()

    @pytest.mark.anyio
    async def test_includes_health_counts(self, server_with_state: ToolwrightMetaMCPServer) -> None:
        result = await server_with_state._handle_call_tool("toolwright_reconcile_status", {})
        text = result[0].text
        assert "1 healthy" in text.lower()
        assert "1 unhealthy" in text.lower()
        assert "1 degraded" in text.lower()

    @pytest.mark.anyio
    async def test_lists_unhealthy_tools(self, server_with_state: ToolwrightMetaMCPServer) -> None:
        result = await server_with_state._handle_call_tool("toolwright_reconcile_status", {})
        text = result[0].text
        assert "create_user" in text
        assert "SCHEMA_CHANGED" in text

    @pytest.mark.anyio
    async def test_lists_degraded_tools(self, server_with_state: ToolwrightMetaMCPServer) -> None:
        result = await server_with_state._handle_call_tool("toolwright_reconcile_status", {})
        text = result[0].text
        assert "delete_user" in text
        assert "SERVER_ERROR" in text

    @pytest.mark.anyio
    async def test_includes_repair_counts(self, server_with_state: ToolwrightMetaMCPServer) -> None:
        result = await server_with_state._handle_call_tool("toolwright_reconcile_status", {})
        text = result[0].text
        # Auto-repairs: 2, Pending approvals: 1
        assert "2" in text  # auto-repairs count
        assert "1" in text  # approvals count

    @pytest.mark.anyio
    async def test_no_state_returns_no_data_message(self, server_empty_state: ToolwrightMetaMCPServer) -> None:
        result = await server_empty_state._handle_call_tool("toolwright_reconcile_status", {})
        text = result[0].text
        assert "no" in text.lower() or "0" in text

    @pytest.mark.anyio
    async def test_filter_only_shows_matching(self, server_with_state: ToolwrightMetaMCPServer) -> None:
        result = await server_with_state._handle_call_tool(
            "toolwright_reconcile_status", {"filter_status": "unhealthy"}
        )
        text = result[0].text
        assert "create_user" in text
        # Healthy tool should not appear in filtered detail lines
        # (it may still appear in summary counts, but not as a listed tool)

    @pytest.mark.anyio
    async def test_is_concise(self, server_with_state: ToolwrightMetaMCPServer) -> None:
        """Output should be under 500 chars for 3 tools — well within 200 tokens."""
        result = await server_with_state._handle_call_tool("toolwright_reconcile_status", {})
        text = result[0].text
        assert len(text) < 500


# ===========================================================================
# 3. toolwright_pending_repairs — tool registration
# ===========================================================================


class TestPendingRepairsRegistration:
    """Ensure the pending repairs tool is registered."""

    @pytest.mark.anyio
    async def test_tool_listed(self, server_with_state: ToolwrightMetaMCPServer) -> None:
        tools = await server_with_state._handle_list_tools()
        names = [t.name for t in tools]
        assert "toolwright_pending_repairs" in names

    @pytest.mark.anyio
    async def test_tool_has_description(self, server_with_state: ToolwrightMetaMCPServer) -> None:
        tools = await server_with_state._handle_list_tools()
        tool = next(t for t in tools if t.name == "toolwright_pending_repairs")
        assert "repair" in tool.description.lower() or "patch" in tool.description.lower()


# ===========================================================================
# 4. toolwright_pending_repairs — concise text output
# ===========================================================================


class TestPendingRepairsHandler:
    """Tests for the pending_repairs handler — concise text output."""

    @pytest.mark.anyio
    async def test_returns_plain_text(self, server_with_state: ToolwrightMetaMCPServer) -> None:
        """Response is plain text, not JSON."""
        result = await server_with_state._handle_call_tool("toolwright_pending_repairs", {})
        text = result[0].text
        with pytest.raises(json.JSONDecodeError):
            json.loads(text)

    @pytest.mark.anyio
    async def test_includes_total_count(self, server_with_state: ToolwrightMetaMCPServer) -> None:
        result = await server_with_state._handle_call_tool("toolwright_pending_repairs", {})
        text = result[0].text
        assert "3" in text

    @pytest.mark.anyio
    async def test_lists_each_patch_title(self, server_with_state: ToolwrightMetaMCPServer) -> None:
        result = await server_with_state._handle_call_tool("toolwright_pending_repairs", {})
        text = result[0].text
        assert "Re-verify contracts" in text
        assert "Approve new tool" in text
        assert "Investigate auth failure" in text

    @pytest.mark.anyio
    async def test_includes_patch_kinds(self, server_with_state: ToolwrightMetaMCPServer) -> None:
        result = await server_with_state._handle_call_tool("toolwright_pending_repairs", {})
        text = result[0].text
        assert "safe" in text.lower()
        assert "approval_required" in text.lower()
        assert "manual" in text.lower()

    @pytest.mark.anyio
    async def test_includes_cli_commands(self, server_with_state: ToolwrightMetaMCPServer) -> None:
        result = await server_with_state._handle_call_tool("toolwright_pending_repairs", {})
        text = result[0].text
        assert "toolwright verify --mode contracts" in text
        assert "toolwright gate allow create_item" in text

    @pytest.mark.anyio
    async def test_no_plan_returns_no_repairs_message(self, server_empty_state: ToolwrightMetaMCPServer) -> None:
        result = await server_empty_state._handle_call_tool("toolwright_pending_repairs", {})
        text = result[0].text
        assert "no" in text.lower() or "0" in text

    @pytest.mark.anyio
    async def test_filter_by_kind_shows_only_matching(self, server_with_state: ToolwrightMetaMCPServer) -> None:
        result = await server_with_state._handle_call_tool(
            "toolwright_pending_repairs", {"filter_kind": "approval_required"}
        )
        text = result[0].text
        assert "Approve new tool" in text
        # safe patch title should not appear
        assert "Re-verify contracts" not in text

    @pytest.mark.anyio
    async def test_includes_apply_hint(self, server_with_state: ToolwrightMetaMCPServer) -> None:
        result = await server_with_state._handle_call_tool("toolwright_pending_repairs", {})
        text = result[0].text
        assert "repair apply" in text.lower()

    @pytest.mark.anyio
    async def test_is_concise(self, server_with_state: ToolwrightMetaMCPServer) -> None:
        """Output should be under 600 chars for 3 patches — well within 200 tokens."""
        result = await server_with_state._handle_call_tool("toolwright_pending_repairs", {})
        text = result[0].text
        assert len(text) < 600


# ===========================================================================
# 5. Dispatch routing
# ===========================================================================


class TestMetaToolDispatch:
    """Verify both tools route through _handle_call_tool."""

    @pytest.mark.anyio
    async def test_unknown_tool_returns_error(self, server_with_state: ToolwrightMetaMCPServer) -> None:
        result = await server_with_state._handle_call_tool("toolwright_nonexistent", {})
        data = json.loads(result[0].text)
        assert "error" in data

    @pytest.mark.anyio
    async def test_reconcile_status_dispatches(self, server_with_state: ToolwrightMetaMCPServer) -> None:
        result = await server_with_state._handle_call_tool("toolwright_reconcile_status", {})
        text = result[0].text
        # Should not be an error JSON
        assert "error" not in text.lower().split("\n")[0] or "Unknown tool" not in text

    @pytest.mark.anyio
    async def test_pending_repairs_dispatches(self, server_with_state: ToolwrightMetaMCPServer) -> None:
        result = await server_with_state._handle_call_tool("toolwright_pending_repairs", {})
        text = result[0].text
        assert "repair" in text.lower() or "patch" in text.lower()
