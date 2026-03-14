"""Tests for toolpack name resolution (C3+C6).

Bare names like 'github' should resolve to .toolwright/toolpacks/github/toolpack.yaml.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from toolwright.utils.resolve import resolve_toolpack_path


class TestToolpackNameResolution:
    """C3+C6: bare names must resolve to toolpack paths."""

    def test_bare_name_resolves_to_toolpack_yaml(self, tmp_path: Path) -> None:
        """'github' should resolve to .toolwright/toolpacks/github/toolpack.yaml."""
        root = tmp_path / ".toolwright"
        tp_dir = root / "toolpacks" / "github"
        tp_dir.mkdir(parents=True)
        tp_file = tp_dir / "toolpack.yaml"
        tp_file.write_text("toolpack_id: github")

        result = resolve_toolpack_path(explicit="github", root=root)
        assert result == tp_file

    def test_bare_name_not_found_raises(self, tmp_path: Path) -> None:
        """Unknown bare name should raise FileNotFoundError."""
        root = tmp_path / ".toolwright"
        root.mkdir(parents=True)

        with pytest.raises(FileNotFoundError):
            resolve_toolpack_path(explicit="nonexistent", root=root)

    def test_explicit_path_still_works(self, tmp_path: Path) -> None:
        """Full path should still resolve directly."""
        tp_file = tmp_path / "toolpack.yaml"
        tp_file.write_text("toolpack_id: test")

        result = resolve_toolpack_path(explicit=str(tp_file))
        assert result == tp_file

    def test_bare_name_with_cwd_toolpacks(self, tmp_path: Path, monkeypatch) -> None:
        """Name resolves under .toolwright/toolpacks/ relative to root."""
        root = tmp_path / ".toolwright"
        tp_dir = root / "toolpacks" / "stripe"
        tp_dir.mkdir(parents=True)
        tp_file = tp_dir / "toolpack.yaml"
        tp_file.write_text("toolpack_id: stripe")

        result = resolve_toolpack_path(explicit="stripe", root=root)
        assert result == tp_file

    def test_bare_name_prefers_existing_file_over_name(self, tmp_path: Path) -> None:
        """If an explicit absolute path exists, use it instead of name resolution."""
        # Create a file at an explicit path
        real_file = tmp_path / "my-toolpack.yaml"
        real_file.write_text("toolpack_id: from-file")

        # Also create .toolwright/toolpacks/my-toolpack.yaml/toolpack.yaml (unlikely but tests priority)
        root = tmp_path / ".toolwright"
        root.mkdir(parents=True)

        result = resolve_toolpack_path(explicit=str(real_file), root=root)
        assert result == real_file
