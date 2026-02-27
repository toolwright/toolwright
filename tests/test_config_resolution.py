"""Tests for config command path resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from toolwright.utils.config import build_mcp_config_payload


def test_build_mcp_config_payload_prefers_invoked_executable_over_path_lookup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When invoked via an absolute path, prefer that path for paste-and-go reliability.

    Claude Desktop often has a constrained PATH; additionally, multiple toolwright installs
    may exist (for example, a repo venv vs a pipx/standalone install). The config snippet
    should reflect the actual binary used to generate it when possible.
    """
    fake_exec = tmp_path / "bin" / "toolwright"
    fake_exec.parent.mkdir(parents=True)
    fake_exec.write_text("#!/bin/sh\nexit 0\n")
    fake_exec.chmod(0o755)

    toolpack = tmp_path / "toolpack.yaml"
    toolpack.write_text("toolpack_id: tp_test\n")

    monkeypatch.setattr("toolwright.utils.config.sys.argv", [str(fake_exec)])
    monkeypatch.setattr(
        "toolwright.utils.config.shutil.which",
        lambda _name: "/bad/path/toolwright",
    )

    payload = build_mcp_config_payload(toolpack_path=toolpack, server_name="tp_test")
    assert payload["mcpServers"]["tp_test"]["command"] == str(fake_exec.resolve())

