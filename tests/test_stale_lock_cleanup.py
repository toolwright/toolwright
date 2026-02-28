"""Tests for stale lock auto-cleanup on acquisition."""

from __future__ import annotations

import json
import os
from pathlib import Path

from toolwright.utils.locks import _pid_alive, root_command_lock
from toolwright.utils.state import runtime_lock_path


def test_stale_lock_auto_cleared(tmp_path: Path) -> None:
    """Lock with dead PID is auto-cleaned on acquisition."""
    root = tmp_path / ".toolwright"
    lock_path = runtime_lock_path(root)
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    # Create a stale lock with a dead PID
    stale_info = {
        "pid": 99999999,
        "command": "stale-test",
        "created_at": 0.0,
    }
    lock_path.write_text(json.dumps(stale_info), encoding="utf-8")
    assert lock_path.exists()
    assert not _pid_alive(99999999)

    # Acquiring should succeed by auto-clearing the stale lock
    with root_command_lock(root, "test"):
        assert lock_path.exists()  # New lock created
        new_info = json.loads(lock_path.read_text(encoding="utf-8"))
        assert new_info["pid"] == os.getpid()
        assert new_info["command"] == "test"

    # Lock should be cleaned up after context exit
    assert not lock_path.exists()
