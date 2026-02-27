"""Tests for toolwright.ui.discovery — bounded path discovery."""

from __future__ import annotations

from pathlib import Path

from toolwright.ui.discovery import find_lockfiles, find_toolpacks


class TestFindToolpacks:
    """find_toolpacks() scans root/toolpacks/**/toolpack.yaml (1 level deep)."""

    def test_finds_toolpacks_in_root(self, tmp_path: Path) -> None:
        # Create root/toolpacks/my-api/toolpack.yaml
        tp_dir = tmp_path / "toolpacks" / "my-api"
        tp_dir.mkdir(parents=True)
        tp_file = tp_dir / "toolpack.yaml"
        tp_file.write_text("name: my-api")

        results = find_toolpacks(tmp_path)
        assert len(results) == 1
        assert results[0] == tp_file.resolve()

    def test_finds_multiple_toolpacks(self, tmp_path: Path) -> None:
        for name in ("alpha", "beta", "gamma"):
            d = tmp_path / "toolpacks" / name
            d.mkdir(parents=True)
            (d / "toolpack.yaml").write_text(f"name: {name}")

        results = find_toolpacks(tmp_path)
        assert len(results) == 3
        names = [r.parent.name for r in results]
        assert names == ["alpha", "beta", "gamma"]  # sorted

    def test_empty_root(self, tmp_path: Path) -> None:
        results = find_toolpacks(tmp_path)
        assert results == []

    def test_empty_toolpacks_dir(self, tmp_path: Path) -> None:
        (tmp_path / "toolpacks").mkdir()
        results = find_toolpacks(tmp_path)
        assert results == []

    def test_ignores_files_in_toolpacks_dir(self, tmp_path: Path) -> None:
        tp_dir = tmp_path / "toolpacks"
        tp_dir.mkdir()
        (tp_dir / "some_file.txt").write_text("not a toolpack")
        results = find_toolpacks(tmp_path)
        assert results == []

    def test_ignores_dir_without_toolpack_yaml(self, tmp_path: Path) -> None:
        d = tmp_path / "toolpacks" / "no-yaml"
        d.mkdir(parents=True)
        (d / "other.txt").write_text("not a toolpack")
        results = find_toolpacks(tmp_path)
        assert results == []


class TestFindLockfiles:
    """find_lockfiles() scans root/**/toolwright.lock*.yaml (max depth 3)."""

    def test_finds_lockfile_in_root(self, tmp_path: Path) -> None:
        lf = tmp_path / "toolwright.lock.yaml"
        lf.write_text("version: 1")

        results = find_lockfiles(tmp_path)
        assert len(results) == 1
        assert results[0] == lf.resolve()

    def test_finds_pending_lockfile(self, tmp_path: Path) -> None:
        lf = tmp_path / "toolwright.lock.pending.yaml"
        lf.write_text("version: 1")

        results = find_lockfiles(tmp_path)
        assert len(results) == 1
        assert results[0] == lf.resolve()

    def test_finds_nested_lockfile(self, tmp_path: Path) -> None:
        nested = tmp_path / "sub" / "toolwright.lock.yaml"
        nested.parent.mkdir()
        nested.write_text("version: 1")

        results = find_lockfiles(tmp_path)
        assert len(results) == 1

    def test_bounded_at_max_depth(self, tmp_path: Path) -> None:
        # depth 0: root (scanned)
        # depth 1: a (scanned)
        # depth 2: a/b (scanned)
        # depth 3: a/b/c (scanned)
        # depth 4: a/b/c/d (NOT scanned — beyond max_depth=3)
        deep = tmp_path / "a" / "b" / "c" / "d"
        deep.mkdir(parents=True)
        too_deep = deep / "toolwright.lock.yaml"
        too_deep.write_text("version: 1")

        # Also add one at depth 3 (should be found)
        ok = tmp_path / "a" / "b" / "c" / "toolwright.lock.yaml"
        ok.write_text("version: 1")

        results = find_lockfiles(tmp_path)
        assert len(results) == 1
        assert results[0] == ok.resolve()

    def test_empty_root(self, tmp_path: Path) -> None:
        results = find_lockfiles(tmp_path)
        assert results == []

    def test_ignores_non_matching_files(self, tmp_path: Path) -> None:
        (tmp_path / "other.yaml").write_text("not a lockfile")
        (tmp_path / "lockfile.yaml").write_text("not matching pattern")
        results = find_lockfiles(tmp_path)
        assert results == []

    def test_does_not_follow_symlinks(self, tmp_path: Path) -> None:
        # Create a symlinked directory
        real_dir = tmp_path / "real"
        real_dir.mkdir()
        (real_dir / "toolwright.lock.yaml").write_text("version: 1")

        link = tmp_path / "linked"
        link.symlink_to(real_dir)

        # Only the real one should be found
        results = find_lockfiles(tmp_path)
        assert len(results) == 1
        assert results[0] == (real_dir / "toolwright.lock.yaml").resolve()

    def test_finds_multiple_lockfiles_sorted(self, tmp_path: Path) -> None:
        (tmp_path / "toolwright.lock.yaml").write_text("v1")
        (tmp_path / "toolwright.lock.pending.yaml").write_text("v1")
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "toolwright.lock.yaml").write_text("v1")

        results = find_lockfiles(tmp_path)
        assert len(results) == 3
        # Should be sorted by path
        names = [r.name for r in results]
        assert all(n.startswith("toolwright.lock") for n in names)
