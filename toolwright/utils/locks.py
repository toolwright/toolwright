"""Root-level command lock utilities."""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from toolwright.utils.state import runtime_lock_path


class RootLockError(RuntimeError):
    """Raised when command lock acquisition fails."""


@dataclass(frozen=True)
class RootLockInfo:
    """Metadata persisted in the lock file."""

    pid: int
    command: str
    created_at: float

    def to_json(self) -> str:
        return json.dumps(
            {
                "pid": self.pid,
                "command": self.command,
                "created_at": self.created_at,
            },
            sort_keys=True,
        )


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _read_lock_info(path: Path) -> RootLockInfo | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None
    try:
        return RootLockInfo(
            pid=int(payload["pid"]),
            command=str(payload["command"]),
            created_at=float(payload["created_at"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


def clear_root_lock(root: str | Path | None, force: bool = False) -> None:
    """Clear a command lock for the provided root.

    Raises RootLockError if the lock is active and force=False.
    """
    path = runtime_lock_path(root)
    if not path.exists():
        return
    info = _read_lock_info(path)
    if not force and info and _pid_alive(info.pid):
        raise RootLockError(
            f"Lock is active (pid={info.pid}, command={info.command}). "
            "Use --force to remove it anyway."
        )
    path.unlink(missing_ok=True)


@contextmanager
def root_command_lock(
    root: str | Path | None,
    command: str,
    *,
    lock_id: str | None = None,
) -> Generator[None, None, None]:
    """Acquire an exclusive lock under <root>/state/lock for mutating commands."""
    lock_path = runtime_lock_path(root)
    if lock_id:
        digest = hashlib.sha256(lock_id.encode("utf-8")).hexdigest()[:12]
        lock_path = lock_path.with_name(f"{lock_path.name}.{digest}")
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    info = RootLockInfo(pid=os.getpid(), command=command, created_at=time.time())
    fd: int | None = None
    try:
        fd = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        existing = _read_lock_info(lock_path)
        if existing and _pid_alive(existing.pid):
            raise RootLockError(
                "another toolwright process is running "
                f"(pid={existing.pid}, command={existing.command}). "
                f"If stale, clear lock at {lock_path} with `toolwright state unlock --force`."
            ) from exc

        if existing and not _pid_alive(existing.pid):
            # Stale + readable lock. Auto-clear once and retry acquisition.
            lock_path.unlink(missing_ok=True)
            try:
                fd = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError as retry_exc:
                retry_existing = _read_lock_info(lock_path)
                if retry_existing and _pid_alive(retry_existing.pid):
                    raise RootLockError(
                        "another toolwright process is running "
                        f"(pid={retry_existing.pid}, command={retry_existing.command}). "
                        f"If stale, clear lock at {lock_path} with `toolwright state unlock --force`."
                    ) from retry_exc

        if fd is None:
            raise RootLockError(
                "found stale or unreadable lock file. "
                f"Clear {lock_path} with `toolwright state unlock --force`."
            ) from exc

    try:
        assert fd is not None
        os.write(fd, info.to_json().encode("utf-8"))
        os.close(fd)
        fd = None
        yield
    finally:
        if fd is not None:
            os.close(fd)
        lock_path.unlink(missing_ok=True)
