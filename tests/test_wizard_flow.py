"""Tests for the wizard / quickstart flow (magic wizard rewrite)."""

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


# ---------------------------------------------------------------------------
# First-run detection
# ---------------------------------------------------------------------------


class TestIsFirstRun:
    """_is_first_run detects whether this is the user's first time."""

    def test_first_run_when_root_does_not_exist(self, tmp_path: Path) -> None:
        from toolwright.ui.flows.quickstart import _is_first_run

        root = tmp_path / "nonexistent"
        assert _is_first_run(root) is True

    def test_first_run_when_no_toolpacks(self, tmp_path: Path) -> None:
        from toolwright.ui.flows.quickstart import _is_first_run

        # Create empty .toolwright dir with no toolpacks
        root = tmp_path / ".toolwright"
        root.mkdir()
        assert _is_first_run(root) is True

    def test_not_first_run_when_toolpacks_exist(self, tmp_path: Path) -> None:
        from toolwright.ui.flows.quickstart import _is_first_run

        # Create .toolwright dir with a toolpack
        root = tmp_path
        tp = root / "toolpacks" / "my-api"
        tp.mkdir(parents=True)
        (tp / "toolpack.yaml").write_text("name: my-api")
        assert _is_first_run(root) is False


# ---------------------------------------------------------------------------
# Health bar rendering
# ---------------------------------------------------------------------------


class TestRenderHealthBar:
    """_render_health_bar shows compact governance summary."""

    def test_no_toolpacks_shows_hint(self, mock_console: Console) -> None:
        from toolwright.ui.flows.quickstart import _render_health_bar

        _render_health_bar([], mock_console)
        output = mock_console.file.getvalue()  # type: ignore[attr-defined]
        assert "No toolpacks found" in output
        assert "toolwright mint" in output

    def test_shows_toolpack_name(self, mock_console: Console) -> None:
        from toolwright.ui.flows.quickstart import _render_health_bar

        model = MagicMock()
        model.toolpack_id = "stripe-api"
        model.lockfile_state = "sealed"
        model.has_baseline = True
        model.drift_state = "clean"
        model.verification_state = "pass"
        model.pending_count = 0

        _render_health_bar([model], mock_console)
        output = mock_console.file.getvalue()  # type: ignore[attr-defined]
        assert "stripe-api" in output

    def test_shows_pending_count(self, mock_console: Console) -> None:
        from toolwright.ui.flows.quickstart import _render_health_bar

        model = MagicMock()
        model.toolpack_id = "test-api"
        model.lockfile_state = "pending"
        model.has_baseline = False
        model.drift_state = "not_checked"
        model.verification_state = "not_run"
        model.pending_count = 3

        _render_health_bar([model], mock_console)
        output = mock_console.file.getvalue()  # type: ignore[attr-defined]
        assert "3 pending" in output


# ---------------------------------------------------------------------------
# Dynamic menu building
# ---------------------------------------------------------------------------


class TestBuildMenu:
    """_build_menu creates context-aware menu based on governance state."""

    def test_no_toolpacks_offers_quickstart(self) -> None:
        from toolwright.ui.flows.quickstart import _build_menu

        menu = _build_menu(statuses=[], toolpacks=[])
        keys = [k for k, _ in menu]
        assert "quickstart" in keys
        assert "exit" in keys

    def test_pending_approvals_recommended_first(self) -> None:
        from toolwright.ui.flows.quickstart import _build_menu

        model = MagicMock()
        model.toolpack_id = "my-api"
        model.lockfile_state = "pending"
        model.verification_state = "not_run"
        model.drift_state = "not_checked"
        model.pending_count = 5
        model.has_baseline = False
        model.has_mcp_config = False

        menu = _build_menu([model], [Path("/fake/toolpack.yaml")])
        first_key, first_label = menu[0]
        assert first_key == "gate"
        assert "recommended" in first_label.lower()

    def test_all_green_recommends_ship(self) -> None:
        from toolwright.ui.flows.quickstart import _build_menu

        model = MagicMock()
        model.toolpack_id = "my-api"
        model.lockfile_state = "sealed"
        model.verification_state = "pass"
        model.drift_state = "clean"
        model.pending_count = 0
        model.has_baseline = True
        model.has_mcp_config = True

        menu = _build_menu([model], [Path("/fake/toolpack.yaml")])
        first_key, first_label = menu[0]
        assert first_key == "ship"
        assert "recommended" in first_label.lower()

    def test_failed_verification_recommends_repair(self) -> None:
        from toolwright.ui.flows.quickstart import _build_menu

        model = MagicMock()
        model.toolpack_id = "my-api"
        model.lockfile_state = "sealed"
        model.verification_state = "fail"
        model.drift_state = "clean"
        model.pending_count = 0
        model.has_baseline = True
        model.has_mcp_config = True

        menu = _build_menu([model], [Path("/fake/toolpack.yaml")])
        first_key, first_label = menu[0]
        assert first_key == "repair"
        assert "recommended" in first_label.lower()

    def test_always_has_exit(self) -> None:
        from toolwright.ui.flows.quickstart import _build_menu

        menu = _build_menu([], [])
        keys = [k for k, _ in menu]
        assert "exit" in keys


