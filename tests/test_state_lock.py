"""Tests for root state locking helpers."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from toolwright.utils.locks import RootLockError, clear_root_lock, root_command_lock
from toolwright.utils.state import runtime_lock_path


def test_root_lock_blocks_parallel_acquisition(tmp_path: Path) -> None:
    with root_command_lock(tmp_path / ".toolwright", "first"), pytest.raises(
        RootLockError
    ), root_command_lock(tmp_path / ".toolwright", "second"):
        pass


def test_root_lock_allows_parallel_acquisition_with_distinct_lock_ids(tmp_path: Path) -> None:
    root = tmp_path / ".toolwright"
    with root_command_lock(root, "first", lock_id="alpha"), root_command_lock(
        root,
        "second",
        lock_id="bravo",
    ):
        pass


def test_root_lock_auto_clears_stale_lock(tmp_path: Path) -> None:
    root = tmp_path / ".toolwright"
    lock_path = runtime_lock_path(root)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(
        json.dumps({"pid": 999999, "command": "stale", "created_at": time.time()}),
        encoding="utf-8",
    )

    with root_command_lock(root, "fresh"):
        assert lock_path.exists()

    assert not lock_path.exists()


def test_clear_root_lock_removes_stale_lock(tmp_path: Path) -> None:
    root = tmp_path / ".toolwright"
    lock_path = runtime_lock_path(root)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(
        json.dumps({"pid": 999999, "command": "stale", "created_at": time.time()}),
        encoding="utf-8",
    )
    clear_root_lock(root, force=False)
    assert not lock_path.exists()


def test_clear_root_lock_requires_force_for_active_pid(tmp_path: Path) -> None:
    root = tmp_path / ".toolwright"
    lock_path = runtime_lock_path(root)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(
        json.dumps({"pid": os.getpid(), "command": "active", "created_at": time.time()}),
        encoding="utf-8",
    )
    with pytest.raises(RootLockError):
        clear_root_lock(root, force=False)
    clear_root_lock(root, force=True)
    assert not lock_path.exists()
