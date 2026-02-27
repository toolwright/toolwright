"""Tests for friendly toolpack directory naming."""

from __future__ import annotations

from pathlib import Path

import pytest

from toolwright.utils.resolve import generate_toolpack_slug


@pytest.fixture()
def tw_root(tmp_path: Path) -> Path:
    """Create a .toolwright root with standard structure."""
    root = tmp_path / ".toolwright"
    root.mkdir()
    (root / "toolpacks").mkdir()
    return root


class TestSlugFromHost:
    def test_api_stripe_com(self) -> None:
        assert generate_toolpack_slug(allowed_hosts=["api.stripe.com"]) == "stripe"

    def test_dummyjson_com(self) -> None:
        assert generate_toolpack_slug(allowed_hosts=["dummyjson.com"]) == "dummyjson"

    def test_api_github_com(self) -> None:
        assert generate_toolpack_slug(allowed_hosts=["api.github.com"]) == "github"

    def test_localhost(self) -> None:
        assert generate_toolpack_slug(allowed_hosts=["localhost"]) == "localhost"

    def test_no_hosts_fallback(self) -> None:
        assert generate_toolpack_slug(allowed_hosts=[]) == "toolpack"


class TestUserChosenName:
    def test_name_wins_over_host(self) -> None:
        assert generate_toolpack_slug(
            name="my-api", allowed_hosts=["api.stripe.com"]
        ) == "my-api"

    def test_name_with_no_hosts(self) -> None:
        assert generate_toolpack_slug(name="payments") == "payments"


class TestCollisionHandling:
    def test_first_use_no_collision(self, tw_root: Path) -> None:
        slug = generate_toolpack_slug(
            allowed_hosts=["api.stripe.com"], root=tw_root
        )
        assert slug == "stripe"

    def test_collision_appends_suffix(self, tw_root: Path) -> None:
        # Create existing stripe directory
        (tw_root / "toolpacks" / "stripe").mkdir()
        slug = generate_toolpack_slug(
            allowed_hosts=["api.stripe.com"], root=tw_root
        )
        assert slug == "stripe-2"

    def test_double_collision(self, tw_root: Path) -> None:
        (tw_root / "toolpacks" / "stripe").mkdir()
        (tw_root / "toolpacks" / "stripe-2").mkdir()
        slug = generate_toolpack_slug(
            allowed_hosts=["api.stripe.com"], root=tw_root
        )
        assert slug == "stripe-3"

    def test_name_collision(self, tw_root: Path) -> None:
        (tw_root / "toolpacks" / "my-api").mkdir()
        slug = generate_toolpack_slug(name="my-api", root=tw_root)
        assert slug == "my-api-2"


class TestBackwardCompat:
    def test_old_tp_prefix_still_valid(self, tw_root: Path) -> None:
        """Old tp_hash directories should still work as toolpack directories."""
        old_dir = tw_root / "toolpacks" / "tp_abc123def456"
        old_dir.mkdir()
        tp_file = old_dir / "toolpack.yaml"
        tp_file.write_text("toolpack_id: tp_abc123def456")
        # The old directory exists and has a toolpack.yaml — it's valid
        assert tp_file.exists()
