"""Tests for `toolwright auth check` command."""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from toolwright.cli.main import cli


@pytest.fixture()
def tw_root(tmp_path: Path) -> Path:
    """Create a .toolwright root with a single toolpack containing allowed_hosts."""
    root = tmp_path / ".toolwright"
    root.mkdir()
    tp_dir = root / "toolpacks" / "stripe"
    tp_dir.mkdir(parents=True)
    tp_file = tp_dir / "toolpack.yaml"
    tp_file.write_text(
        "version: '1.0.0'\n"
        "schema_version: '1.0'\n"
        "toolpack_id: stripe\n"
        "created_at: '2024-01-01T00:00:00'\n"
        "capture_id: cap_1\n"
        "artifact_id: art_1\n"
        "scope: first_party_only\n"
        "allowed_hosts:\n"
        "  - api.stripe.com\n"
        "display_name: Stripe API\n"
        "origin:\n"
        "  start_url: https://dashboard.stripe.com\n"
        "paths:\n"
        "  tools: tools.json\n"
        "  toolsets: toolsets.yaml\n"
        "  policy: policy.yaml\n"
        "  baseline: baseline.yaml\n"
    )
    # Create minimal artifact files so load_toolpack doesn't fail
    (tp_dir / "tools.json").write_text('{"tools": []}')
    (tp_dir / "toolwright.lock.yaml").write_text("tools: {}")
    return root


@pytest.fixture()
def tw_root_multi_host(tmp_path: Path) -> Path:
    """Create a .toolwright root with a toolpack containing multiple hosts."""
    root = tmp_path / ".toolwright"
    root.mkdir()
    tp_dir = root / "toolpacks" / "myapi"
    tp_dir.mkdir(parents=True)
    tp_file = tp_dir / "toolpack.yaml"
    tp_file.write_text(
        "version: '1.0.0'\n"
        "schema_version: '1.0'\n"
        "toolpack_id: myapi\n"
        "created_at: '2024-01-01T00:00:00'\n"
        "capture_id: cap_1\n"
        "artifact_id: art_1\n"
        "scope: first_party_only\n"
        "allowed_hosts:\n"
        "  - api.example.com\n"
        "  - auth.example.com\n"
        "display_name: My API\n"
        "origin:\n"
        "  start_url: https://example.com\n"
        "paths:\n"
        "  tools: tools.json\n"
        "  toolsets: toolsets.yaml\n"
        "  policy: policy.yaml\n"
        "  baseline: baseline.yaml\n"
    )
    (tp_dir / "tools.json").write_text('{"tools": []}')
    (tp_dir / "toolwright.lock.yaml").write_text("tools: {}")
    return root


class TestEnvVarNameGeneration:
    """Test that env var names are generated correctly."""

    def test_simple_host(self) -> None:
        from toolwright.cli.commands_auth import _host_to_env_var

        assert _host_to_env_var("api.stripe.com") == "TOOLWRIGHT_AUTH_API_STRIPE_COM"

    def test_localhost_with_port(self) -> None:
        from toolwright.cli.commands_auth import _host_to_env_var

        assert _host_to_env_var("localhost:8080") == "TOOLWRIGHT_AUTH_LOCALHOST_8080"

    def test_hyphenated_host(self) -> None:
        from toolwright.cli.commands_auth import _host_to_env_var

        assert _host_to_env_var("my-api.example.com") == "TOOLWRIGHT_AUTH_MY_API_EXAMPLE_COM"


class TestAuthCheckFindsSetEnvVar:
    """Test that auth check detects when env vars are set."""

    def test_per_host_env_var_set(self, tw_root: Path) -> None:
        runner = CliRunner()
        with patch.dict(
            "os.environ",
            {"TOOLWRIGHT_AUTH_API_STRIPE_COM": "Bearer sk_test_123"},
            clear=False,
        ):
            result = runner.invoke(
                cli,
                ["--root", str(tw_root), "auth", "check", "--no-probe"],
            )
        assert result.exit_code == 0
        assert "SET" in result.output
        assert "TOOLWRIGHT_AUTH_API_STRIPE_COM" in result.output

    def test_global_env_var_set(self, tw_root: Path) -> None:
        runner = CliRunner()
        with patch.dict(
            "os.environ",
            {"TOOLWRIGHT_AUTH_HEADER": "Bearer global_token"},
            clear=False,
        ):
            result = runner.invoke(
                cli,
                ["--root", str(tw_root), "auth", "check", "--no-probe"],
            )
        assert result.exit_code == 0
        assert "SET" in result.output


