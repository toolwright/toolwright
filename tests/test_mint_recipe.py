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
            ["mint", "https://example.myshopify.com", "--recipe", "shopify", "--no-probe"],
            catch_exceptions=False,
        )
    assert mock_run.called
    call_kwargs = mock_run.call_args[1]
    assert "*.myshopify.com" in call_kwargs["allowed_hosts"]


def test_mint_recipe_flag_merges_extra_headers():
    """mint --recipe should set extra_headers from recipe."""
    from toolwright.cli.main import cli

    runner = CliRunner()
    with patch("toolwright.cli.mint.run_mint") as mock_run:
        runner.invoke(
            cli,
            [
                "mint", "https://api.notion.com",
                "--recipe", "notion",
                "--no-probe",
            ],
            catch_exceptions=False,
        )
    assert mock_run.called
    call_kwargs = mock_run.call_args[1]
    assert call_kwargs["extra_headers"]["Notion-Version"] == "2022-06-28"


def test_mint_recipe_cli_headers_override_recipe():
    """CLI --extra-header should override recipe header defaults."""
    from toolwright.cli.main import cli

    runner = CliRunner()
    with patch("toolwright.cli.mint.run_mint") as mock_run:
        runner.invoke(
            cli,
            [
                "mint", "https://api.notion.com",
                "--recipe", "notion",
                "-H", "Notion-Version: 2099-01-01",
                "--no-probe",
            ],
            catch_exceptions=False,
        )
    assert mock_run.called
    call_kwargs = mock_run.call_args[1]
    # CLI value should win over recipe default
    assert call_kwargs["extra_headers"]["Notion-Version"] == "2099-01-01"


def test_mint_recipe_with_manual_hosts():
    """When both --recipe and --allowed-hosts given, manual hosts should win."""
    from toolwright.cli.main import cli

    runner = CliRunner()
    with patch("toolwright.cli.mint.run_mint") as mock_run:
        runner.invoke(
            cli,
            [
                "mint", "https://example.myshopify.com",
                "--recipe", "shopify",
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
            ["mint", "https://example.myshopify.com", "--recipe", "shopify", "--no-probe"],
            catch_exceptions=False,
        )
    assert mock_run.called
    call_kwargs = mock_run.call_args[1]
    assert call_kwargs["recipe"] == "shopify"


def test_recipe_provides_allowed_hosts():
    """Recipe hosts should be usable as allowed_hosts for mint."""
    from toolwright.recipes.loader import load_recipe

    recipe = load_recipe("shopify")
    hosts = [h["pattern"] for h in recipe["hosts"]]
    assert len(hosts) >= 1
    assert "*.myshopify.com" in hosts


def test_recipe_provides_extra_headers():
    """Recipe extra_headers should be mergeable into mint headers."""
    from toolwright.recipes.loader import load_recipe

    recipe = load_recipe("notion")
    extra = recipe.get("extra_headers", {})
    assert "Notion-Version" in extra


def test_recipe_provides_rule_template_refs():
    """Recipe rule_templates should reference valid templates."""
    from toolwright.recipes.loader import load_recipe
    from toolwright.rules.loader import load_template

    recipe = load_recipe("shopify")
    for tmpl_name in recipe.get("rule_templates", []):
        # Should not raise
        template = load_template(tmpl_name)
        assert template["name"] == tmpl_name


def test_recipe_hosts_convertible_to_tuple():
    """Recipe hosts list should be convertible to tuple for Click compatibility."""
    from toolwright.recipes.loader import load_recipe

    recipe = load_recipe("shopify")
    hosts_tuple = tuple(h["pattern"] for h in recipe.get("hosts", []))
    assert isinstance(hosts_tuple, tuple)
    assert len(hosts_tuple) >= 1


def test_recipe_extra_headers_merge_cli_wins():
    """CLI-provided extra headers should override recipe defaults."""
    from toolwright.recipes.loader import load_recipe

    recipe = load_recipe("notion")
    recipe_headers = recipe.get("extra_headers", {})

    # Simulate merge: CLI overrides recipe
    cli_headers = {"Notion-Version": "2023-08-01"}
    merged = dict(recipe_headers)
    merged.update(cli_headers)

    assert merged["Notion-Version"] == "2023-08-01"  # CLI wins


def test_recipe_auth_header_enrichment():
    """Recipe auth_header_name should be applicable to auth requirements."""
    from toolwright.recipes.loader import load_recipe

    recipe = load_recipe("shopify")
    for host_entry in recipe.get("hosts", []):
        if host_entry.get("auth_header_name"):
            assert host_entry["auth_header_name"] == "X-Shopify-Access-Token"
            break
    else:
        raise AssertionError("Expected at least one host with auth_header_name")