# ---------------------------------------------------------------------------
# Wizard flow integration
# ---------------------------------------------------------------------------


class TestWizardFirstRun:
    """First-run wizard shows welcome and detection."""

    def test_first_run_exit(self, mock_console: Console) -> None:
        from toolwright.ui.flows.quickstart import wizard_flow

        with (
            patch("toolwright.ui.flows.quickstart.err_console", mock_console),
            patch("toolwright.ui.flows.quickstart.select_one", return_value="exit"),
            patch("toolwright.ui.views.branding.err_console", mock_console),
        ):
            wizard_flow(root=Path("/nonexistent/.toolwright"))

        output = mock_console.file.getvalue()  # type: ignore[attr-defined]
        assert "Welcome" in output or "toolwright" in output.lower()

    def test_first_run_shows_project_detection(self, mock_console: Console, tmp_path: Path) -> None:
        from toolwright.ui.flows.quickstart import wizard_flow

        # Create a Python project
        (tmp_path / "requirements.txt").write_text("fastapi\n")
        (tmp_path / "main.py").write_text("from fastapi import FastAPI\n")

        with (
            patch("toolwright.ui.flows.quickstart.err_console", mock_console),
            patch("toolwright.ui.flows.quickstart.select_one", return_value="exit"),
            patch("toolwright.ui.views.branding.err_console", mock_console),
            # detect_project runs on cwd, so mock cwd
            patch("toolwright.ui.flows.quickstart.Path") as MockPath,
        ):
            MockPath.cwd.return_value = tmp_path
            # Keep the real Path for other uses
            MockPath.side_effect = Path
            wizard_flow(root=tmp_path / ".toolwright")


class TestWizardReturning:
    """Returning user wizard shows health bar and smart menu."""

    def test_returning_user_exit(self, mock_console: Console, tmp_path: Path) -> None:
        from toolwright.ui.flows.quickstart import wizard_flow

        # Create a toolpack so it's not first-run
        tp = tmp_path / "toolpacks" / "test-api"
        tp.mkdir(parents=True)
        (tp / "toolpack.yaml").write_text("name: test-api")

        mock_status = MagicMock()
        mock_status.toolpack_id = "test-api"
        mock_status.lockfile_state = "sealed"
        mock_status.verification_state = "pass"
        mock_status.drift_state = "clean"
        mock_status.pending_count = 0
        mock_status.has_baseline = True
        mock_status.has_mcp_config = True
        mock_status.tool_count = 5
        mock_status.approved_count = 5
        mock_status.blocked_count = 0

        with (
            patch("toolwright.ui.flows.quickstart.err_console", mock_console),
            patch("toolwright.ui.flows.quickstart.select_one", return_value="exit"),
            patch("toolwright.ui.views.branding.err_console", mock_console),
            patch("toolwright.ui.flows.quickstart._gather_governance_status", return_value=[mock_status]),
        ):
            wizard_flow(root=tmp_path)

        output = mock_console.file.getvalue()  # type: ignore[attr-defined]
        assert "test-api" in output


# ---------------------------------------------------------------------------
# Quickstart flow
# ---------------------------------------------------------------------------


class TestQuickstartFlow:
    """Quickstart sub-flow collects inputs and shows plan."""

    def test_shows_plan_before_mint(self, mock_console: Console) -> None:
        from toolwright.ui.flows.quickstart import _quickstart_flow

        with (
            patch("toolwright.ui.flows.quickstart.err_console", mock_console),
            patch(
                "toolwright.ui.flows.quickstart.input_text",
                side_effect=["https://api.example.com", "api.example.com", ""],
            ),
            patch("toolwright.ui.flows.quickstart.confirm", return_value=False),
        ):
            _quickstart_flow(root=Path(".toolwright"), verbose=False)

        output = mock_console.file.getvalue()  # type: ignore[attr-defined]
        assert "Will run" in output
        assert "toolwright mint https://api.example.com" in output
        assert "-a api.example.com" in output

    def test_aborts_on_empty_url(self, mock_console: Console) -> None:
        from toolwright.ui.flows.quickstart import _quickstart_flow

        with (
            patch("toolwright.ui.flows.quickstart.err_console", mock_console),
            patch("toolwright.ui.flows.quickstart.input_text", return_value=""),
        ):
            _quickstart_flow(root=Path(".toolwright"), verbose=False)

        output = mock_console.file.getvalue()  # type: ignore[attr-defined]
        assert "URL is required" in output


# ---------------------------------------------------------------------------
# Dashboard fallback
# ---------------------------------------------------------------------------


class TestDashboardFallback:
    """Dashboard shows sys.executable in install hint."""

    def test_fallback_shows_python_path(self) -> None:
        import sys

        from toolwright.ui.dashboard import _fallback

        mock_con = Console(file=StringIO(), force_terminal=False, theme=TOOLWRIGHT_THEME)

        with patch("toolwright.ui.console.err_console", mock_con):
            _fallback("some/toolpack.yaml", ".toolwright")

        output = mock_con.file.getvalue()  # type: ignore[attr-defined]
        assert sys.executable in output
        assert "pip install" in output