class TestAuthCheckMissingEnvVar:
    """Test that auth check reports missing env vars with suggestions."""

    def test_missing_env_var_shows_not_set(self, tw_root: Path) -> None:
        runner = CliRunner()
        with patch.dict(
            "os.environ",
            {},
            clear=True,
        ):
            # Set PATH so subprocess calls don't fail
            import os

            result = runner.invoke(
                cli,
                ["--root", str(tw_root), "auth", "check", "--no-probe"],
                env={"PATH": os.environ.get("PATH", "")},
            )
        assert result.exit_code == 1
        assert "NOT SET" in result.output
        assert "TOOLWRIGHT_AUTH_API_STRIPE_COM" in result.output

    def test_missing_env_var_shows_export_suggestion(self, tw_root: Path) -> None:
        runner = CliRunner()
        with patch.dict("os.environ", {}, clear=True):
            import os

            result = runner.invoke(
                cli,
                ["--root", str(tw_root), "auth", "check", "--no-probe"],
                env={"PATH": os.environ.get("PATH", "")},
            )
        assert "export TOOLWRIGHT_AUTH_API_STRIPE_COM" in result.output


class TestAuthCheckPerHostPriority:
    """Test that per-host env var is checked first, then global."""

    def test_per_host_overrides_global(self, tw_root: Path) -> None:
        runner = CliRunner()
        with patch.dict(
            "os.environ",
            {
                "TOOLWRIGHT_AUTH_API_STRIPE_COM": "Bearer per_host",
                "TOOLWRIGHT_AUTH_HEADER": "Bearer global",
            },
            clear=False,
        ):
            result = runner.invoke(
                cli,
                ["--root", str(tw_root), "auth", "check", "--no-probe"],
            )
        assert result.exit_code == 0
        # Both should show as SET
        assert result.output.count("SET") >= 2


class TestAuthCheckProbe:
    """Test probe functionality."""

    def test_probe_success(self, tw_root: Path) -> None:
        """Mock a successful probe (200 response)."""
        import urllib.request

        runner = CliRunner()
        with (
            patch.dict(
                "os.environ",
                {"TOOLWRIGHT_AUTH_API_STRIPE_COM": "Bearer sk_test"},
                clear=False,
            ),
            patch("urllib.request.urlopen") as mock_urlopen,
        ):
            mock_response = type("Response", (), {"status": 200, "close": lambda self: None})()
            mock_urlopen.return_value = mock_response
            result = runner.invoke(
                cli,
                ["--root", str(tw_root), "auth", "check"],
            )
        assert result.exit_code == 0
        assert "200" in result.output

    def test_probe_auth_failure(self, tw_root: Path) -> None:
        """Mock a 401 response -> auth invalid."""
        import urllib.error

        runner = CliRunner()
        with (
            patch.dict(
                "os.environ",
                {"TOOLWRIGHT_AUTH_API_STRIPE_COM": "Bearer bad_token"},
                clear=False,
            ),
            patch("urllib.request.urlopen") as mock_urlopen,
        ):
            mock_urlopen.side_effect = urllib.error.HTTPError(
                url="https://api.stripe.com",
                code=401,
                msg="Unauthorized",
                hdrs=None,  # type: ignore[arg-type]
                fp=None,
            )
            result = runner.invoke(
                cli,
                ["--root", str(tw_root), "auth", "check"],
            )
        assert result.exit_code == 1
        assert "401" in result.output

    def test_no_probe_flag_skips_http(self, tw_root: Path) -> None:
        """--no-probe should not make any HTTP requests."""
        runner = CliRunner()
        with (
            patch.dict(
                "os.environ",
                {"TOOLWRIGHT_AUTH_API_STRIPE_COM": "Bearer sk_test"},
                clear=False,
            ),
            patch("urllib.request.urlopen") as mock_urlopen,
        ):
            result = runner.invoke(
                cli,
                ["--root", str(tw_root), "auth", "check", "--no-probe"],
            )
        mock_urlopen.assert_not_called()
        assert result.exit_code == 0


class TestAuthCheckMultiHost:
    """Test auth check with multiple hosts."""

    def test_checks_all_hosts(self, tw_root_multi_host: Path) -> None:
        runner = CliRunner()
        with patch.dict(
            "os.environ",
            {
                "TOOLWRIGHT_AUTH_API_EXAMPLE_COM": "Bearer token1",
                "TOOLWRIGHT_AUTH_AUTH_EXAMPLE_COM": "Bearer token2",
            },
            clear=False,
        ):
            result = runner.invoke(
                cli,
                ["--root", str(tw_root_multi_host), "auth", "check", "--no-probe"],
            )
        assert result.exit_code == 0
        assert "api.example.com" in result.output
        assert "auth.example.com" in result.output
