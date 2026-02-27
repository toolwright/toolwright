"""Docs smoke tests for public onboarding contracts."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from toolwright.cli.main import cli

DOC_PATHS = [
    Path("README.md"),
    Path("docs/user-guide.md"),
]


def test_public_docs_do_not_leak_absolute_local_paths() -> None:
    for path in DOC_PATHS:
        text = path.read_text(encoding="utf-8")
        assert "/Users/" not in text
        assert "C:\\" not in text


def test_docs_onboarding_snippets_smoke(tmp_path: Path) -> None:
    runner = CliRunner()
    out_dir = tmp_path / "demo_docs_smoke"

    demo_result = runner.invoke(cli, ["demo", "--out", str(out_dir)])
    assert demo_result.exit_code == 0

    top_help = runner.invoke(cli, ["--help"])
    assert top_help.exit_code == 0

    gate_help = runner.invoke(cli, ["gate", "--help"])
    assert gate_help.exit_code == 0

    summary = json.loads((out_dir / "prove_summary.json").read_text(encoding="utf-8"))
    assert summary["schema_version"] == "1.0.0"
    assert summary["govern_enforced"] is True
    assert summary["parity_ok"] is True
