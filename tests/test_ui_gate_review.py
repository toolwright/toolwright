"""Tests for the interactive gate review flow."""

from __future__ import annotations

from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from rich.console import Console

from toolwright.core.approval.lockfile import ApprovalStatus, ToolApproval


def _make_tool(
    tool_id: str = "get_users",
    name: str = "get_users",
    risk_tier: str = "low",
    status: ApprovalStatus = ApprovalStatus.PENDING,
) -> ToolApproval:
    """Create a mock ToolApproval."""
    return ToolApproval(
        tool_id=tool_id,
        signature_id=f"GET:/api/{name}@api.example.com",
        name=name,
        method="GET",
        path=f"/api/{name}",
        host="api.example.com",
        risk_tier=risk_tier,
        status=status,
        toolsets=["default"],
    )


@pytest.fixture
def mock_console() -> Console:
    from toolwright.ui.console import CASK_THEME

    return Console(file=StringIO(), force_terminal=False, theme=CASK_THEME)


class TestGateReviewNoLockfiles:
    """gate_review_flow shows error when no lockfiles found."""

    def test_no_lockfiles(self, mock_console: Console) -> None:
        from toolwright.ui.flows.gate_review import gate_review_flow

        with patch("toolwright.ui.flows.gate_review.err_console", mock_console):
            gate_review_flow(root_path="/nonexistent")

        output = mock_console.file.getvalue()  # type: ignore[attr-defined]
        assert "No lockfiles found" in output


class TestGateReviewNoPending:
    """When all tools are already reviewed, show success."""

    def test_no_pending_tools(self, mock_console: Console) -> None:
        from toolwright.ui.flows.gate_review import gate_review_flow

        tools = [_make_tool(status=ApprovalStatus.APPROVED)]
        lockfile = MagicMock()
        lockfile.tools = {"get_users": tools[0]}

        with (
            patch("toolwright.ui.flows.gate_review.err_console", mock_console),
            patch(
                "toolwright.ui.flows.gate_review.load_lockfile_tools",
                return_value=(lockfile, tools),
            ),
        ):
            gate_review_flow(lockfile_path="/some/lockfile.yaml")

        output = mock_console.file.getvalue()  # type: ignore[attr-defined]
        assert "No pending tools" in output


class TestGateReviewDirectoryValidation:
    """gate_review_flow rejects directory paths."""

    def test_rejects_directory_path(self, tmp_path: Path, mock_console: Console) -> None:
        from toolwright.ui.flows.gate_review import gate_review_flow

        with patch("toolwright.ui.flows.gate_review.err_console", mock_console):
            gate_review_flow(lockfile_path=str(tmp_path))

        output = mock_console.file.getvalue()  # type: ignore[attr-defined]
        assert "Expected a file, got a directory" in output


class TestGateReviewSkipAll:
    """User can skip all tools to make no changes."""

    def test_skip_all_makes_no_changes(self, mock_console: Console) -> None:
        from toolwright.ui.flows.gate_review import gate_review_flow

        tools = [_make_tool()]
        lockfile = MagicMock()

        # input_stream: "s\n" to skip all low-risk tools
        stream = StringIO("s\n")

        with (
            patch("toolwright.ui.flows.gate_review.err_console", mock_console),
            patch(
                "toolwright.ui.flows.gate_review.load_lockfile_tools",
                return_value=(lockfile, tools),
            ),
            patch("toolwright.ui.flows.gate_review.run_gate_approve") as mock_approve,
        ):
            gate_review_flow(lockfile_path="/some/lockfile.yaml", input_stream=stream)
            mock_approve.assert_not_called()


class TestGateReviewHighRiskRequiresTypedConfirm:
    """High-risk tools require per-tool typed APPROVE confirmation."""

    def test_high_risk_skipped_without_typed_confirm(self, mock_console: Console) -> None:
        from toolwright.ui.flows.gate_review import gate_review_flow

        tools = [_make_tool(risk_tier="high", tool_id="delete_users", name="delete_users")]
        lockfile = MagicMock()

        # input_stream: "a\n" to select approve, then "nope\n" for typed confirm (not "APPROVE")
        stream = StringIO("a\nnope\n")

        with (
            patch("toolwright.ui.flows.gate_review.err_console", mock_console),
            patch(
                "toolwright.ui.flows.gate_review.load_lockfile_tools",
                return_value=(lockfile, tools),
            ),
            patch("toolwright.ui.flows.gate_review.run_gate_approve") as mock_approve,
        ):
            gate_review_flow(lockfile_path="/some/lockfile.yaml", input_stream=stream)
            # Should not have been called — the tool was skipped
            mock_approve.assert_not_called()


