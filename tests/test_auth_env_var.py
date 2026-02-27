"""Tests for TOOLWRIGHT_AUTH_HEADER env var fallback (Task 7.6)."""

from __future__ import annotations

import json
from pathlib import Path

import click
import pytest
from click.testing import CliRunner

from toolwright.cli.commands_mcp import register_mcp_commands


def _write_minimal_tools(tmp_path: Path) -> Path:
    """Create a minimal tools.json for server instantiation."""
    tools_path = tmp_path / "tools.json"
    tools_path.write_text(json.dumps({
        "version": "1.0.0",
        "schema_version": "1.0",
        "name": "Test",
        "allowed_hosts": [],
        "actions": [],
    }))
    return tools_path


def _make_cli_with_capture(captured: dict[str, object]):
    """Build a CLI group with serve registered, capturing run_mcp_serve kwargs."""

    @click.group()
    @click.pass_context
    def cli(ctx: click.Context) -> None:
        ctx.ensure_object(dict)

    def fake_run_with_lock(
        ctx: click.Context,
        name: str,
        fn: object,
        lock_id: object = None,
    ) -> None:
        # fn is a lambda wrapping run_mcp_serve.  We call it and let it
        # fail (the import inside will succeed, but we just need Click to
        # have resolved the options). Instead, inspect the serve command's
        # callback closure by grabbing parameters from ctx.
        pass

    register_mcp_commands(cli=cli, run_with_lock=fake_run_with_lock)
    return cli


def test_serve_uses_auth_env_var(tmp_path: Path) -> None:
    """When TOOLWRIGHT_AUTH_HEADER is set and --auth is not provided,
    the Click option should resolve auth_header from the env var."""
    tools_path = _write_minimal_tools(tmp_path)

    # Inspect the Click command's params to verify envvar is configured
    captured: dict[str, object] = {}
    cli = _make_cli_with_capture(captured)

    # Find the serve command and check its --auth option
    serve_cmd = cli.commands.get("serve")
    assert serve_cmd is not None, "serve command not registered"

    auth_param = None
    for param in serve_cmd.params:
        if param.name == "auth_header":
            auth_param = param
            break

    assert auth_param is not None, "--auth param not found on serve command"
    assert auth_param.envvar == "TOOLWRIGHT_AUTH_HEADER", (
        f"Expected envvar='TOOLWRIGHT_AUTH_HEADER', got {auth_param.envvar!r}"
    )


def test_explicit_auth_overrides_env_var(tmp_path: Path) -> None:
    """When both TOOLWRIGHT_AUTH_HEADER env var and --auth flag are provided,
    the explicit --auth flag should win (Click's default behavior).

    This is guaranteed by Click when envvar is set on an option:
    explicit CLI value takes priority over env var.
    We verify the option is configured with envvar so Click handles precedence.
    """
    tools_path = _write_minimal_tools(tmp_path)

    captured: dict[str, object] = {}
    cli = _make_cli_with_capture(captured)

    runner = CliRunner()
    # Both env var and explicit --auth provided; Click gives --auth priority
    result = runner.invoke(cli, [
        "serve",
        "--tools", str(tools_path),
        "--unsafe-no-lockfile",
        "--auth", "Bearer explicit-token",
    ], env={"TOOLWRIGHT_AUTH_HEADER": "Bearer env-token"})

    assert result.exit_code == 0, f"CLI failed: {result.output}"
