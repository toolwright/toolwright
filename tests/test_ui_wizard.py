"""Tests for the wizard / quickstart flow."""

from __future__ import annotations

from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner
from rich.console import Console

from toolwright.ui.console import TOOLWRIGHT_THEME


@pytest.fixture
def mock_console() -> Console:
    return Console(file=StringIO(), force_terminal=False, theme=TOOLWRIGHT_THEME)


class TestWizardLaunch:
    """Wizard launches on no-args + interactive, shows help otherwise."""

    def test_wizard_launches_when_interactive(self, mock_console: Console) -> None:
        from toolwright.ui.flows.quickstart import wizard_flow

        with (
            patch("toolwright.ui.flows.quickstart.err_console", mock_console),
            # Exit immediately
            patch("toolwright.ui.flows.quickstart.select_one", return_value="exit"),
        ):
            wizard_flow(root=Path(".toolwright"))

        output = mock_console.file.getvalue()  # type: ignore[attr-defined]
        # Should show branding
        assert "Cask" in output

    def test_shows_help_in_non_interactive_mode(self) -> None:
        """When --no-interactive is set, toolwright shows help instead of wizard."""
        runner = CliRunner()
        from toolwright.cli.main import cli

        result = runner.invoke(cli, ["--no-interactive"])
        assert result.exit_code == 0
        # Help output should appear since non-interactive shows help
        assert "Usage" in result.output or "Commands" in result.output

    def test_help_flag_still_works(self) -> None:
        """--help is not intercepted by wizard."""
        runner = CliRunner()
        from toolwright.cli.main import cli

        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "Usage" in result.output

    def test_version_flag_still_works(self) -> None:
        """--version is not intercepted by wizard."""
        runner = CliRunner()
        from toolwright.cli.main import cli

        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0


class TestWizardMenu:
    """Wizard menu dispatches correctly."""

    def test_exit_returns_immediately(self, mock_console: Console) -> None:
        from toolwright.ui.flows.quickstart import wizard_flow

        with (
            patch("toolwright.ui.flows.quickstart.err_console", mock_console),
            patch("toolwright.ui.flows.quickstart.select_one", return_value="exit"),
        ):
            wizard_flow(root=Path(".toolwright"))

    def test_dispatches_to_doctor(self, mock_console: Console) -> None:
        from toolwright.ui.flows.quickstart import wizard_flow

        call_count = {"n": 0}

        def mock_select(*_args, **_kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return "doctor"
            return "exit"

        with (
            patch("toolwright.ui.flows.quickstart.err_console", mock_console),
            patch("toolwright.ui.flows.quickstart.select_one", side_effect=mock_select),
            patch("toolwright.ui.flows.doctor.err_console", mock_console),
            patch("toolwright.ui.flows.doctor.find_toolpacks", return_value=[]),
            # confirm is lazily imported inside wizard_flow, patch at source
            patch("toolwright.ui.prompts.confirm", return_value=False),
        ):
            wizard_flow(root=Path(".toolwright"))

    def test_dispatches_to_init(self, mock_console: Console) -> None:
        from toolwright.ui.flows.quickstart import wizard_flow

        call_count = {"n": 0}

        def mock_select(*_args, **_kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return "init"
            return "exit"

        with (
            patch("toolwright.ui.flows.quickstart.err_console", mock_console),
            patch("toolwright.ui.flows.quickstart.select_one", side_effect=mock_select),
            patch("toolwright.ui.flows.init.err_console", mock_console),
            patch("toolwright.ui.flows.init.input_text", return_value="."),
            patch("toolwright.ui.flows.init.confirm", return_value=False),
            # confirm inside wizard_flow for "Return to menu?"
            patch("toolwright.ui.prompts.confirm", return_value=False),
        ):
            wizard_flow(root=Path(".toolwright"))


class TestWizardStatusSummary:
    """Wizard shows status summary on start."""

    def test_shows_toolpack_names(self, mock_console: Console, tmp_path: Path) -> None:
        from unittest.mock import MagicMock

        from toolwright.ui.flows.quickstart import wizard_flow

        # Create two toolpacks
        for name in ("api1", "api2"):
            tp = tmp_path / "toolpacks" / name
            tp.mkdir(parents=True)
            (tp / "toolpack.yaml").write_text(f"name: {name}")

        mock_status = MagicMock()
        mock_status.toolpack_id = "api1"
        mock_status.lockfile_state = "sealed"
        mock_status.verification_state = "pass"
        mock_status.drift_state = "clean"
        mock_status.pending_count = 0
        mock_status.has_baseline = True
        mock_status.has_mcp_config = True

        with (
            patch("toolwright.ui.flows.quickstart.err_console", mock_console),
            patch("toolwright.ui.flows.quickstart.select_one", return_value="exit"),
            patch("toolwright.ui.views.branding.err_console", mock_console),
            patch("toolwright.ui.flows.quickstart._gather_governance_status", return_value=[mock_status]),
        ):
            wizard_flow(root=tmp_path)

        output = mock_console.file.getvalue()  # type: ignore[attr-defined]
        assert "api1" in output


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
