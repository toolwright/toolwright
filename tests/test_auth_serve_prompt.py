"""Tests for auto-prompt auth setup on serve."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from toolwright.mcp.runtime import prompt_auth_setup_if_missing


def _make_tools_json(tmp_path: Path, hosts: list[str]) -> Path:
    tools_path = tmp_path / "tools.json"
    tools_path.write_text(json.dumps({"actions": [], "allowed_hosts": hosts}))
    return tools_path


def test_no_missing_auth_no_prompt(tmp_path: Path, capsys):
    tools_path = _make_tools_json(tmp_path, ["api.example.com"])
    prompt_auth_setup_if_missing(
        tools_path=str(tools_path),
        auth_header="Bearer tok",
        root=tmp_path,
    )
    captured = capsys.readouterr()
    assert "WARNING" not in captured.err


def test_missing_auth_interactive_prompts(tmp_path: Path, capsys):
    tools_path = _make_tools_json(tmp_path, ["api.example.com"])
    with (
        patch("toolwright.mcp.runtime.sys") as mock_sys,
        patch("toolwright.mcp.runtime.click.confirm", return_value=False),
    ):
        mock_sys.stdin.isatty.return_value = True
        prompt_auth_setup_if_missing(
            tools_path=str(tools_path),
            auth_header=None,
            root=tmp_path,
        )
    captured = capsys.readouterr()
    assert "WARNING" in captured.err


def test_missing_auth_non_interactive_warnings_only(tmp_path: Path, capsys):
    tools_path = _make_tools_json(tmp_path, ["api.example.com"])
    with patch("toolwright.mcp.runtime.sys") as mock_sys:
        mock_sys.stdin.isatty.return_value = False
        prompt_auth_setup_if_missing(
            tools_path=str(tools_path),
            auth_header=None,
            root=tmp_path,
        )
    captured = capsys.readouterr()
    assert "WARNING" in captured.err


def test_user_declines_setup_continues(tmp_path: Path, capsys):
    tools_path = _make_tools_json(tmp_path, ["api.example.com"])
    with (
        patch("toolwright.mcp.runtime.sys") as mock_sys,
        patch("toolwright.mcp.runtime.click.confirm", return_value=False),
    ):
        mock_sys.stdin.isatty.return_value = True
        prompt_auth_setup_if_missing(
            tools_path=str(tools_path),
            auth_header=None,
            root=tmp_path,
        )
    captured = capsys.readouterr()
    assert "WARNING" in captured.err


def test_user_accepts_setup_calls_flow(tmp_path: Path):
    tools_path = _make_tools_json(tmp_path, ["api.example.com"])
    with (
        patch("toolwright.mcp.runtime.sys") as mock_sys,
        patch("toolwright.mcp.runtime.click.confirm", return_value=True),
        patch("toolwright.cli.auth_setup.auth_setup_flow") as mock_flow,
    ):
        mock_sys.stdin.isatty.return_value = True
        prompt_auth_setup_if_missing(
            tools_path=str(tools_path),
            auth_header=None,
            root=tmp_path,
        )
    mock_flow.assert_called_once()


class TestDotenvAuthLoading:
    """Tests that .toolwright/.env tokens are loaded into os.environ during serve."""

    def test_dotenv_loaded_before_auth_check(self, tmp_path: Path, capsys):
        """Auth tokens from .env should be visible to prompt_auth_setup_if_missing."""
        import os

        from toolwright.mcp.runtime import inject_dotenv_auth

        # Create .toolwright/.env with a token
        env_dir = tmp_path / ".toolwright"
        env_dir.mkdir(parents=True)
        env_file = env_dir / ".env"
        env_file.write_text("TOOLWRIGHT_AUTH_API_EXAMPLE_COM=Bearer test_token\n")

        # Inject dotenv into os.environ
        injected = inject_dotenv_auth(root=tmp_path)

        try:
            assert "TOOLWRIGHT_AUTH_API_EXAMPLE_COM" in injected
            assert os.environ.get("TOOLWRIGHT_AUTH_API_EXAMPLE_COM") == "Bearer test_token"

            # Now auth check should NOT warn (token is set)
            tools_path = _make_tools_json(tmp_path, ["api.example.com"])
            prompt_auth_setup_if_missing(
                tools_path=str(tools_path),
                auth_header=None,
                root=tmp_path,
            )
            captured = capsys.readouterr()
            assert "WARNING" not in captured.err
        finally:
            # Clean up injected env vars
            os.environ.pop("TOOLWRIGHT_AUTH_API_EXAMPLE_COM", None)

    def test_dotenv_does_not_overwrite_existing_env(self, tmp_path: Path):
        """Existing env vars should take precedence over .env file."""
        import os

        from toolwright.mcp.runtime import inject_dotenv_auth

        env_dir = tmp_path / ".toolwright"
        env_dir.mkdir(parents=True)
        env_file = env_dir / ".env"
        env_file.write_text("TOOLWRIGHT_AUTH_API_EXAMPLE_COM=Bearer from_dotenv\n")

        os.environ["TOOLWRIGHT_AUTH_API_EXAMPLE_COM"] = "Bearer from_shell"
        try:
            inject_dotenv_auth(root=tmp_path)
            assert os.environ["TOOLWRIGHT_AUTH_API_EXAMPLE_COM"] == "Bearer from_shell"
        finally:
            os.environ.pop("TOOLWRIGHT_AUTH_API_EXAMPLE_COM", None)

    def test_dotenv_missing_file_is_noop(self, tmp_path: Path):
        """Missing .env file should not cause errors."""
        from toolwright.mcp.runtime import inject_dotenv_auth

        injected = inject_dotenv_auth(root=tmp_path)
        assert injected == {}
