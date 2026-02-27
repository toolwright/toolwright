"""Tests for nested resource descriptions."""

from __future__ import annotations

from toolwright.core.compile.tools import ToolManifestGenerator
from toolwright.models.endpoint import Endpoint


def _ep(method: str, path: str) -> Endpoint:
    return Endpoint(
        method=method,
        path=path,
        host="api.example.com",
        url=f"https://api.example.com{path}",
    )


def test_nested_collection_mentions_parent() -> None:
    """GET /albums/{id}/photos should mention 'album' in description."""
    gen = ToolManifestGenerator()
    ep = _ep("GET", "/albums/{id}/photos")
    desc = gen._generate_description(ep)
    assert "album" in desc.lower(), f"Expected 'album' in: {desc}"


def test_nested_comments_mentions_post() -> None:
    """GET /posts/{id}/comments should mention 'post' in description."""
    gen = ToolManifestGenerator()
    ep = _ep("GET", "/posts/{id}/comments")
    desc = gen._generate_description(ep)
    assert "post" in desc.lower(), f"Expected 'post' in: {desc}"


def test_top_level_collection_unchanged() -> None:
    """GET /posts should say 'List all posts', not mention any parent."""
    gen = ToolManifestGenerator()
    ep = _ep("GET", "/posts")
    desc = gen._generate_description(ep)
    assert "List all posts" in desc


def test_nested_single_resource_unaffected() -> None:
    """GET /posts/{post_id}/comments/{id} should not say 'List'."""
    gen = ToolManifestGenerator()
    ep = _ep("GET", "/posts/{post_id}/comments/{id}")
    desc = gen._generate_description(ep)
    assert "Retrieve" in desc
