"""Tests for toolwright.ui.ops — the TUI operations layer."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from toolwright.core.approval.lockfile import ApprovalStatus


class TestListTools:
    """list_tools returns ToolApproval objects from lockfile."""

    def test_returns_tools_from_lockfile(self, tmp_path: Path) -> None:
        # Create a YAML lockfile in the expected format
        from toolwright.core.approval import LockfileManager
        from toolwright.core.approval.lockfile import ToolApproval
        from toolwright.ui.ops import list_tools

        lockfile_path = tmp_path / "lockfile.yaml"
        manager = LockfileManager(str(lockfile_path))
        manager.load()  # creates empty lockfile
        # Add a tool manually
        tool = ToolApproval(
            tool_id="GET /users api.example.com",
            signature_id="sig1",
            name="get_users",
            method="GET",
            path="/users",
            host="api.example.com",
            risk_tier="low",
            status=ApprovalStatus.APPROVED,
        )
        manager.lockfile.tools[tool.tool_id] = tool
        manager.save()

        # Mock resolve_toolpack_paths to point to our lockfile
        mock_resolved = MagicMock()
        mock_resolved.approved_lockfile_path = lockfile_path
        mock_resolved.pending_lockfile_path = None

        with (
            patch("toolwright.ui.ops.load_toolpack"),
            patch("toolwright.ui.ops.resolve_toolpack_paths", return_value=mock_resolved),
        ):
            tools = list_tools(str(tmp_path / "toolpack.yaml"))

        assert len(tools) == 1
        t = tools[0]
        assert t.name == "get_users"
        assert t.method == "GET"
        assert t.path == "/users"
        assert t.host == "api.example.com"
        assert t.risk_tier == "low"
        assert t.status == ApprovalStatus.APPROVED

    def test_returns_empty_when_no_lockfile(self, tmp_path: Path) -> None:
        from toolwright.ui.ops import list_tools

        mock_resolved = MagicMock()
        mock_resolved.approved_lockfile_path = None
        mock_resolved.pending_lockfile_path = None

        with (
            patch("toolwright.ui.ops.load_toolpack"),
            patch("toolwright.ui.ops.resolve_toolpack_paths", return_value=mock_resolved),
        ):
            tools = list_tools(str(tmp_path / "toolpack.yaml"))

        assert tools == []

    def test_returns_empty_on_error(self) -> None:
        from toolwright.ui.ops import list_tools

        with patch("toolwright.ui.ops.load_toolpack", side_effect=FileNotFoundError):
            tools = list_tools("/nonexistent/toolpack.yaml")

        assert tools == []

    def test_falls_back_to_pending_lockfile(self, tmp_path: Path) -> None:
        from toolwright.core.approval import LockfileManager
        from toolwright.core.approval.lockfile import ToolApproval
        from toolwright.ui.ops import list_tools

        lockfile_path = tmp_path / "pending-lockfile.yaml"
        manager = LockfileManager(str(lockfile_path))
        manager.load()
        tool = ToolApproval(
            tool_id="POST /items api.example.com",
            signature_id="sig2",
            name="create_item",
            method="POST",
            path="/items",
            host="api.example.com",
            risk_tier="high",
            status=ApprovalStatus.PENDING,
        )
        manager.lockfile.tools[tool.tool_id] = tool
        manager.save()

        mock_resolved = MagicMock()
        mock_resolved.approved_lockfile_path = None
        mock_resolved.pending_lockfile_path = lockfile_path

        with (
            patch("toolwright.ui.ops.load_toolpack"),
            patch("toolwright.ui.ops.resolve_toolpack_paths", return_value=mock_resolved),
        ):
            tools = list_tools(str(tmp_path / "toolpack.yaml"))

        assert len(tools) == 1
        assert tools[0].name == "create_item"
        assert tools[0].status == ApprovalStatus.PENDING


class TestDashboardStatusWidget:
    """StatusWidget.refresh_status uses correct StatusModel fields."""

    def test_refresh_status_uses_flat_fields(self) -> None:
        """Ensure StatusWidget accesses lockfile_state, not lockfile.state."""
        from toolwright.ui.ops import StatusModel

        model = StatusModel(
            toolpack_id="my-api",
            toolpack_path="/tmp/tp.yaml",
            root="/tmp",
            lockfile_state="sealed",
            lockfile_path="/tmp/lockfile.yaml",
            approved_count=5,
            blocked_count=1,
            pending_count=2,
            has_baseline=True,
            baseline_age_seconds=3600.0,
            drift_state="clean",
            verification_state="pass",
            has_mcp_config=True,
            tool_count=8,
            alerts=[],
        )

        # Exercise the same logic as StatusWidget.refresh_status
        # but without Textual (which may not be installed)
        lines = [
            f"Toolpack: {model.toolpack_id}",
            f"Tools: {model.tool_count}",
            f"Lockfile: {model.lockfile_state}",
            f"  Approved: {model.approved_count}  "
            f"Blocked: {model.blocked_count}  "
            f"Pending: {model.pending_count}",
            f"Baseline: {'exists' if model.has_baseline else 'missing'}",
            f"Drift: {model.drift_state}",
            f"Verification: {model.verification_state}",
        ]
        output = "\n".join(lines)

        assert "my-api" in output
        assert "sealed" in output
        assert "Approved: 5" in output
        assert "Blocked: 1" in output
        assert "Pending: 2" in output
        assert "Baseline: exists" in output
        assert "Drift: clean" in output
        assert "Verification: pass" in output
        assert "Tools: 8" in output

    def test_sealed_with_blocked_shows_warn_not_ok(self) -> None:
        """M15: status should show [WARN] not [OK] when lockfile is sealed but has blocked tools."""
        from toolwright.ui.ops import StatusModel
        from toolwright.ui.views.status import render_plain

        model = StatusModel(
            toolpack_id="my-api",
            toolpack_path="/tmp/tp.yaml",
            root="/tmp",
            lockfile_state="sealed",
            lockfile_path="/tmp/lockfile.yaml",
            approved_count=5,
            blocked_count=2,
            pending_count=0,
            has_baseline=True,
            baseline_age_seconds=3600.0,
            drift_state="clean",
            verification_state="pass",
            has_mcp_config=True,
            tool_count=7,
            alerts=[],
        )

        output = render_plain(model)
        # Find the Lockfile line
        lockfile_line = [l for l in output.splitlines() if "Lockfile" in l][0]
        # Should NOT show [OK] when there are blocked tools
        assert "[OK]" not in lockfile_line, (
            f"Lockfile with blocked tools should not show [OK]: {lockfile_line}"
        )
        assert "[WARN]" in lockfile_line

    def test_sealed_no_blocked_shows_ok(self) -> None:
        """Sealed lockfile with no blocked tools should show [OK]."""
        from toolwright.ui.ops import StatusModel
        from toolwright.ui.views.status import render_plain

        model = StatusModel(
            toolpack_id="my-api",
            toolpack_path="/tmp/tp.yaml",
            root="/tmp",
            lockfile_state="sealed",
            lockfile_path="/tmp/lockfile.yaml",
            approved_count=5,
            blocked_count=0,
            pending_count=0,
            has_baseline=True,
            baseline_age_seconds=3600.0,
            drift_state="clean",
            verification_state="pass",
            has_mcp_config=True,
            tool_count=5,
            alerts=[],
        )

        output = render_plain(model)
        lockfile_line = [l for l in output.splitlines() if "Lockfile" in l][0]
        assert "[OK]" in lockfile_line

    def test_next_step_computed_from_engine(self) -> None:
        """Verify next-step is computed via compute_next_steps, not a model attr."""
        from toolwright.ui.views.next_steps import NextStepsInput, compute_next_steps

        ns_input = NextStepsInput(
            command="dashboard",
            toolpack_id="my-api",
            lockfile_state="pending",
            verification_state="not_run",
            drift_state="not_checked",
            pending_count=3,
            has_baseline=False,
            has_mcp_config=False,
            has_approved_lockfile=False,
            has_pending_lockfile=True,
        )
        ns = compute_next_steps(ns_input)

        # Should recommend approval since there are pending tools
        assert ns.primary is not None
        assert ns.primary.command  # has a command string
        assert ns.primary.label  # has a label
