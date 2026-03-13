"""Tests for recipe loading and validation."""

from __future__ import annotations

from toolwright.recipes.loader import list_recipes, load_recipe


def test_list_recipes_returns_bundled():
    """list_recipes should return the bundled recipes that work end-to-end."""
    recipes = list_recipes()
    names = {r["name"] for r in recipes}
    assert "github" in names
    assert "stripe" in names
    # Only recipes with working openapi_spec_url are shipped
    assert "shopify" not in names
    assert "notion" not in names
    assert "slack" not in names


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


def test_removed_recipes_raise_value_error():
    """Removed recipes (shopify, notion, slack) should raise ValueError."""
    import pytest

    for name in ("shopify", "notion", "slack"):
        with pytest.raises(ValueError, match="Unknown recipe"):
            load_recipe(name)
