"""Tests for recipe auth_guide field support."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import yaml

from toolwright.recipes.loader import load_recipe, list_recipes


class TestRecipeAuthGuideLoading:
    """Test that auth_guide is parsed from recipe YAML."""

    def test_github_recipe_has_auth_guide(self) -> None:
        recipe = load_recipe("github")
        assert "auth_guide" in recipe
        guide = recipe["auth_guide"]
        assert guide["host"] == "api.github.com"
        assert guide["scheme"] == "bearer"
        assert "github.com" in guide["create_url"]
        assert guide["scopes_hint"]
        assert guide["instructions"]

    def test_stripe_recipe_has_auth_guide(self) -> None:
        recipe = load_recipe("stripe")
        assert "auth_guide" in recipe
        guide = recipe["auth_guide"]
        assert guide["host"] == "api.stripe.com"
        assert guide["scheme"] == "bearer"
        assert "stripe.com" in guide["create_url"]
        assert guide["scopes_hint"]
        assert guide["instructions"]

    def test_recipe_without_auth_guide_loads(self, tmp_path: Path) -> None:
        """A recipe without auth_guide should still load (backward compat)."""
        recipe_file = tmp_path / "test.yaml"
        recipe_file.write_text(yaml.dump({
            "name": "test",
            "description": "Test recipe",
            "hosts": [{"pattern": "test.example.com"}],
        }))

        with patch("toolwright.recipes.loader._RECIPES_DIR", tmp_path):
            recipe = load_recipe("test")

        assert recipe["name"] == "test"
        assert recipe.get("auth_guide") is None

    def test_auth_guide_fields_accessible(self) -> None:
        recipe = load_recipe("github")
        guide = recipe["auth_guide"]
        # All five expected fields should be present
        expected_fields = {"host", "scheme", "create_url", "scopes_hint", "instructions"}
        assert expected_fields.issubset(set(guide.keys()))

    def test_list_recipes_still_works_with_auth_guide(self) -> None:
        """list_recipes should not break when auth_guide is present."""
        recipes = list_recipes()
        assert len(recipes) > 0
        # Each recipe should have name, description, hosts
        for r in recipes:
            assert "name" in r
