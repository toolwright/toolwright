"""Tests for toolpack auto-resolution chain."""

from __future__ import annotations

import os
from pathlib import Path

import click
import pytest
import yaml

from toolwright.utils.resolve import resolve_toolpack_path


@pytest.fixture()
def tw_root(tmp_path: Path) -> Path:
    """Create a .toolwright root with standard structure."""
    root = tmp_path / ".toolwright"
    root.mkdir()
    (root / "toolpacks").mkdir()
    return root


def _make_toolpack(root: Path, name: str) -> Path:
    """Create a minimal toolpack directory with toolpack.yaml."""
    tp_dir = root / "toolpacks" / name
    tp_dir.mkdir(parents=True, exist_ok=True)
    tp_file = tp_dir / "toolpack.yaml"
    tp_file.write_text(yaml.dump({"toolpack_id": name}))
    return tp_file


class TestExplicitFlag:
    def test_explicit_path_used(self, tw_root: Path) -> None:
        tp = _make_toolpack(tw_root, "stripe")
        result = resolve_toolpack_path(explicit=str(tp), root=tw_root)
        assert result == tp

    def test_explicit_wins_over_env_var(
        self, tw_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        tp1 = _make_toolpack(tw_root, "stripe")
        tp2 = _make_toolpack(tw_root, "github")
        monkeypatch.setenv("TOOLWRIGHT_TOOLPACK", str(tp2))
        result = resolve_toolpack_path(explicit=str(tp1), root=tw_root)
        assert result == tp1

    def test_explicit_missing_file_raises(self, tw_root: Path) -> None:
        with pytest.raises(FileNotFoundError, match="Toolpack not found"):
            resolve_toolpack_path(explicit="/nonexistent/toolpack.yaml", root=tw_root)


class TestEnvVarFallback:
    def test_env_var_used_when_no_explicit(
        self, tw_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        tp = _make_toolpack(tw_root, "stripe")
        monkeypatch.setenv("TOOLWRIGHT_TOOLPACK", str(tp))
        result = resolve_toolpack_path(root=tw_root)
        assert result == tp

    def test_env_var_missing_file_raises(
        self, tw_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TOOLWRIGHT_TOOLPACK", "/nonexistent/toolpack.yaml")
        with pytest.raises(FileNotFoundError, match="TOOLWRIGHT_TOOLPACK points to missing file"):
            resolve_toolpack_path(root=tw_root)


class TestConfigFallback:
    def test_config_default_by_name(self, tw_root: Path) -> None:
        _make_toolpack(tw_root, "stripe")
        config_path = tw_root / "config.yaml"
        config_path.write_text(yaml.dump({"default_toolpack": "stripe"}))
        result = resolve_toolpack_path(root=tw_root)
        assert result == tw_root / "toolpacks" / "stripe" / "toolpack.yaml"

    def test_config_default_nonexistent_ignored(self, tw_root: Path) -> None:
        """Config points to nonexistent toolpack -> falls through to auto-detect."""
        tp = _make_toolpack(tw_root, "stripe")
        config_path = tw_root / "config.yaml"
        config_path.write_text(yaml.dump({"default_toolpack": "nonexistent"}))
        # Should fall through to auto-detect since only one toolpack exists
        result = resolve_toolpack_path(root=tw_root)
        assert result == tp


class TestAutoDetect:
    def test_single_toolpack_auto_detected(self, tw_root: Path) -> None:
        tp = _make_toolpack(tw_root, "stripe")
        result = resolve_toolpack_path(root=tw_root)
        assert result == tp

    def test_multiple_toolpacks_error(self, tw_root: Path) -> None:
        _make_toolpack(tw_root, "stripe")
        _make_toolpack(tw_root, "github")
        with pytest.raises(click.UsageError, match="Multiple toolpacks found"):
            resolve_toolpack_path(root=tw_root)

    def test_multiple_toolpacks_error_lists_options(self, tw_root: Path) -> None:
        _make_toolpack(tw_root, "stripe")
        _make_toolpack(tw_root, "github")
        with pytest.raises(click.UsageError, match="--toolpack"):
            resolve_toolpack_path(root=tw_root)

    def test_multiple_toolpacks_error_suggests_use(self, tw_root: Path) -> None:
        _make_toolpack(tw_root, "stripe")
        _make_toolpack(tw_root, "github")
        with pytest.raises(click.UsageError, match="toolwright use"):
            resolve_toolpack_path(root=tw_root)


class TestNoToolpacks:
    def test_no_toolpacks_error(self, tw_root: Path) -> None:
        with pytest.raises(click.UsageError, match="No toolpack found"):
            resolve_toolpack_path(root=tw_root)

    def test_no_toolpacks_error_suggests_mint(self, tw_root: Path) -> None:
        with pytest.raises(click.UsageError, match="toolwright mint"):
            resolve_toolpack_path(root=tw_root)

    def test_no_toolpacks_dir_error(self, tmp_path: Path) -> None:
        root = tmp_path / ".toolwright"
        root.mkdir()
        # No toolpacks/ subdirectory at all
        with pytest.raises(click.UsageError, match="No toolpack found"):
            resolve_toolpack_path(root=root)


class TestResolutionPriority:
    """Verify the full resolution chain priority."""

    def test_env_var_beats_config(
        self, tw_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        stripe = _make_toolpack(tw_root, "stripe")
        github = _make_toolpack(tw_root, "github")
        config_path = tw_root / "config.yaml"
        config_path.write_text(yaml.dump({"default_toolpack": "stripe"}))
        monkeypatch.setenv("TOOLWRIGHT_TOOLPACK", str(github))
        result = resolve_toolpack_path(root=tw_root)
        assert result == github

    def test_config_beats_auto_detect(self, tw_root: Path) -> None:
        _make_toolpack(tw_root, "stripe")
        github = _make_toolpack(tw_root, "github")
        config_path = tw_root / "config.yaml"
        config_path.write_text(yaml.dump({"default_toolpack": "github"}))
        result = resolve_toolpack_path(root=tw_root)
        assert result == tw_root / "toolpacks" / "github" / "toolpack.yaml"
