"""CLI tests for `toolwright inspect` dependency gating."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from toolwright.cli.main import cli


def test_inspect_missing_mcp_exact_error(tmp_path: Path, monkeypatch) -> None:
    tools_path = tmp_path / "tools.json"
    tools_path.write_text(json.dumps({"version": "1.0.0", "schema_version": "1.0", "actions": []}))

    runner = CliRunner()
    monkeypatch.setattr("importlib.util.find_spec", lambda _name: None)
    monkeypatch.setattr("toolwright.mcp.meta_server.run_meta_server", lambda **_kwargs: None)

    result = runner.invoke(cli, ["inspect", "--tools", str(tools_path)])

    assert result.exit_code != 0
    assert result.stdout == ""
    assert (
        result.stderr
        == 'Error: mcp not installed. Install with: pip install "toolwright[mcp]"\n'
    )
