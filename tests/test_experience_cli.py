"""Tests for the unified experience command surface (`demo`, core commands)."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from toolwright.cli.main import cli


def test_top_help_includes_core_commands() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "demo" in result.stdout
    assert "init" in result.stdout
    assert "mint" in result.stdout
    assert "gate" in result.stdout
    assert "serve" in result.stdout
    assert "run" in result.stdout
    assert "drift" in result.stdout
    assert "verify" in result.stdout


def test_demo_offline_emits_required_artifacts(tmp_path: Path) -> None:
    runner = CliRunner()
    out_dir = tmp_path / "demo_offline"
    result = runner.invoke(cli, ["demo", "--out", str(out_dir)])

    assert result.exit_code == 0
    report = out_dir / "prove_twice_report.md"
    diff_json = out_dir / "prove_twice_diff.json"
    summary_json = out_dir / "prove_summary.json"

    assert report.exists()
    assert diff_json.exists()
    assert summary_json.exists()

    summary = json.loads(summary_json.read_text(encoding="utf-8"))
    assert summary["schema_version"] == "1.0.0"
    assert summary["scenario"] == "offline_fixture"
    assert summary["govern_enforced"] is True
    assert summary["parity_ok"] is True
    assert summary["run_a_ok"] is True
    assert summary["run_b_ok"] is True
    assert summary["drift_count"] >= 0
    assert set(summary) >= {
        "schema_version",
        "scenario",
        "govern_enforced",
        "run_a_ok",
        "run_b_ok",
        "parity_ok",
        "drift_count",
        "report_path",
        "diff_path",
    }


def test_demo_fails_when_governance_check_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "toolwright.cli.wow._check_fail_closed_without_lockfile",
        lambda **_kwargs: False,
    )
    runner = CliRunner()
    out_dir = tmp_path / "demo_govern_fail"
    result = runner.invoke(cli, ["demo", "--out", str(out_dir)])
    assert result.exit_code == 1


def test_demo_fails_when_parity_breaks(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "toolwright.cli.wow._results_are_parity_equivalent",
        lambda _run_a, _run_b: False,
    )
    runner = CliRunner()
    out_dir = tmp_path / "demo_parity_fail"
    result = runner.invoke(cli, ["demo", "--out", str(out_dir)])
    assert result.exit_code == 1
