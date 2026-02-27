"""Tests for the Ship Secure Agent flow (6-stage lifecycle)."""

from __future__ import annotations

from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from rich.console import Console

from toolwright.ui.console import TOOLWRIGHT_THEME


@pytest.fixture
def mock_console() -> Console:
    return Console(file=StringIO(), force_terminal=False, theme=TOOLWRIGHT_THEME)


class TestShipFlowStageCapture:
    """Stage 1: Capture."""

    def test_uses_existing_toolpack_when_available(
        self, tmp_path: Path, mock_console: Console
    ) -> None:
        from toolwright.ui.flows.ship import _stage_capture

        tp = tmp_path / "toolpacks" / "api"
        tp.mkdir(parents=True)
        (tp / "toolpack.yaml").write_text("name: api")

        with patch("toolwright.ui.flows.ship.err_console", mock_console):
            result = _stage_capture(
                root=tmp_path, verbose=False,
                con=mock_console, input_stream=StringIO("y\n"),
            )

        assert result is not None
        assert "toolpack.yaml" in result

    def test_returns_none_on_empty_url(self, tmp_path: Path, mock_console: Console) -> None:
        from toolwright.ui.flows.ship import _stage_capture

        with patch("toolwright.ui.flows.ship.err_console", mock_console):
            result = _stage_capture(
                root=tmp_path, verbose=False,
                con=mock_console, input_stream=StringIO("\n"),
            )

        assert result is None

    def test_shows_plan_before_capture(self, tmp_path: Path, mock_console: Console) -> None:
        from toolwright.ui.flows.ship import _stage_capture

        # Provide URL, host, name, then decline proceed
        stream = StringIO("https://api.example.com\napi.example.com\ntest\nn\n")
        with patch("toolwright.ui.flows.ship.err_console", mock_console):
            _stage_capture(root=tmp_path, verbose=False, con=mock_console, input_stream=stream)

        output = mock_console.file.getvalue()  # type: ignore[attr-defined]
        assert "Will run" in output
        assert "toolwright mint" in output


class TestShipFlowStageServe:
    """Stage 6: Serve shows command and CI hints."""

    def test_shows_serve_command(self, mock_console: Console) -> None:
        from toolwright.ui.flows.ship import _stage_serve

        # Decline config generation
        stream = StringIO("n\n")
        with patch("toolwright.ui.flows.ship.err_console", mock_console):
            _stage_serve(
                toolpack_path="/my/toolpack.yaml",
                root=Path(".toolwright"),
                con=mock_console,
                input_stream=stream,
            )

        output = mock_console.file.getvalue()  # type: ignore[attr-defined]
        assert "toolwright serve --toolpack /my/toolpack.yaml" in output
        assert "Ctrl+C" in output

    def test_shows_ci_commands(self, mock_console: Console) -> None:
        from toolwright.ui.flows.ship import _stage_serve

        stream = StringIO("n\n")
        with patch("toolwright.ui.flows.ship.err_console", mock_console):
            _stage_serve(
                toolpack_path="/my/toolpack.yaml",
                root=Path(".toolwright"),
                con=mock_console,
                input_stream=stream,
            )

        output = mock_console.file.getvalue()  # type: ignore[attr-defined]
        assert "toolwright verify" in output
        assert "toolwright drift" in output
        assert "CI" in output


class TestShipFlowStageSnapshot:
    """Stage 4: Snapshot."""

    def test_calls_snapshot_on_confirm(self, mock_console: Console) -> None:
        from toolwright.ui.flows.ship import _stage_snapshot

        with (
            patch("toolwright.ui.flows.ship.err_console", mock_console),
            patch("toolwright.ui.ops.run_gate_snapshot", return_value="/snap"),
        ):
            result = _stage_snapshot(
                lockfile_path="/my/lockfile.yaml",
                root=Path(".toolwright"),
                con=mock_console,
                input_stream=StringIO("y\n"),
            )

        assert result is True
        output = mock_console.file.getvalue()  # type: ignore[attr-defined]
        assert "Baseline snapshot created" in output

    def test_returns_false_on_decline(self, mock_console: Console) -> None:
        from toolwright.ui.flows.ship import _stage_snapshot

        with patch("toolwright.ui.flows.ship.err_console", mock_console):
            result = _stage_snapshot(
                lockfile_path="/my/lockfile.yaml",
                root=Path(".toolwright"),
                con=mock_console,
                input_stream=StringIO("n\n"),
            )

        assert result is False


