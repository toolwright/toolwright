"""Tests for repair CLI command — help text, exit codes, artifact paths, flags."""

from __future__ import annotations

import json
from pathlib import Path

import yaml
from click.testing import CliRunner

from toolwright.cli.main import CORE_COMMANDS, cli

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_minimal_toolpack(path: Path) -> Path:
    """Write a minimal toolpack.yaml and supporting artifacts."""
    tp_dir = path / "toolpacks" / "tp_test"
    tp_dir.mkdir(parents=True, exist_ok=True)
    artifact_dir = tp_dir / "artifact"
    artifact_dir.mkdir(exist_ok=True)
    lockfile_dir = tp_dir / "lockfile"
    lockfile_dir.mkdir(exist_ok=True)

    # tools.json
    tools = {"actions": [{"name": "get_users", "method": "GET", "path": "/users"}]}
    (artifact_dir / "tools.json").write_text(json.dumps(tools))

    # toolsets.yaml
    (artifact_dir / "toolsets.yaml").write_text(
        yaml.safe_dump({"toolsets": [{"name": "default", "tools": ["get_users"]}]})
    )

    # policy.yaml
    (artifact_dir / "policy.yaml").write_text(
        yaml.safe_dump({"version": "1.0", "rules": []})
    )

    # baseline.json
    (artifact_dir / "baseline.json").write_text(json.dumps({"endpoints": []}))

    # contracts
    (artifact_dir / "contracts.yaml").write_text(yaml.safe_dump({"contracts": []}))

    # pending lockfile
    (lockfile_dir / "toolwright.lock.pending.yaml").write_text(
        yaml.safe_dump({"version": "1.0.0", "tools": {}})
    )

    # toolpack.yaml
    toolpack = {
        "version": "1.0.0",
        "schema_version": "1.0",
        "toolpack_id": "tp_test",
        "created_at": "2026-02-20T00:00:00Z",
        "capture_id": "cap_test",
        "artifact_id": "art_test",
        "scope": "test",
        "allowed_hosts": ["api.example.com"],
        "origin": {"start_url": "https://api.example.com", "name": "Test"},
        "paths": {
            "tools": "artifact/tools.json",
            "toolsets": "artifact/toolsets.yaml",
            "policy": "artifact/policy.yaml",
            "baseline": "artifact/baseline.json",
            "contracts": "artifact/contracts.yaml",
            "lockfiles": {
                "pending": "lockfile/toolwright.lock.pending.yaml",
            },
        },
    }
    tp_file = tp_dir / "toolpack.yaml"
    tp_file.write_text(yaml.safe_dump(toolpack, sort_keys=False))
    return tp_file


def _write_audit_log(path: Path, entries: list[dict]) -> Path:
    """Write synthetic audit.log.jsonl."""
    out = path / "audit.log.jsonl"
    with out.open("w") as f:
        for entry in entries:
            f.write(json.dumps(entry, sort_keys=True) + "\n")
    return out


def _deny_entry(reason_code: str, tool_id: str = "get_users") -> dict:
    return {
        "timestamp": "2026-02-20T00:00:00Z",
        "run_id": "test_run",
        "tool_id": tool_id,
        "scope_id": "test_scope",
        "decision": "deny",
        "reason_code": reason_code,
        "evidence_refs": [],
        "lockfile_digest": "abc123",
        "policy_digest": "def456",
    }


# ===========================================================================
# 1. Help text (2 tests)
# ===========================================================================


class TestRepairHelp:
    """Tests for repair command help and visibility."""

    def test_repair_visible_in_core_commands(self) -> None:
        """repair appears in CORE_COMMANDS after drift."""
        assert "repair" in CORE_COMMANDS
        drift_idx = CORE_COMMANDS.index("drift")
        repair_idx = CORE_COMMANDS.index("repair")
        assert repair_idx == drift_idx + 1, (
            f"repair should appear right after drift, but drift={drift_idx}, repair={repair_idx}"
        )

    def test_repair_help_shows_examples(self) -> None:
        """'toolwright repair --help' includes usage examples."""
        runner = CliRunner()
        result = runner.invoke(cli, ["repair", "--help"])

        assert result.exit_code == 0
        assert "--toolpack" in result.output
        assert "Examples:" in result.output

    def test_repair_help_shows_from_flag(self) -> None:
        """'toolwright repair --help' shows the --from flag."""
        runner = CliRunner()
        result = runner.invoke(cli, ["repair", "--help"])

        assert result.exit_code == 0
        assert "--from" in result.output

    def test_repair_help_shows_auto_discover_flag(self) -> None:
        """'toolwright repair --help' shows --auto-discover/--no-auto-discover."""
        runner = CliRunner()
        result = runner.invoke(cli, ["repair", "--help"])

        assert result.exit_code == 0
        assert "--auto-discover" in result.output
        assert "--no-auto-discover" in result.output


