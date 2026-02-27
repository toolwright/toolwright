"""Tests for toolwright workflow CLI commands."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from toolwright.cli.main import cli

# ---------------------------------------------------------------------------
# workflow init
# ---------------------------------------------------------------------------


def test_workflow_init_creates_file(tmp_path: Path) -> None:
    """workflow init creates a starter YAML at the given path."""
    target = tmp_path / "my-workflow.yaml"
    runner = CliRunner()
    result = runner.invoke(cli, ["workflow", "init", str(target)])

    assert result.exit_code == 0
    assert target.exists()
    assert f"Wrote {target}" in result.output


def test_workflow_init_creates_valid_yaml_with_version(tmp_path: Path) -> None:
    """The generated starter file is valid YAML containing a version key."""
    target = tmp_path / "starter.yaml"
    runner = CliRunner()
    result = runner.invoke(cli, ["workflow", "init", str(target)])

    assert result.exit_code == 0
    data = yaml.safe_load(target.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    assert "version" in data
    assert data["version"] == 1


def test_workflow_init_refuses_overwrite(tmp_path: Path) -> None:
    """workflow init exits non-zero and prints 'already exists' when the file exists."""
    target = tmp_path / "existing.yaml"
    target.write_text("placeholder", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(cli, ["workflow", "init", str(target)])

    assert result.exit_code != 0
    assert "already exists" in result.output or "already exists" in (result.stderr or "")


def test_workflow_init_default_path(tmp_path: Path) -> None:
    """workflow init without a path argument defaults to tide.yaml in cwd."""
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        result = runner.invoke(cli, ["workflow", "init"])
        assert result.exit_code == 0
        assert Path(td, "tide.yaml").exists()


def test_workflow_init_creates_parent_dirs(tmp_path: Path) -> None:
    """workflow init creates parent directories if they do not exist."""
    target = tmp_path / "nested" / "deep" / "workflow.yaml"
    runner = CliRunner()
    result = runner.invoke(cli, ["workflow", "init", str(target)])

    assert result.exit_code == 0
    assert target.exists()


# ---------------------------------------------------------------------------
# workflow doctor
# ---------------------------------------------------------------------------


def test_workflow_doctor_exits_zero() -> None:
    """workflow doctor always exits 0 (it just reports dependency status)."""
    runner = CliRunner()
    result = runner.invoke(cli, ["workflow", "doctor"])

    assert result.exit_code == 0


def test_workflow_doctor_reports_playwright_status() -> None:
    """workflow doctor output includes a Playwright status line."""
    runner = CliRunner()
    result = runner.invoke(cli, ["workflow", "doctor"])

    assert "Playwright:" in result.output


def test_workflow_doctor_reports_mcp_sdk_status() -> None:
    """workflow doctor output includes an MCP SDK status line."""
    runner = CliRunner()
    result = runner.invoke(cli, ["workflow", "doctor"])

    assert "MCP SDK:" in result.output


def test_workflow_doctor_reports_tide_status() -> None:
    """workflow doctor output includes a Tide status line."""
    runner = CliRunner()
    result = runner.invoke(cli, ["workflow", "doctor"])

    assert "Tide:" in result.output


# ---------------------------------------------------------------------------
# workflow diff
# ---------------------------------------------------------------------------


def _make_run_dir(base: Path, name: str, run_data: dict) -> Path:
    """Create a minimal run directory with a run.json."""
    run_dir = base / name
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run.json").write_text(
        json.dumps(run_data), encoding="utf-8"
    )
    return run_dir


def test_workflow_diff_json_output(tmp_path: Path) -> None:
    """workflow diff --format json produces parseable JSON with expected keys."""
    run_a = _make_run_dir(tmp_path, "run_a", {
        "run_id": "a",
        "workflow_name": "test",
        "ok": True,
        "results": [],
    })
    run_b = _make_run_dir(tmp_path, "run_b", {
        "run_id": "b",
        "workflow_name": "test",
        "ok": False,
        "results": [],
    })

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["workflow", "diff", str(run_a), str(run_b), "--format", "json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert "run_a" in payload
    assert "run_b" in payload
    assert "workflow_changed" in payload
    assert "overall_status_changed" in payload
    assert "step_diffs" in payload


def test_workflow_diff_detects_status_change(tmp_path: Path) -> None:
    """diff reports overall_status_changed when ok differs between runs."""
    run_a = _make_run_dir(tmp_path, "run_a", {
        "run_id": "a",
        "workflow_name": "test",
        "ok": True,
        "results": [],
    })
    run_b = _make_run_dir(tmp_path, "run_b", {
        "run_id": "b",
        "workflow_name": "test",
        "ok": False,
        "results": [],
    })

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["workflow", "diff", str(run_a), str(run_b), "--format", "json"],
    )

    payload = json.loads(result.output)
    assert payload["overall_status_changed"] is True


def test_workflow_diff_detects_workflow_change(tmp_path: Path) -> None:
    """diff reports workflow_changed when workflow names differ."""
    run_a = _make_run_dir(tmp_path, "run_a", {
        "run_id": "a",
        "workflow_name": "alpha",
        "ok": True,
        "results": [],
    })
    run_b = _make_run_dir(tmp_path, "run_b", {
        "run_id": "b",
        "workflow_name": "beta",
        "ok": True,
        "results": [],
    })

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["workflow", "diff", str(run_a), str(run_b), "--format", "json"],
    )

    payload = json.loads(result.output)
    assert payload["workflow_changed"] is True


def test_workflow_diff_includes_step_diffs(tmp_path: Path) -> None:
    """diff reports per-step differences when results contain steps."""
    run_a = _make_run_dir(tmp_path, "run_a", {
        "run_id": "a",
        "workflow_name": "test",
        "ok": True,
        "results": [
            {"step_id": "s1", "ok": True, "type": "shell", "artifacts": []},
        ],
    })
    run_b = _make_run_dir(tmp_path, "run_b", {
        "run_id": "b",
        "workflow_name": "test",
        "ok": False,
        "results": [
            {"step_id": "s1", "ok": False, "type": "shell", "artifacts": ["a.log"]},
        ],
    })

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["workflow", "diff", str(run_a), str(run_b), "--format", "json"],
    )

    payload = json.loads(result.output)
    assert len(payload["step_diffs"]) == 1
    step = payload["step_diffs"][0]
    assert step["step_id"] == "s1"
    assert step["status_a"] == "pass"
    assert step["status_b"] == "fail"
    assert step["artifact_count_a"] == 0
    assert step["artifact_count_b"] == 1


def test_workflow_diff_github_md_format(tmp_path: Path) -> None:
    """diff default format (github-md) produces markdown with a header."""
    run_a = _make_run_dir(tmp_path, "run_a", {
        "run_id": "a",
        "workflow_name": "test",
        "ok": True,
        "results": [],
    })
    run_b = _make_run_dir(tmp_path, "run_b", {
        "run_id": "b",
        "workflow_name": "test",
        "ok": True,
        "results": [],
    })

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["workflow", "diff", str(run_a), str(run_b)],
    )

    assert result.exit_code == 0
    assert "# Tide Run Diff" in result.output


def test_workflow_diff_missing_run_json(tmp_path: Path) -> None:
    """diff exits non-zero when run.json is missing from a run directory."""
    run_a = tmp_path / "run_a"
    run_a.mkdir()
    # no run.json inside run_a
    run_b = _make_run_dir(tmp_path, "run_b", {
        "run_id": "b",
        "workflow_name": "test",
        "ok": True,
        "results": [],
    })

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["workflow", "diff", str(run_a), str(run_b), "--format", "json"],
    )

    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# workflow pack
# ---------------------------------------------------------------------------


def test_workflow_pack_creates_zip(tmp_path: Path) -> None:
    """workflow pack creates a zip file from a run directory."""
    run_dir = _make_run_dir(tmp_path, "run_pack", {
        "run_id": "pack-test",
        "workflow_name": "test",
        "ok": True,
        "results": [],
    })

    runner = CliRunner()
    result = runner.invoke(cli, ["workflow", "pack", str(run_dir)])

    assert result.exit_code == 0
    # Default output is run_dir.parent / f"{run_dir.name}.zip"
    expected_zip = run_dir.parent / f"{run_dir.name}.zip"
    assert expected_zip.exists()
    assert str(expected_zip) in result.output


def test_workflow_pack_zip_contains_run_json(tmp_path: Path) -> None:
    """The pack zip contains run.json from the run directory."""
    run_dir = _make_run_dir(tmp_path, "run_pack2", {
        "run_id": "pack2",
        "workflow_name": "test",
        "ok": True,
        "results": [],
    })

    runner = CliRunner()
    result = runner.invoke(cli, ["workflow", "pack", str(run_dir)])

    assert result.exit_code == 0
    expected_zip = run_dir.parent / f"{run_dir.name}.zip"
    with zipfile.ZipFile(expected_zip, "r") as zf:
        assert "run.json" in zf.namelist()


def test_workflow_pack_custom_output(tmp_path: Path) -> None:
    """workflow pack --out writes the zip to the specified path."""
    run_dir = _make_run_dir(tmp_path, "run_custom", {
        "run_id": "custom",
        "workflow_name": "test",
        "ok": True,
        "results": [],
    })
    out_path = tmp_path / "output" / "custom-bundle.zip"

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["workflow", "pack", str(run_dir), "--out", str(out_path)],
    )

    assert result.exit_code == 0
    assert out_path.exists()
    assert str(out_path) in result.output


def test_workflow_pack_includes_nested_files(tmp_path: Path) -> None:
    """workflow pack includes files in subdirectories."""
    run_dir = _make_run_dir(tmp_path, "run_nested", {
        "run_id": "nested",
        "workflow_name": "test",
        "ok": True,
        "results": [],
    })
    artifacts = run_dir / "artifacts"
    artifacts.mkdir()
    (artifacts / "screenshot.png").write_bytes(b"fake-png")

    runner = CliRunner()
    result = runner.invoke(cli, ["workflow", "pack", str(run_dir)])

    assert result.exit_code == 0
    expected_zip = run_dir.parent / f"{run_dir.name}.zip"
    with zipfile.ZipFile(expected_zip, "r") as zf:
        names = zf.namelist()
        assert "run.json" in names
        assert "artifacts/screenshot.png" in names


# ---------------------------------------------------------------------------
# workflow run (tide-not-installed error case)
# ---------------------------------------------------------------------------


def test_workflow_run_errors_without_tide(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """workflow run exits non-zero with a helpful message when tide is not installed."""
    import builtins

    real_import = builtins.__import__

    def _block_tide(name: str, *args: object, **kwargs: object) -> object:
        if name == "tide" or name.startswith("tide."):
            raise ImportError("mocked: tide not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _block_tide)

    # Create a dummy workflow file so Click's exists=True check passes.
    wf = tmp_path / "tide.yaml"
    wf.write_text("version: 1\nname: test\nsteps: []\n", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(cli, ["workflow", "run", str(wf)])

    # _require_tide calls sys.exit(1) when tide is not importable.
    assert result.exit_code != 0
    assert "tide" in (result.output + (result.stderr or "")).lower()