class TestShipFlowStageApprove:
    """Stage 3: Approve."""

    def test_skips_when_all_approved(self, mock_console: Console) -> None:
        from toolwright.ui.flows.ship import _stage_approve

        from toolwright.core.approval.lockfile import ApprovalStatus, ToolApproval

        tools = [ToolApproval(
            tool_id="get_users",
            signature_id="GET:/api/users@api.example.com",
            name="get_users",
            method="GET",
            path="/api/users",
            host="api.example.com",
            risk_tier="low",
            status=ApprovalStatus.APPROVED,
            toolsets=["default"],
        )]
        lockfile = MagicMock()

        with (
            patch("toolwright.ui.flows.ship.err_console", mock_console),
            patch("toolwright.ui.flows.ship.load_lockfile_tools", return_value=(lockfile, tools)),
        ):
            result = _stage_approve(
                lockfile_path="/my/lockfile.yaml",
                root=Path(".toolwright"),
                verbose=False,
                con=mock_console,
            )

        assert result is True
        output = mock_console.file.getvalue()  # type: ignore[attr-defined]
        assert "already approved" in output.lower()

    def test_declines_approval_returns_false(self, mock_console: Console) -> None:
        from toolwright.ui.flows.ship import _stage_approve

        from toolwright.core.approval.lockfile import ApprovalStatus, ToolApproval

        tools = [ToolApproval(
            tool_id="get_users",
            signature_id="GET:/api/users@api.example.com",
            name="get_users",
            method="GET",
            path="/api/users",
            host="api.example.com",
            risk_tier="low",
            status=ApprovalStatus.PENDING,
            toolsets=["default"],
        )]
        lockfile = MagicMock()

        with (
            patch("toolwright.ui.flows.ship.err_console", mock_console),
            patch("toolwright.ui.flows.ship.load_lockfile_tools", return_value=(lockfile, tools)),
        ):
            result = _stage_approve(
                lockfile_path="/my/lockfile.yaml",
                root=Path(".toolwright"),
                verbose=False,
                con=mock_console,
                input_stream=StringIO("n\n"),
            )

        assert result is False


class TestShipFlowStageTracker:
    """Stage tracker renders correctly."""

    def test_renders_tracker_with_done_and_active(self) -> None:
        from toolwright.ui.flows.ship import _render_stage_tracker

        result = _render_stage_tracker(current=2, done={0, 1})
        # Should contain all stage names
        assert "capture" in result
        assert "review" in result
        assert "approve" in result
        assert "snapshot" in result

    def test_shows_tracker(self, mock_console: Console) -> None:
        from toolwright.ui.flows.ship import _show_tracker

        _show_tracker(current=1, done={0}, con=mock_console)

        output = mock_console.file.getvalue()  # type: ignore[attr-defined]
        assert "capture" in output
        assert "review" in output


class TestShipFlowEarlyExit:
    """Early exit summary."""

    def test_early_exit_shows_completed(self, mock_console: Console) -> None:
        from toolwright.ui.console import get_symbols
        from toolwright.ui.flows.ship import _early_exit

        sym = get_symbols()
        _early_exit(done={0, 1}, con=mock_console, sym=sym)

        output = mock_console.file.getvalue()  # type: ignore[attr-defined]
        assert "Capture" in output
        assert "Review" in output
        assert "resume" in output.lower() or "toolwright ship" in output

    def test_early_exit_no_stages(self, mock_console: Console) -> None:
        from toolwright.ui.console import get_symbols
        from toolwright.ui.flows.ship import _early_exit

        sym = get_symbols()
        _early_exit(done=set(), con=mock_console, sym=sym)

        output = mock_console.file.getvalue()  # type: ignore[attr-defined]
        assert "Exited early" in output


class TestShipFlowToolPreview:
    """Tool preview in review stage."""

    def test_shows_tool_count_and_risk(self, mock_console: Console) -> None:
        from toolwright.ui.console import get_symbols
        from toolwright.ui.flows.ship import _show_tool_preview

        mock_tool = MagicMock()
        mock_tool.name = "get_users"
        mock_tool.risk_tier = "low"
        mock_tool.method = "GET"
        mock_tool.path = "/api/users"

        sym = get_symbols()
        _show_tool_preview([mock_tool], mock_console, sym)

        output = mock_console.file.getvalue()  # type: ignore[attr-defined]
        assert "1 tool(s) discovered" in output
