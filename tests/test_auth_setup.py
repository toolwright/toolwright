"""Tests for the interactive auth setup wizard."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import yaml

from toolwright.cli.auth_setup import auth_setup_flow


def _make_toolpack(tmp_path: Path, hosts: list[str]) -> Path:
    """Create a minimal toolpack.yaml with given allowed_hosts."""
    tp_dir = tmp_path / ".toolwright" / "toolpacks" / "test"
    tp_dir.mkdir(parents=True)
    tp_path = tp_dir / "toolpack.yaml"
    tp_path.write_text(
        yaml.safe_dump(
            {
                "version": "1.0.0",
                "schema_version": "1.0",
                "toolpack_id": "test-tp",
                "created_at": "2025-01-01T00:00:00",
                "capture_id": "cap-1",
                "artifact_id": "art-1",
                "scope": "test",
                "allowed_hosts": hosts,
                "display_name": "test-api",
                "origin": {"start_url": "https://example.com"},
                "paths": {
                    "tools": "tools.json",
                    "toolsets": "toolsets.yaml",
                    "policy": "policy.yaml",
                    "baseline": "baseline.yaml",
                },
            }
        )
    )
    (tp_dir / "tools.json").write_text(
        json.dumps({"actions": [], "allowed_hosts": hosts})
    )
    return tp_path


def test_all_hosts_configured_shows_complete(tmp_path: Path, capsys):
    tp_path = _make_toolpack(tmp_path, ["api.example.com"])
    env_var = "TOOLWRIGHT_AUTH_API_EXAMPLE_COM"
    with patch.dict(os.environ, {env_var: "Bearer tok123"}):
        auth_setup_flow(root=tmp_path, toolpack_path=str(tp_path), no_probe=True)
    captured = capsys.readouterr()
    assert "SET" in captured.out or "configured" in captured.out.lower()


def test_missing_auth_prompts_for_token(tmp_path: Path, capsys):
    tp_path = _make_toolpack(tmp_path, ["api.example.com"])
    with (
        patch.dict(os.environ, {}, clear=False),
        patch("toolwright.cli.auth_setup.sys") as mock_sys,
        patch("toolwright.cli.auth_setup.getpass.getpass", return_value="Bearer secret"),
        patch("toolwright.cli.auth_setup._probe_host", return_value=(200, "OK")),
    ):
        mock_sys.stdin.isatty.return_value = True
        os.environ.pop("TOOLWRIGHT_AUTH_API_EXAMPLE_COM", None)
        auth_setup_flow(root=tmp_path, toolpack_path=str(tp_path), no_probe=True)
    captured = capsys.readouterr()
    assert "NOT SET" in captured.out


def test_probe_success_shows_checkmark(tmp_path: Path, capsys):
    tp_path = _make_toolpack(tmp_path, ["api.example.com"])
    with (
        patch.dict(os.environ, {}, clear=False),
        patch("toolwright.cli.auth_setup.sys") as mock_sys,
        patch("toolwright.cli.auth_setup.getpass.getpass", return_value="Bearer secret"),
        patch("toolwright.cli.auth_setup._probe_host", return_value=(200, "OK")),
    ):
        mock_sys.stdin.isatty.return_value = True
        os.environ.pop("TOOLWRIGHT_AUTH_API_EXAMPLE_COM", None)
        auth_setup_flow(root=tmp_path, toolpack_path=str(tp_path), no_probe=False)
    captured = capsys.readouterr()
    assert "200" in captured.out


def test_probe_failure_shows_error(tmp_path: Path, capsys):
    tp_path = _make_toolpack(tmp_path, ["api.example.com"])
    with (
        patch.dict(os.environ, {}, clear=False),
        patch("toolwright.cli.auth_setup.sys") as mock_sys,
        patch("toolwright.cli.auth_setup.getpass.getpass", return_value="Bearer bad"),
        patch("toolwright.cli.auth_setup._probe_host", return_value=(401, "auth invalid")),
    ):
        mock_sys.stdin.isatty.return_value = True
        os.environ.pop("TOOLWRIGHT_AUTH_API_EXAMPLE_COM", None)
        auth_setup_flow(root=tmp_path, toolpack_path=str(tp_path), no_probe=False)
    captured = capsys.readouterr()
    assert "401" in captured.out


def test_dotenv_file_written(tmp_path: Path):
    tp_path = _make_toolpack(tmp_path, ["api.example.com"])
    env_path = tmp_path / ".toolwright" / ".env"
    with (
        patch.dict(os.environ, {}, clear=False),
        patch("toolwright.cli.auth_setup.sys") as mock_sys,
        patch("toolwright.cli.auth_setup.getpass.getpass", return_value="Bearer secret"),
        patch("toolwright.cli.auth_setup._probe_host", return_value=(200, "OK")),
    ):
        mock_sys.stdin.isatty.return_value = True
        os.environ.pop("TOOLWRIGHT_AUTH_API_EXAMPLE_COM", None)
        auth_setup_flow(root=tmp_path, toolpack_path=str(tp_path), no_probe=True)
    assert env_path.exists()
    content = env_path.read_text()
    assert "TOOLWRIGHT_AUTH_API_EXAMPLE_COM" in content
    assert "Bearer secret" in content


def test_non_interactive_no_prompts(tmp_path: Path, capsys):
    tp_path = _make_toolpack(tmp_path, ["api.example.com"])
    with (
        patch.dict(os.environ, {}, clear=False),
        patch("toolwright.cli.auth_setup.sys") as mock_sys,
    ):
        mock_sys.stdin.isatty.return_value = False
        os.environ.pop("TOOLWRIGHT_AUTH_API_EXAMPLE_COM", None)
        auth_setup_flow(root=tmp_path, toolpack_path=str(tp_path), no_probe=True)
    captured = capsys.readouterr()
    assert "NOT SET" in captured.out


def test_no_toolpack_shows_error(tmp_path: Path, capsys):
    root = tmp_path / ".toolwright"
    root.mkdir(parents=True)
    auth_setup_flow(root=root, toolpack_path=None, no_probe=True)
    captured = capsys.readouterr()
    assert (
        "error" in captured.out.lower()
        or "not found" in captured.out.lower()
        or "no toolpack" in captured.out.lower()
    )


def test_keyboard_interrupt_clean_exit(tmp_path: Path, capsys):
    tp_path = _make_toolpack(tmp_path, ["api.example.com"])
    with (
        patch.dict(os.environ, {}, clear=False),
        patch("toolwright.cli.auth_setup.sys") as mock_sys,
        patch("toolwright.cli.auth_setup.getpass.getpass", side_effect=KeyboardInterrupt),
    ):
        mock_sys.stdin.isatty.return_value = True
        os.environ.pop("TOOLWRIGHT_AUTH_API_EXAMPLE_COM", None)
        auth_setup_flow(root=tmp_path, toolpack_path=str(tp_path), no_probe=True)
    captured = capsys.readouterr()
    assert "abort" in captured.out.lower() or "cancel" in captured.out.lower()


def test_multiple_hosts_partial_config(tmp_path: Path, capsys):
    tp_path = _make_toolpack(tmp_path, ["api.example.com", "api.stripe.com"])
    with (
        patch.dict(os.environ, {"TOOLWRIGHT_AUTH_API_EXAMPLE_COM": "Bearer tok"}, clear=False),
        patch("toolwright.cli.auth_setup.sys") as mock_sys,
    ):
        mock_sys.stdin.isatty.return_value = False
        os.environ.pop("TOOLWRIGHT_AUTH_API_STRIPE_COM", None)
        auth_setup_flow(root=tmp_path, toolpack_path=str(tp_path), no_probe=True)
    captured = capsys.readouterr()
    assert "api.example.com" in captured.out
    assert "api.stripe.com" in captured.out


def test_no_hosts_in_toolpack(tmp_path: Path, capsys):
    tp_path = _make_toolpack(tmp_path, [])
    auth_setup_flow(root=tmp_path, toolpack_path=str(tp_path), no_probe=True)
    captured = capsys.readouterr()
    assert "no" in captured.out.lower() and "host" in captured.out.lower()


def test_gitignore_ensured(tmp_path: Path):
    tp_path = _make_toolpack(tmp_path, ["api.example.com"])
    gitignore = tmp_path / ".gitignore"
    with (
        patch.dict(os.environ, {}, clear=False),
        patch("toolwright.cli.auth_setup.sys") as mock_sys,
        patch("toolwright.cli.auth_setup.getpass.getpass", return_value="Bearer tok"),
        patch("toolwright.cli.auth_setup._probe_host", return_value=(200, "OK")),
    ):
        mock_sys.stdin.isatty.return_value = True
        os.environ.pop("TOOLWRIGHT_AUTH_API_EXAMPLE_COM", None)
        auth_setup_flow(root=tmp_path, toolpack_path=str(tp_path), no_probe=True)
    assert gitignore.exists()
    assert ".toolwright/.env" in gitignore.read_text()
