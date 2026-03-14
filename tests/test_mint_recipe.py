"""Tests for mint --recipe integration."""

from __future__ import annotations

from unittest.mock import patch

from click.testing import CliRunner


def test_mint_recipe_flag_requires_hosts_or_recipe():
    """mint must error if neither --allowed-hosts nor --recipe is given."""
    from toolwright.cli.main import cli

    runner = CliRunner()
    result = runner.invoke(cli, ["mint", "https://example.com"])
    assert result.exit_code != 0
    assert "--allowed-hosts or --recipe" in result.output


def test_mint_recipe_flag_provides_hosts():
    """mint --recipe should supply hosts from recipe, skipping capture."""
    from toolwright.cli.main import cli

    runner = CliRunner()
    # Patch run_mint at the source so the lazy import picks up the mock.
    with patch("toolwright.cli.mint.run_mint") as mock_run:
        runner.invoke(
            cli,
            ["mint", "https://api.github.com", "--recipe", "github", "--no-probe"],
            catch_exceptions=False,
        )
    assert mock_run.called
    call_kwargs = mock_run.call_args[1]
    assert "api.github.com" in call_kwargs["allowed_hosts"]


def test_mint_recipe_flag_passes_empty_extra_headers():
    """mint --recipe should pass extra_headers from recipe (github has none)."""
    from toolwright.cli.main import cli

    runner = CliRunner()
    with patch("toolwright.cli.mint.run_mint") as mock_run:
        runner.invoke(
            cli,
            [
                "mint", "https://api.github.com",
                "--recipe", "github",
                "--no-probe",
            ],
            catch_exceptions=False,
        )
    assert mock_run.called
    call_kwargs = mock_run.call_args[1]
    # github recipe has no extra_headers
    assert call_kwargs["extra_headers"] in ({}, None)


def test_mint_recipe_cli_headers_override_recipe():
    """CLI --extra-header should override/add to recipe header defaults."""
    from toolwright.cli.main import cli

    runner = CliRunner()
    with patch("toolwright.cli.mint.run_mint") as mock_run:
        runner.invoke(
            cli,
            [
                "mint", "https://api.github.com",
                "--recipe", "github",
                "-H", "X-Custom: test-value",
                "--no-probe",
            ],
            catch_exceptions=False,
        )
    assert mock_run.called
    call_kwargs = mock_run.call_args[1]
    # CLI value should be present
    assert call_kwargs["extra_headers"]["X-Custom"] == "test-value"


def test_mint_recipe_with_manual_hosts():
    """When both --recipe and --allowed-hosts given, manual hosts should win."""
    from toolwright.cli.main import cli

    runner = CliRunner()
    with patch("toolwright.cli.mint.run_mint") as mock_run:
        runner.invoke(
            cli,
            [
                "mint", "https://api.github.com",
                "--recipe", "github",
                "-a", "custom.example.com",
                "--no-probe",
            ],
            catch_exceptions=False,
        )
    assert mock_run.called
    call_kwargs = mock_run.call_args[1]
    # Manual hosts should be used, not recipe hosts
    assert "custom.example.com" in call_kwargs["allowed_hosts"]


def test_mint_recipe_passes_recipe_to_run_mint():
    """mint --recipe should pass recipe name to run_mint."""
    from toolwright.cli.main import cli

    runner = CliRunner()
    with patch("toolwright.cli.mint.run_mint") as mock_run:
        runner.invoke(
            cli,
            ["mint", "https://api.github.com", "--recipe", "github", "--no-probe"],
            catch_exceptions=False,
        )
    assert mock_run.called
    call_kwargs = mock_run.call_args[1]
    assert call_kwargs["recipe"] == "github"


def test_recipe_provides_allowed_hosts():
    """Recipe hosts should be usable as allowed_hosts for mint."""
    from toolwright.recipes.loader import load_recipe

    recipe = load_recipe("github")
    hosts = [h["pattern"] for h in recipe["hosts"]]
    assert len(hosts) >= 1
    assert "api.github.com" in hosts


def test_recipe_provides_rule_template_refs():
    """Recipe rule_templates should reference valid templates."""
    from toolwright.recipes.loader import load_recipe
    from toolwright.rules.loader import load_template

    recipe = load_recipe("stripe")
    for tmpl_name in recipe.get("rule_templates", []):
        # Should not raise
        template = load_template(tmpl_name)
        assert template["name"] == tmpl_name


def test_recipe_hosts_convertible_to_tuple():
    """Recipe hosts list should be convertible to tuple for Click compatibility."""
    from toolwright.recipes.loader import load_recipe

    recipe = load_recipe("github")
    hosts_tuple = tuple(h["pattern"] for h in recipe.get("hosts", []))
    assert isinstance(hosts_tuple, tuple)
    assert len(hosts_tuple) >= 1


def test_recipe_auth_header_enrichment():
    """Recipe auth_header_name should be applicable to auth requirements."""
    from toolwright.recipes.loader import load_recipe

    recipe = load_recipe("github")
    for host_entry in recipe.get("hosts", []):
        if host_entry.get("auth_header_name"):
            assert host_entry["auth_header_name"] == "Authorization"
            break
    else:
        raise AssertionError("Expected at least one host with auth_header_name")
