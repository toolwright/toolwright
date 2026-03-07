"""Tests for interactive init and config flows."""

from __future__ import annotations

from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pytest
from rich.console import Console

from toolwright.ui.console import TOOLWRIGHT_THEME


@pytest.fixture
def mock_console() -> Console:
    return Console(file=StringIO(), force_terminal=False, theme=TOOLWRIGHT_THEME)


class TestInitFlow:
    """init_flow() prompts for directory and shows plan."""

    def test_shows_plan_with_default_directory(self, mock_console: Console) -> None:
        from toolwright.ui.flows.init import init_flow

        with (
            patch("toolwright.ui.flows.init.err_console", mock_console),
            patch("toolwright.ui.flows.init.confirm", return_value=True),
            patch("toolwright.core.init.service.initialize_project"),
        ):
            init_flow(directory=".")

        output = mock_console.file.getvalue()  # type: ignore[attr-defined]
        assert "Will run" in output
        assert "toolwright init -d ." in output

    def test_shows_success_after_init(self, mock_console: Console) -> None:
        from toolwright.ui.flows.init import init_flow

        with (
            patch("toolwright.ui.flows.init.err_console", mock_console),
            patch("toolwright.ui.flows.init.confirm", return_value=True),
            patch("toolwright.core.init.service.initialize_project"),
        ):
            init_flow(directory="/my/project")

        output = mock_console.file.getvalue()  # type: ignore[attr-defined]
        assert "Toolwright initialized" in output

    def test_aborts_on_decline(self, mock_console: Console) -> None:
        from toolwright.ui.flows.init import init_flow

        with (
            patch("toolwright.ui.flows.init.err_console", mock_console),
            patch("toolwright.ui.flows.init.confirm", return_value=False),
            patch("toolwright.core.init.service.initialize_project") as mock_run,
        ):
            init_flow(directory=".")
            mock_run.assert_not_called()

    def test_prompts_for_directory_when_none(self, mock_console: Console) -> None:
        from toolwright.ui.flows.init import init_flow

        with (
            patch("toolwright.ui.flows.init.err_console", mock_console),
            patch("toolwright.ui.flows.init.input_text", return_value="/some/dir"),
            patch("toolwright.ui.flows.init.confirm", return_value=True),
            patch("toolwright.core.init.service.initialize_project"),
        ):
            init_flow()

        output = mock_console.file.getvalue()  # type: ignore[attr-defined]
        assert "toolwright init -d /some/dir" in output

    def test_shows_demo_in_next_steps(self, mock_console: Console) -> None:
        """After init, next-steps must mention toolwright demo."""
        from toolwright.ui.flows.init import init_flow

        with (
            patch("toolwright.ui.flows.init.err_console", mock_console),
            patch("toolwright.ui.flows.init.confirm", return_value=True),
            patch("toolwright.core.init.service.initialize_project"),
        ):
            init_flow(directory="/my/project")

        output = mock_console.file.getvalue()  # type: ignore[attr-defined]
        assert "toolwright demo" in output

    def test_handles_init_failure(self, mock_console: Console) -> None:
        from toolwright.ui.flows.init import init_flow

        with (
            patch("toolwright.ui.flows.init.err_console", mock_console),
            patch("toolwright.ui.flows.init.confirm", return_value=True),
            patch(
                "toolwright.core.init.service.initialize_project",
                side_effect=RuntimeError("boom"),
            ),
        ):
            init_flow(directory=".")

        output = mock_console.file.getvalue()  # type: ignore[attr-defined]
        assert "Init failed" in output


class TestConfigFlow:
    """config_flow() generates config snippets with guidance."""

    def test_shows_plan(self, tmp_path: Path, mock_console: Console) -> None:
        from toolwright.ui.flows.config import config_flow

        tp = tmp_path / "toolpacks" / "api"
        tp.mkdir(parents=True)
        (tp / "toolpack.yaml").write_text("name: api")

        with (
            patch("toolwright.ui.flows.config.err_console", mock_console),
            patch(
                "toolwright.ui.flows.config.select_one",
                return_value="Claude Code",
            ),
            patch("toolwright.core.config_snippets.render_mcp_client_config", return_value="{}"),
        ):
            config_flow(root=tmp_path)

        output = mock_console.file.getvalue()  # type: ignore[attr-defined]
        assert "Will run" in output
        assert "toolwright config" in output

    def test_shows_error_when_no_toolpacks(
        self, tmp_path: Path, mock_console: Console
    ) -> None:
        from toolwright.ui.flows.config import config_flow

        with patch("toolwright.ui.flows.config.err_console", mock_console):
            config_flow(root=tmp_path)

        output = mock_console.file.getvalue()  # type: ignore[attr-defined]
        assert "No toolpacks found" in output

    def test_shows_target_path_for_claude_desktop(
        self, mock_console: Console
    ) -> None:
        from toolwright.ui.flows.config import config_flow

        with (
            patch("toolwright.ui.flows.config.err_console", mock_console),
            patch(
                "toolwright.ui.flows.config.select_one",
                return_value="Claude Desktop",
            ),
            patch("toolwright.core.config_snippets.render_mcp_client_config", return_value="{}"),
        ):
            config_flow(toolpack_path="/some/toolpack.yaml")

        output = mock_console.file.getvalue()  # type: ignore[attr-defined]
        assert "Target config file" in output

    def test_codex_format_selected_for_codex_client(
        self, mock_console: Console
    ) -> None:
        from toolwright.ui.flows.config import config_flow

        with (
            patch("toolwright.ui.flows.config.err_console", mock_console),
            patch("toolwright.ui.flows.config.select_one", return_value="Codex"),
            patch(
                "toolwright.core.config_snippets.render_mcp_client_config",
                return_value="{}",
            ) as mock_render,
        ):
            config_flow(toolpack_path="/some/toolpack.yaml")

        # Check that the shared renderer was called with fmt="codex"
        mock_render.assert_called_once_with(
            toolpack_path="/some/toolpack.yaml",
            fmt="codex",
        )


class TestFlowRegistrationPhase4:
    """Init flow is registered in INTERACTIVE_COMMANDS."""

    def test_init_registered(self) -> None:
        from toolwright.ui.flows import INTERACTIVE_COMMANDS

        assert "init" in INTERACTIVE_COMMANDS