# ===========================================================================
# 2. Exit codes (3 tests)
# ===========================================================================


class TestRepairExitCodes:
    """Tests for CLI exit codes."""

    def test_healthy_toolpack_exits_0(self, tmp_path: Path) -> None:
        """No context files, healthy system → exit 0."""
        tp = _write_minimal_toolpack(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["repair", "--toolpack", str(tp), "--no-auto-discover"],
        )

        assert result.exit_code == 0

    def test_issues_found_exits_1(self, tmp_path: Path) -> None:
        """Audit log with deny entries → exit 1."""
        tp = _write_minimal_toolpack(tmp_path)
        audit = _write_audit_log(tmp_path, [_deny_entry("denied_not_approved")])

        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "repair",
                "--toolpack", str(tp),
                "--from", str(audit),
                "--no-auto-discover",
            ],
        )

        assert result.exit_code == 1

    def test_invalid_toolpack_exits_2(self, tmp_path: Path) -> None:
        """Non-existent toolpack → exit 2."""
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["repair", "--toolpack", str(tmp_path / "nope.yaml")],
        )

        assert result.exit_code == 2


# ===========================================================================
# 3. Output artifacts (3 tests)
# ===========================================================================


class TestRepairOutputs:
    """Tests for repair output artifacts."""

    def test_repair_json_written(self, tmp_path: Path) -> None:
        """repair.json is written to output directory."""
        tp = _write_minimal_toolpack(tmp_path)
        audit = _write_audit_log(tmp_path, [_deny_entry("denied_not_approved")])
        out = tmp_path / "repair_out"

        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "repair",
                "--toolpack", str(tp),
                "--from", str(audit),
                "-o", str(out),
                "--no-auto-discover",
            ],
        )

        assert result.exit_code == 1
        # Find repair.json in output
        repair_json_files = list(out.rglob("repair.json"))
        assert len(repair_json_files) >= 1
        data = json.loads(repair_json_files[0].read_text())
        assert data["repair_schema_version"] == "0.1"

    def test_repair_md_written(self, tmp_path: Path) -> None:
        """repair.md is written to output directory."""
        tp = _write_minimal_toolpack(tmp_path)
        audit = _write_audit_log(tmp_path, [_deny_entry("denied_not_approved")])
        out = tmp_path / "repair_out"

        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "repair",
                "--toolpack", str(tp),
                "--from", str(audit),
                "-o", str(out),
                "--no-auto-discover",
            ],
        )

        assert result.exit_code == 1
        md_files = list(out.rglob("repair.md"))
        assert len(md_files) >= 1

    def test_commands_sh_written(self, tmp_path: Path) -> None:
        """patch.commands.sh is written to output directory."""
        tp = _write_minimal_toolpack(tmp_path)
        audit = _write_audit_log(tmp_path, [_deny_entry("denied_not_approved")])
        out = tmp_path / "repair_out"

        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "repair",
                "--toolpack", str(tp),
                "--from", str(audit),
                "-o", str(out),
                "--no-auto-discover",
            ],
        )

        assert result.exit_code == 1
        sh_files = list(out.rglob("patch.commands.sh"))
        assert len(sh_files) >= 1


# ===========================================================================
# 4. Flag behavior (2 tests)
# ===========================================================================


class TestRepairFlags:
    """Tests for --from and --no-auto-discover flags."""

    def test_from_flag_accepts_multiple(self, tmp_path: Path) -> None:
        """--from can be specified multiple times."""
        tp = _write_minimal_toolpack(tmp_path)
        (tmp_path / "ctx1").mkdir(exist_ok=True)
        audit1 = _write_audit_log(
            tmp_path / "ctx1",
            [_deny_entry("denied_not_approved")],
        )
        (tmp_path / "ctx2").mkdir(exist_ok=True)
        audit2 = _write_audit_log(
            tmp_path / "ctx2",
            [_deny_entry("denied_policy", tool_id="create_user")],
        )

        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "repair",
                "--toolpack", str(tp),
                "--from", str(audit1),
                "--from", str(audit2),
                "--no-auto-discover",
            ],
        )

        # Both deny entries should be found → exit 1
        assert result.exit_code == 1

    def test_no_auto_discover_prevents_discovery(self, tmp_path: Path) -> None:
        """--no-auto-discover prevents searching near toolpack."""
        tp = _write_minimal_toolpack(tmp_path)
        # Place an audit log next to toolpack
        tp_dir = tp.parent
        _write_audit_log(tp_dir, [_deny_entry("denied_policy")])

        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["repair", "--toolpack", str(tp), "--no-auto-discover"],
        )

        # With --no-auto-discover and no --from, should be healthy
        assert result.exit_code == 0