class TestGateReviewApproveFlow:
    """Review flow approves low-risk tools in batch."""

    def test_batch_approve_low_risk(self, mock_console: Console) -> None:
        from toolwright.ui.flows.gate_review import gate_review_flow

        tools = [_make_tool(risk_tier="low")]
        lockfile = MagicMock()

        result = MagicMock()
        result.approved_ids = ["get_users"]
        result.promoted = False

        # input_stream: "a\n" to approve all low-risk, "y\n" for proceed confirmation
        stream = StringIO("a\ny\n")

        with (
            patch("toolwright.ui.flows.gate_review.err_console", mock_console),
            patch(
                "toolwright.ui.flows.gate_review.load_lockfile_tools",
                return_value=(lockfile, tools),
            ),
            patch(
                "toolwright.ui.flows.gate_review.run_gate_approve",
                return_value=result,
            ) as mock_approve,
        ):
            gate_review_flow(lockfile_path="/some/lockfile.yaml", input_stream=stream)
            mock_approve.assert_called_once()

        output = mock_console.file.getvalue()  # type: ignore[attr-defined]
        assert "Approved" in output


class TestGateReviewRiskGrouping:
    """Verify tools are grouped by risk tier."""

    def test_high_risk_reviewed_individually(self, mock_console: Console) -> None:
        from toolwright.ui.flows.gate_review import gate_review_flow

        tools = [
            _make_tool(risk_tier="high", tool_id="delete_users", name="delete_users"),
            _make_tool(risk_tier="low", tool_id="get_users", name="get_users"),
        ]
        lockfile = MagicMock()

        result = MagicMock()
        result.approved_ids = ["get_users"]
        result.promoted = False

        # input_stream:
        # "s\n" = skip high-risk tool (individual review)
        # "a\n" = approve all low-risk batch
        # "y\n" = proceed confirmation
        stream = StringIO("s\na\ny\n")

        with (
            patch("toolwright.ui.flows.gate_review.err_console", mock_console),
            patch(
                "toolwright.ui.flows.gate_review.load_lockfile_tools",
                return_value=(lockfile, tools),
            ),
            patch(
                "toolwright.ui.flows.gate_review.run_gate_approve",
                return_value=result,
            ) as mock_approve,
        ):
            gate_review_flow(lockfile_path="/some/lockfile.yaml", input_stream=stream)
            # Only get_users approved, not delete_users (skipped)
            mock_approve.assert_called_once()
            call_args = mock_approve.call_args
            assert "get_users" in call_args.kwargs.get("tool_ids", call_args[1].get("tool_ids", []))

        output = mock_console.file.getvalue()  # type: ignore[attr-defined]
        assert "HIGH-risk" in output
        assert "LOW-risk" in output


class TestGateSnapshotFlow:
    """gate_snapshot_flow validates and shows plan."""

    def test_no_lockfiles(self, mock_console: Console) -> None:
        from toolwright.ui.flows.gate_snapshot import gate_snapshot_flow

        with patch("toolwright.ui.flows.gate_snapshot.err_console", mock_console):
            gate_snapshot_flow(root_path="/nonexistent")

        output = mock_console.file.getvalue()  # type: ignore[attr-defined]
        assert "No lockfiles found" in output

    def test_rejects_directory(self, tmp_path: Path, mock_console: Console) -> None:
        from toolwright.ui.flows.gate_snapshot import gate_snapshot_flow

        with patch("toolwright.ui.flows.gate_snapshot.err_console", mock_console):
            gate_snapshot_flow(lockfile_path=str(tmp_path))

        output = mock_console.file.getvalue()  # type: ignore[attr-defined]
        assert "Expected a file, got a directory" in output

    def test_pending_tools_triggers_review_offer(self, mock_console: Console) -> None:
        from toolwright.ui.flows.gate_snapshot import gate_snapshot_flow

        tools = [_make_tool()]
        lockfile = MagicMock()

        with (
            patch("toolwright.ui.flows.gate_snapshot.err_console", mock_console),
            patch(
                "toolwright.ui.flows.gate_snapshot.load_lockfile_tools",
                return_value=(lockfile, tools),
            ),
            # User declines to jump to review
            patch("toolwright.ui.flows.gate_snapshot.confirm", return_value=False),
            patch("toolwright.ui.flows.gate_snapshot.run_gate_snapshot") as mock_snap,
        ):
            gate_snapshot_flow(lockfile_path="/some/lockfile.yaml")
            mock_snap.assert_not_called()

        output = mock_console.file.getvalue()  # type: ignore[attr-defined]
        assert "pending approval" in output

    def test_shows_plan_on_ready(self, mock_console: Console) -> None:
        from toolwright.ui.flows.gate_snapshot import gate_snapshot_flow

        tools = [_make_tool(status=ApprovalStatus.APPROVED)]
        lockfile = MagicMock()

        with (
            patch("toolwright.ui.flows.gate_snapshot.err_console", mock_console),
            patch(
                "toolwright.ui.flows.gate_snapshot.load_lockfile_tools",
                return_value=(lockfile, tools),
            ),
            patch("toolwright.ui.flows.gate_snapshot.confirm", return_value=True),
            patch("toolwright.ui.flows.gate_snapshot.run_gate_snapshot", return_value="/path/snap"),
        ):
            gate_snapshot_flow(lockfile_path="/some/lockfile.yaml")

        output = mock_console.file.getvalue()  # type: ignore[attr-defined]
        assert "Will run" in output
        assert "toolwright gate snapshot" in output
        assert "Baseline snapshot created" in output
