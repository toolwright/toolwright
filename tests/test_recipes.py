"""Tests for recipe loading and validation."""

from __future__ import annotations

from toolwright.recipes.loader import list_recipes, load_recipe


def test_list_recipes_returns_bundled():
    """list_recipes should return at least 5 bundled recipes."""
    recipes = list_recipes()
    names = {r["name"] for r in recipes}
    assert "github" in names
    assert "shopify" in names
    assert "notion" in names
    assert "stripe" in names
    assert "slack" in names


def test_load_recipe_returns_parsed_yaml():
    """load_recipe should return a full recipe dict."""
    recipe = load_recipe("github")
    assert recipe["name"] == "github"
    assert "hosts" in recipe
    assert len(recipe["hosts"]) >= 1
    assert "rule_templates" in recipe


def test_load_recipe_unknown_raises():
    """load_recipe should raise ValueError for unknown recipe."""
    import pytest

    with pytest.raises(ValueError, match="Unknown recipe"):
        load_recipe("nonexistent")


def test_shopify_recipe_has_custom_auth_header():
    """Shopify recipe should specify X-Shopify-Access-Token."""
    recipe = load_recipe("shopify")
    host = recipe["hosts"][0]
    assert host["auth_header_name"] == "X-Shopify-Access-Token"


def test_notion_recipe_has_extra_headers():
    """Notion recipe should specify Notion-Version header."""
    recipe = load_recipe("notion")
    assert "Notion-Version" in recipe.get("extra_headers", {})
