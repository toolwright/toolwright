"""Tests for conditional default scope in mint command."""

from __future__ import annotations

from unittest.mock import patch

from click.testing import CliRunner

from toolwright.cli.main import cli


def test_mint_with_allowed_hosts_defaults_to_first_party_only() -> None:
    """When --allowed-hosts is provided but --scope is not, default to first_party_only."""
    runner = CliRunner()
    with patch("toolwright.cli.mint.run_mint") as mock_mint:
        mock_mint.side_effect = SystemExit(0)
        runner.invoke(
            cli,
            ["mint", "https://example.com", "-a", "api.example.com"],
            catch_exceptions=False,
        )
        if mock_mint.called:
            call_kwargs = mock_mint.call_args[1]
            assert call_kwargs["scope_name"] == "first_party_only"


def test_mint_with_explicit_scope_uses_that_scope() -> None:
    """When --scope is explicitly provided, use it regardless of --allowed-hosts."""
    runner = CliRunner()
    with patch("toolwright.cli.mint.run_mint") as mock_mint:
        mock_mint.side_effect = SystemExit(0)
        runner.invoke(
            cli,
            ["mint", "https://example.com", "-a", "api.example.com", "--scope", "agent_safe_readonly"],
            catch_exceptions=False,
        )
        if mock_mint.called:
            call_kwargs = mock_mint.call_args[1]
            assert call_kwargs["scope_name"] == "agent_safe_readonly"
