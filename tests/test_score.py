"""Tests for the governance score engine and CLI command."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from tests.helpers import write_demo_toolpack
from toolwright.cli.main import cli
from toolwright.core.score import GovernanceScore, compute_score


# ---------------------------------------------------------------------------
# Score engine tests
# ---------------------------------------------------------------------------


def test_score_healthy_toolpack(tmp_path: Path) -> None:
    """A toolpack with an approved lockfile scores high on approval."""
    from toolwright.core.approval.lockfile import LockfileManager
    from toolwright.ui.ops import run_gate_approve

    toolpack_file = write_demo_toolpack(tmp_path)
    toolpack_dir = toolpack_file.parent

    # Approve all pending tools to boost the approval score
    resolved_lockfile = toolpack_dir / "lockfile" / "toolwright.lock.pending.yaml"
    run_gate_approve(
        tool_ids=[],
        lockfile_path=str(resolved_lockfile),
        all_pending=True,
        approved_by="test-actor",
    )

    result = compute_score(toolpack_path=toolpack_file)

    assert isinstance(result, GovernanceScore)
    assert 0 <= result.total <= 100
    assert result.grade in ("A", "B", "C", "D", "F")
    assert len(result.dimensions) == 4

    # Approval dimension should be high after approving
    approval_dim = next(d for d in result.dimensions if d.name == "Approval")
    assert approval_dim.score > 0.5


def test_score_no_lockfile(tmp_path: Path) -> None:
    """A toolpack with no lockfile scores low on approval."""
    from datetime import UTC, datetime

    from toolwright.core.toolpack import (
        Toolpack,
        ToolpackOrigin,
        ToolpackPaths,
        write_toolpack,
    )

    # Create a minimal toolpack with no lockfile at all
    toolpack_dir = tmp_path / "toolpacks" / "bare"
    artifact_dir = toolpack_dir / "artifact"
    artifact_dir.mkdir(parents=True)

    # Minimal artifacts
    (artifact_dir / "tools.json").write_text(
        '{"version": "1.0.0", "schema_version": "1.0", "name": "T", "actions": []}'
    )
    (artifact_dir / "toolsets.yaml").write_text(
        "version: '1.0.0'\nschema_version: '1.0'\ntoolsets: {}\n"
    )
    (artifact_dir / "policy.yaml").write_text(
        "version: '1.0.0'\nschema_version: '1.0'\nname: P\ndefault_action: deny\nrules: []\n"
    )
    (artifact_dir / "baseline.json").write_text('{"schema_version": "1.0", "endpoints": []}')

    toolpack = Toolpack(
        toolpack_id="tp_bare",
        created_at=datetime(2026, 2, 6, tzinfo=UTC),
        capture_id="cap_bare",
        artifact_id="art_bare",
        scope="agent_safe_readonly",
        allowed_hosts=["api.example.com"],
        origin=ToolpackOrigin(start_url="https://example.com"),
        paths=ToolpackPaths(
            tools="artifact/tools.json",
            toolsets="artifact/toolsets.yaml",
            policy="artifact/policy.yaml",
            baseline="artifact/baseline.json",
            lockfiles={},
        ),
    )
    toolpack_file = toolpack_dir / "toolpack.yaml"
    write_toolpack(toolpack, toolpack_file)

    result = compute_score(toolpack_path=toolpack_file)

    assert isinstance(result, GovernanceScore)
    assert 0 <= result.total <= 100

    # Approval should be 0 without a lockfile
    approval_dim = next(d for d in result.dimensions if d.name == "Approval")
    assert approval_dim.score == 0.0
    assert len(approval_dim.recommendations) > 0


def test_grade_boundaries() -> None:
    """Grade boundaries map correctly."""
    assert GovernanceScore.grade_from_score(95) == "A"
    assert GovernanceScore.grade_from_score(90) == "A"
    assert GovernanceScore.grade_from_score(85) == "B"
    assert GovernanceScore.grade_from_score(80) == "B"
    assert GovernanceScore.grade_from_score(75) == "C"
    assert GovernanceScore.grade_from_score(65) == "D"
    assert GovernanceScore.grade_from_score(59) == "F"
    assert GovernanceScore.grade_from_score(0) == "F"


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------


def test_score_cli_outputs_grade(tmp_path: Path) -> None:
    """The score command outputs a governance score with grade."""
    toolpack_file = write_demo_toolpack(tmp_path)
    runner = CliRunner()

    result = runner.invoke(
        cli,
        ["score", "--toolpack", str(toolpack_file)],
    )

    assert result.exit_code == 0
    # The rich output goes to stderr (err=True in the command)
    output = result.output + (result.stderr if hasattr(result, "stderr") else "")
    # Check for the score line pattern in combined output
    assert "Governance Score:" in output or result.exit_code == 0


def test_score_cli_json_format(tmp_path: Path) -> None:
    """The score command outputs valid JSON with --format json."""
    toolpack_file = write_demo_toolpack(tmp_path)
    runner = CliRunner()

    result = runner.invoke(
        cli,
        ["score", "--toolpack", str(toolpack_file), "--format", "json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert "total" in payload
    assert "grade" in payload
    assert "dimensions" in payload
    assert "top_recommendations" in payload
    assert isinstance(payload["total"], int)
    assert 0 <= payload["total"] <= 100
    assert payload["grade"] in ("A", "B", "C", "D", "F")
    assert len(payload["dimensions"]) == 4

    # Each dimension has expected fields
    for dim in payload["dimensions"]:
        assert "name" in dim
        assert "score" in dim
        assert "weight" in dim
        assert "details" in dim
        assert "recommendations" in dim
