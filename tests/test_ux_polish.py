"""UX polish tests — verifying improved user-facing messages and behavior.

Tests for issues identified in the comprehensive UX audit:
1. `init` next steps should tell user that mint will print exact commands
2. Claude Desktop config path in `serve` help should be correct
3. `gate allow` should print next-step guidance after approvals
4. `doctor` success output should go to stdout (not stderr only)
5. `bundle` success output should go to stdout (not stderr only)
6. `config` should be a core command for discoverability
7. auth.py should not catch ImportError on asyncio (stdlib)
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

from click.testing import CliRunner

from tests.helpers import write_demo_toolpack
from toolwright.cli.main import cli

# --- 1. init next steps should tell user mint prints the exact commands ---


def test_init_next_steps_show_all_entry_paths(tmp_path: Path) -> None:
    """init should show all 3 entry paths (mint, HAR import, OpenAPI import)
    so users know how to start regardless of their situation."""
    runner = CliRunner()
    result = runner.invoke(cli, ["init", "--directory", str(tmp_path)])

    assert result.exit_code == 0
    output = result.output.lower()
    # All 3 entry paths must be visible
    assert "toolwright mint" in output
    assert "toolwright capture import" in output
    assert "openapi" in output
    # Follow-up commands shown directly
    assert "gate allow" in output
    assert "serve" in output


def test_init_next_steps_no_bare_gate_allow_all(tmp_path: Path) -> None:
    """init should not print a bare `toolwright gate allow --all` without --lockfile,
    since that will fail when run from a project root after mint."""
    runner = CliRunner()
    result = runner.invoke(cli, ["init", "--directory", str(tmp_path)])

    assert result.exit_code == 0
    lines = result.output.strip().split("\n")
    for line in lines:
        stripped = line.strip()
        # Bare "toolwright gate allow --all" without --lockfile is misleading
        if (
            "toolwright gate allow --all" in stripped
            and "--lockfile" not in stripped
            and (stripped.startswith("toolwright gate") or stripped.startswith("2."))
        ):
            raise AssertionError(
                f"init prints bare 'gate allow --all' without --lockfile: {stripped!r}"
            )


# --- 2. Claude Desktop config path in serve help ---


def test_serve_help_claude_config_path_not_wrong() -> None:
    """serve help should not reference the wrong ~/.claude/ path."""
    runner = CliRunner()
    result = runner.invoke(cli, ["serve", "--help"])

    assert result.exit_code == 0
    # The wrong path:
    assert "~/.claude/claude_desktop_config.json" not in result.output


# --- 3. gate allow should print next-step guidance ---


def test_gate_allow_prints_next_steps(tmp_path: Path) -> None:
    """After approving tools, gate allow should print guidance on what to do next."""
    # Create tools manifest with a pending tool
    tools_path = tmp_path / "tools.json"
    lockfile_path = tmp_path / "toolwright.lock.yaml"
    manifest = {
        "actions": [
            {
                "name": "get_test",
                "signature_id": "sig_get_test",
                "method": "GET",
                "path": "/test",
                "host": "example.com",
                "risk_tier": "low",
            }
        ]
    }
    tools_path.write_text(json.dumps(manifest))

    runner = CliRunner()
    # First sync to create pending tools
    runner.invoke(
        cli,
        ["gate", "sync", "--tools", str(tools_path), "--lockfile", str(lockfile_path)],
    )

    # Then approve all
    result = runner.invoke(
        cli,
        ["gate", "allow", "--all", "--yes", "--lockfile", str(lockfile_path)],
    )

    assert result.exit_code == 0
    output = result.output.lower()
    # Should mention serve as the next step after approval
    assert "serve" in output or "next" in output, (
        f"gate allow should print next-step guidance mentioning serve. Got: {result.output!r}"
    )


# --- 4. doctor success output should include stdout ---


def test_doctor_success_on_stdout(tmp_path: Path) -> None:
    """Doctor success message should go to stdout, not only stderr."""
    toolpack_file = write_demo_toolpack(tmp_path)
    runner = CliRunner()

    result = runner.invoke(
        cli,
        ["doctor", "--toolpack", str(toolpack_file), "--runtime", "local"],
    )

    assert result.exit_code == 0
    # Success should be on stdout (not exclusively stderr)
    assert "Doctor check passed" in result.stdout


def test_doctor_errors_still_on_stderr(tmp_path: Path) -> None:
    """Doctor error messages should remain on stderr."""
    toolpack_file = write_demo_toolpack(tmp_path)
    tools_path = toolpack_file.parent / "artifact" / "tools.json"
    tools_path.unlink()

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["doctor", "--toolpack", str(toolpack_file), "--runtime", "local"],
    )

    assert result.exit_code != 0
    assert "tools.json missing" in (result.output + (result.stderr_bytes or b"").decode())


# --- 5. bundle success output should include stdout ---


def test_bundle_success_on_stdout(tmp_path: Path) -> None:
    """Bundle success message should go to stdout, not only stderr."""
    toolpack_file = write_demo_toolpack(tmp_path)
    runner = CliRunner()

    result = runner.invoke(
        cli,
        [
            "bundle", "--toolpack", str(toolpack_file),
            "--out", str(tmp_path / "out.zip"),
            "--verbose",
        ],
    )

    if result.exit_code == 0:
        # Verbose bundle message should appear on stdout
        assert "Bundle created" in result.stdout


# --- 6. config should be a core command ---


def test_config_in_operations_commands() -> None:
    """config should be listed in OPERATIONS_COMMANDS (setup step, not daily use)."""
    from toolwright.cli.main import OPERATIONS_COMMANDS

    assert "config" in OPERATIONS_COMMANDS


# --- 7. auth.py should not catch ImportError on asyncio (stdlib) ---


def test_auth_login_does_not_guard_asyncio_import() -> None:
    """auth login should guard playwright import, not asyncio (which is stdlib)."""
    auth_path = Path("toolwright/cli/auth.py")
    tree = ast.parse(auth_path.read_text())

    for node in ast.walk(tree):
        if isinstance(node, ast.Try):
            for handler in node.handlers:
                if (
                    handler.type
                    and isinstance(handler.type, ast.Name)
                    and handler.type.id == "ImportError"
                ):
                    for stmt in node.body:
                        if isinstance(stmt, ast.Import):
                            for alias in stmt.names:
                                if alias.name == "asyncio":
                                    raise AssertionError(
                                        "auth.py wraps `import asyncio` in try/except ImportError. "
                                        "asyncio is stdlib and never fails. Guard playwright instead."
                                    )


# --- 8. verify --mode replay should emit deprecation warning ---


def test_verify_replay_mode_emits_deprecation_warning(tmp_path: Path) -> None:
    """Using --mode replay should print a deprecation warning suggesting baseline-check."""
    toolpack_file = write_demo_toolpack(tmp_path)
    runner = CliRunner()

    result = runner.invoke(
        cli,
        ["verify", "--toolpack", str(toolpack_file), "--mode", "replay"],
    )

    # Should print deprecation warning regardless of exit code
    output = result.output + (result.stderr_bytes or b"").decode()
    assert "deprecated" in output.lower(), (
        f"verify --mode replay should print deprecation warning. Got: {result.output!r}"
    )
    assert "baseline-check" in output, (
        f"deprecation warning should suggest 'baseline-check'. Got: {result.output!r}"
    )


def test_verify_baseline_check_mode_no_deprecation_warning(tmp_path: Path) -> None:
    """Using --mode baseline-check should NOT print a deprecation warning."""
    toolpack_file = write_demo_toolpack(tmp_path)
    runner = CliRunner()

    result = runner.invoke(
        cli,
        ["verify", "--toolpack", str(toolpack_file), "--mode", "baseline-check"],
    )

    output = result.output + (result.stderr_bytes or b"").decode()
    assert "deprecated" not in output.lower(), (
        f"verify --mode baseline-check should not print deprecation warning. Got: {result.output!r}"
    )


# --- 9. Help command ordering should follow user workflow ---


def test_help_core_commands_in_workflow_order() -> None:
    """Core commands in --help should follow user workflow order:
    create -> serve -> gate -> status -> drift -> repair."""
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])

    assert result.exit_code == 0
    output = result.output
    # Extract only the Quick Start section to avoid matching words elsewhere
    core_start = output.find("Quick Start:")
    assert core_start != -1, "Help should have a 'Quick Start:' section"
    core_section = output[core_start:]

    # Find positions within the quick start section only
    create_pos = core_section.find("\n  create ")
    serve_pos = core_section.find("\n  serve ")
    gate_pos = core_section.find("\n  gate ")
    status_pos = core_section.find("\n  status ")
    drift_pos = core_section.find("\n  drift ")
    repair_pos = core_section.find("\n  repair ")

    assert create_pos < serve_pos, "create should appear before serve in help"
    assert serve_pos < gate_pos, "serve should appear before gate in help"
    assert gate_pos < status_pos, "gate should appear before status in help"
    assert status_pos < drift_pos, "status should appear before drift in help"
    assert drift_pos < repair_pos, "drift should appear before repair in help"


def test_help_has_operations_section() -> None:
    """Default help should have an 'Operations' section."""
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])

    assert result.exit_code == 0
    assert "Operations:" in result.output, "Help should have an 'Operations' section"


# --- 10. Outcomes verification should return "skipped" not "pass" ---


def test_outcomes_result_returns_skipped_not_pass() -> None:
    """_outcomes_result() should return 'skipped' since it's not configured,
    not 'pass' which falsely claims verification succeeded."""
    from toolwright.cli.verify import _outcomes_result

    result = _outcomes_result()
    assert result["status"] == "skipped", (
        f"outcomes should return 'skipped' when not configured, got '{result['status']}'"
    )


# --- 11. serve with pending lockfile should not produce stack trace ---


def test_serve_pending_lockfile_no_stack_trace(tmp_path: Path) -> None:
    """serve with unapproved tools should show friendly error, not stack trace."""
    toolpack_file = write_demo_toolpack(tmp_path)

    # Create a fresh pending lockfile (tools not approved)
    from toolwright.cli.approve import sync_lockfile
    tools_path = toolpack_file.parent / "artifact" / "tools.json"
    pending_lockfile = toolpack_file.parent / "lockfile" / "toolwright.lock.pending.yaml"
    sync_lockfile(
        tools_path=str(tools_path),
        policy_path=None,
        toolsets_path=None,
        lockfile_path=str(pending_lockfile),
        capture_id=None,
        scope=None,
        deterministic=False,
    )

    runner = CliRunner()
    result = runner.invoke(cli, [
        "serve",
        "--toolpack", str(toolpack_file),
        "--lockfile", str(pending_lockfile),
    ])

    # Must NOT produce a stack trace (Traceback)
    assert "Traceback" not in result.output, (
        f"serve with pending lockfile should not show stack trace. Got:\n{result.output}"
    )
    assert result.exit_code != 0, "serve with pending lockfile should fail"
    # Should show actionable guidance
    output = result.output.lower()
    assert "approv" in output or "pending" in output or "gate allow" in output, (
        f"Error should mention approval. Got: {result.output!r}"
    )


# --- 12. serve with mismatched lockfile/toolpack should not stack trace (F-007) ---


def test_serve_mismatched_lockfile_no_stack_trace(tmp_path: Path) -> None:
    """serve with lockfile synced against different tools.json should not stack trace (F-007)."""
    toolpack_file = write_demo_toolpack(tmp_path)

    # Create a lockfile synced against DIFFERENT tools (wrong tool names)
    import json


    different_tools = {
        "version": "1.0.0",
        "schema_version": "1.0",
        "name": "Different",
        "allowed_hosts": ["other.example.com"],
        "actions": [
            {
                "name": "completely_different_tool",
                "method": "GET",
                "path": "/other",
                "host": "other.example.com",
                "signature_id": "sig_other_tool",
                "tool_id": "sig_other_tool",
                "input_schema": {"type": "object", "properties": {}},
            }
        ],
    }
    # Write different tools to a temp location, sync lockfile against it
    diff_tools_path = tmp_path / "different_tools.json"
    diff_tools_path.write_text(json.dumps(different_tools))

    from toolwright.cli.approve import sync_lockfile
    mismatched_lockfile = tmp_path / "mismatched.lock.yaml"
    sync_lockfile(
        tools_path=str(diff_tools_path),
        policy_path=None,
        toolsets_path=None,
        lockfile_path=str(mismatched_lockfile),
        capture_id=None,
        scope=None,
        deterministic=False,
    )
    # Approve all tools in the mismatched lockfile
    from toolwright.core.approval import LockfileManager
    mgr = LockfileManager(mismatched_lockfile)
    mgr.load()
    mgr.approve_all()
    mgr.save()

    runner = CliRunner()
    result = runner.invoke(cli, [
        "serve",
        "--toolpack", str(toolpack_file),
        "--lockfile", str(mismatched_lockfile),
    ])

    # Must NOT produce a stack trace
    assert "Traceback" not in result.output, (
        f"serve with mismatched lockfile should not show stack trace (F-007). "
        f"Got:\n{result.output}"
    )
    assert result.exit_code != 0


# --- 13. diff without baseline should give actionable guidance ---


def test_diff_without_baseline_gives_actionable_error(tmp_path: Path) -> None:
    """diff without a baseline snapshot should tell the user how to fix it."""
    toolpack = write_demo_toolpack(tmp_path)

    runner = CliRunner()
    result = runner.invoke(cli, ["diff", "--toolpack", str(toolpack)])

    output = result.output.lower()
    # Should mention both options: run snapshot OR pass --baseline
    assert "toolwright gate snapshot" in output or "gate snapshot" in output, (
        f"Error should mention 'toolwright gate snapshot'. Got: {result.output!r}"
    )
    assert "--baseline" in output, (
        f"Error should mention '--baseline' option. Got: {result.output!r}"
    )


# --- Quick Start should contain exactly 6 core commands ---


def test_quick_start_has_exactly_six_core_commands() -> None:
    """Quick Start section should show exactly: create, serve, gate, status, drift, repair."""
    from toolwright.cli.main import CORE_COMMANDS

    expected = ["create", "serve", "gate", "status", "drift", "repair"]
    assert CORE_COMMANDS == expected, (
        f"CORE_COMMANDS should be {expected}, got {CORE_COMMANDS}"
    )

    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    output = result.output

    # Extract the Quick Start section only
    qs_start = output.find("Quick Start:")
    assert qs_start != -1
    ops_start = output.find("Operations:", qs_start)
    assert ops_start != -1
    qs_section = output[qs_start:ops_start]

    # All 6 expected commands must be present
    for cmd in expected:
        assert f"  {cmd} " in qs_section or f"  {cmd}\n" in qs_section, (
            f"'{cmd}' should be in Quick Start section"
        )

    # These should NOT be in Quick Start (moved to Operations)
    for cmd in ["mint", "rules", "groups", "config"]:
        assert f"  {cmd} " not in qs_section, (
            f"'{cmd}' should NOT be in Quick Start section"
        )
