"""Filesystem helpers for atomic writes."""

from __future__ import annotations

import os
from pathlib import Path


def atomic_write_text(path: Path, data: str) -> None:
    """Atomically write text data to a file with fsync."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")

    with open(tmp_path, "w", encoding="utf-8") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())

    os.replace(tmp_path, path)
    _fsync_directory(path.parent)


def _fsync_directory(path: Path) -> None:
    """Best-effort fsync on a directory after atomic replace."""
    try:
        fd = os.open(path, os.O_DIRECTORY)
    except OSError:
        return
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
