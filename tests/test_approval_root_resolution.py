"""Tests for approval root resolution helpers."""

from __future__ import annotations

from pathlib import Path

from toolwright.core.approval.signing import resolve_approval_root


def test_resolve_approval_root_uses_fallback_when_lockfile_outside_root(
    tmp_path: Path,
) -> None:
    """Lockfiles exported outside a `.toolwright` tree should still verify via fallback root."""
    lockfile = tmp_path / "export" / "lockfile" / "toolwright.lock.yaml"
    lockfile.parent.mkdir(parents=True, exist_ok=True)
    lockfile.write_text("version: '1.0'\n", encoding="utf-8")

    approval_root = tmp_path / "portable" / ".toolwright"
    confirm_store = approval_root / "state" / "confirmations.db"
    confirm_store.parent.mkdir(parents=True, exist_ok=True)
    confirm_store.write_text("", encoding="utf-8")

    resolved = resolve_approval_root(
        lockfile_path=lockfile,
        fallback_root=confirm_store,
    )
    assert resolved == approval_root.resolve()


def test_resolve_approval_root_accepts_fallback_root_directory(tmp_path: Path) -> None:
    lockfile = tmp_path / "export" / "lockfile" / "toolwright.lock.yaml"
    lockfile.parent.mkdir(parents=True, exist_ok=True)
    lockfile.write_text("version: '1.0'\n", encoding="utf-8")

    approval_root = tmp_path / "portable" / ".toolwright"
    approval_root.mkdir(parents=True, exist_ok=True)

    resolved = resolve_approval_root(
        lockfile_path=lockfile,
        fallback_root=approval_root,
    )
    assert resolved == approval_root.resolve()


def test_resolve_approval_root_prefers_lockfile_ancestor(tmp_path: Path) -> None:
    approval_root = tmp_path / "project" / ".toolwright"
    lockfile = approval_root / "locks" / "toolwright.lock.yaml"
    lockfile.parent.mkdir(parents=True, exist_ok=True)
    lockfile.write_text("version: '1.0'\n", encoding="utf-8")

    other_root = tmp_path / "other" / ".toolwright"
    confirm_store = other_root / "state" / "confirmations.db"
    confirm_store.parent.mkdir(parents=True, exist_ok=True)
    confirm_store.write_text("", encoding="utf-8")

    resolved = resolve_approval_root(
        lockfile_path=lockfile,
        fallback_root=confirm_store,
    )
    assert resolved == approval_root.resolve()

