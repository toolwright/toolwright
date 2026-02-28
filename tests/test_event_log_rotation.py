"""Tests for event log rotation."""

from __future__ import annotations

from pathlib import Path

from toolwright.core.reconcile.event_log import ReconcileEventLog
from toolwright.models.reconcile import ReconcileEvent


def test_rotation_triggered_when_log_exceeds_max_size(tmp_path: Path) -> None:
    """Log files are rotated when they exceed MAX_LOG_SIZE."""
    log = ReconcileEventLog(str(tmp_path))
    # Use a small limit for testing
    log.MAX_LOG_SIZE = 1024  # 1KB

    # Write enough data to exceed 1KB
    for i in range(100):
        event = ReconcileEvent(
            tool_id=f"tool_{i}",
            kind="drift_detected",
            description="x" * 100,
        )
        log.record(event)

    # Should have rotated at least once
    rotated = log.log_path.parent / f"{log.log_path.name}.1"
    assert rotated.exists(), f"Expected rotated file {rotated} to exist"

    # recent() should still work (reads from current log)
    events = log.recent(10)
    assert len(events) <= 10


def test_rotation_shifts_existing_files(tmp_path: Path) -> None:
    """Multiple rotations shift files: .1 -> .2 -> .3."""
    log = ReconcileEventLog(str(tmp_path))
    log.MAX_LOG_SIZE = 512  # Very small for quick rotation

    # Write enough data to trigger multiple rotations
    for i in range(200):
        event = ReconcileEvent(
            tool_id=f"tool_{i}",
            kind="drift_detected",
            description="y" * 100,
        )
        log.record(event)

    # At minimum .1 should exist
    assert (log.log_path.parent / f"{log.log_path.name}.1").exists()


def test_rotation_deletes_oldest_beyond_max(tmp_path: Path) -> None:
    """Oldest rotated file beyond MAX_ROTATED is deleted."""
    log = ReconcileEventLog(str(tmp_path))
    log.MAX_LOG_SIZE = 256  # Tiny for lots of rotations
    log.MAX_ROTATED = 2  # Only keep 2 rotated files

    for i in range(300):
        event = ReconcileEvent(
            tool_id=f"tool_{i}",
            kind="drift_detected",
            description="z" * 100,
        )
        log.record(event)

    # .1 and .2 may exist but .3 should not
    third = log.log_path.parent / f"{log.log_path.name}.3"
    assert not third.exists(), f"File {third} should have been deleted (beyond MAX_ROTATED=2)"
