"""Tests for the ``toolwright why`` command and explanation engine."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from tests.helpers import write_demo_toolpack
from toolwright.cli.main import cli
from toolwright.core.approval.lockfile import LockfileManager
from toolwright.core.why import Explanation, explain_tool


class TestWhyEngineApproved:
    """Test why engine with an approved tool."""

    def test_approved_tool_returns_approved_status(self, tmp_path: Path) -> None:
        toolpack_file = write_demo_toolpack(tmp_path)
        # Approve the tool
        lockfile_dir = toolpack_file.parent / "lockfile"
        pending_lockfile = lockfile_dir / "toolwright.lock.pending.yaml"
        manager = LockfileManager(pending_lockfile)
        manager.load()
        manager.approve("get_users", approved_by="test-user", reason="safe read-only")
        manager.save()

        result = explain_tool(
            tool_name="get_users",
            toolpack_path=toolpack_file,
            root=tmp_path,
        )

        assert isinstance(result, Explanation)
        assert result.status == "approved"
        assert result.tool_name == "get_users"
        assert any("approved" in r.lower() for r in result.reasons)

    def test_approved_tool_has_timeline(self, tmp_path: Path) -> None:
        toolpack_file = write_demo_toolpack(tmp_path)
        lockfile_dir = toolpack_file.parent / "lockfile"
        pending_lockfile = lockfile_dir / "toolwright.lock.pending.yaml"
        manager = LockfileManager(pending_lockfile)
        manager.load()
        manager.approve("get_users", approved_by="test-user")
        manager.save()

        result = explain_tool(
            tool_name="get_users",
            toolpack_path=toolpack_file,
            root=tmp_path,
        )

        assert len(result.timeline) > 0
        assert any("found in tools manifest" in t for t in result.timeline)


class TestWhyEnginePending:
    """Test why engine with a pending tool."""

    def test_pending_tool_returns_pending_status(self, tmp_path: Path) -> None:
        toolpack_file = write_demo_toolpack(tmp_path)

        result = explain_tool(
            tool_name="get_users",
            toolpack_path=toolpack_file,
            root=tmp_path,
        )

        assert result.status == "pending"
        assert any("awaiting" in r.lower() or "pending" in r.lower() for r in result.reasons)

    def test_pending_tool_suggests_next_steps(self, tmp_path: Path) -> None:
        toolpack_file = write_demo_toolpack(tmp_path)

        result = explain_tool(
            tool_name="get_users",
            toolpack_path=toolpack_file,
            root=tmp_path,
        )

        assert len(result.next_steps) > 0
        assert any("gate" in s.lower() or "allow" in s.lower() for s in result.next_steps)


class TestWhyEngineUnknown:
    """Test why engine with unknown tool (not in manifest)."""

    def test_unknown_tool_returns_unknown_status(self, tmp_path: Path) -> None:
        toolpack_file = write_demo_toolpack(tmp_path)

        result = explain_tool(
            tool_name="nonexistent_tool",
            toolpack_path=toolpack_file,
            root=tmp_path,
        )

        assert result.status == "unknown"
        assert any("not found" in r.lower() for r in result.reasons)

    def test_unknown_tool_suggests_available_tools(self, tmp_path: Path) -> None:
        toolpack_file = write_demo_toolpack(tmp_path)

        result = explain_tool(
            tool_name="nonexistent_tool",
            toolpack_path=toolpack_file,
            root=tmp_path,
        )

        assert len(result.next_steps) > 0


class TestWhyCLI:
    """Test the why CLI command output."""

    def test_why_plain_output(self, tmp_path: Path) -> None:
        toolpack_file = write_demo_toolpack(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["--root", str(tmp_path), "why", "get_users", "--toolpack", str(toolpack_file)],
        )
        assert result.exit_code == 0
        assert "get_users" in result.output
        assert "pending" in result.output.lower()

    def test_why_json_output(self, tmp_path: Path) -> None:
        toolpack_file = write_demo_toolpack(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "--root", str(tmp_path),
                "why", "get_users",
                "--toolpack", str(toolpack_file),
                "--json",
            ],
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["tool_name"] == "get_users"
        assert data["status"] == "pending"
        assert isinstance(data["reasons"], list)
        assert isinstance(data["timeline"], list)
        assert isinstance(data["next_steps"], list)

    def test_why_unknown_tool_output(self, tmp_path: Path) -> None:
        toolpack_file = write_demo_toolpack(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["--root", str(tmp_path), "why", "bogus_tool", "--toolpack", str(toolpack_file)],
        )
        assert result.exit_code == 0
        assert "not found" in result.output.lower() or "unknown" in result.output.lower()
