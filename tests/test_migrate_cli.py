"""Tests for migrate command and contract artifact upgrades."""

from __future__ import annotations

from pathlib import Path

import yaml
from click.testing import CliRunner

from toolwright.cli.main import cli
from tests.helpers import write_demo_toolpack


def _make_legacy_toolpack(toolpack_path: Path) -> None:
    payload = yaml.safe_load(toolpack_path.read_text(encoding="utf-8"))
    paths = payload["paths"]
    paths.pop("contracts", None)
    toolpack_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    contracts_path = toolpack_path.parent / "artifact" / "contracts.yaml"
    contracts_path.unlink(missing_ok=True)



def test_migrate_dry_run_reports_changes(tmp_path: Path) -> None:
    toolpack_path = write_demo_toolpack(tmp_path)
    _make_legacy_toolpack(toolpack_path)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "migrate",
            "--toolpack",
            str(toolpack_path),
            "--dry-run",
        ],
    )

    assert result.exit_code == 0
    assert "Dry run" in result.output
    assert "paths.contracts" in result.output



def test_migrate_apply_writes_contracts_and_updates_toolpack(tmp_path: Path) -> None:
    toolpack_path = write_demo_toolpack(tmp_path)
    _make_legacy_toolpack(toolpack_path)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "migrate",
            "--toolpack",
            str(toolpack_path),
            "--apply",
        ],
    )

    assert result.exit_code == 0
    payload = yaml.safe_load(toolpack_path.read_text(encoding="utf-8"))
    assert payload["paths"]["contracts"] == "artifact/contracts.yaml"
    assert (toolpack_path.parent / "artifact" / "contracts.yaml").exists()
