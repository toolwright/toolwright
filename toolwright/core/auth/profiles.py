"""Auth profile management — local-only Playwright storage state."""

from __future__ import annotations

import json
import os
import platform
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class AuthProfileManager:
    """Manages local auth profiles (Playwright storage_state.json).

    Profiles are stored under <root>/auth/profiles/<name>/ with:
    - storage_state.json: Playwright browser state (cookies, localStorage)
    - meta.json: Created/updated timestamps and target URL
    """

    def __init__(self, root: Path) -> None:
        self.root = root
        self.profiles_dir = root / "auth" / "profiles"

    def create(
        self,
        name: str,
        storage_state: dict[str, Any],
        target_url: str,
    ) -> Path:
        """Create a new auth profile with storage state.

        Returns the path to the profile directory.
        """
        _validate_name(name)
        profile_dir = self.profiles_dir / name
        profile_dir.mkdir(parents=True, exist_ok=True)

        state_path = profile_dir / "storage_state.json"
        state_path.write_text(
            json.dumps(storage_state, indent=2, default=str),
            encoding="utf-8",
        )
        _set_secure_permissions(state_path)

        meta = {
            "name": name,
            "target_url": target_url,
            "created_at": datetime.now(UTC).isoformat(),
            "last_used_at": None,
        }
        meta_path = profile_dir / "meta.json"
        meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

        return profile_dir

    def load(self, name: str) -> dict[str, Any] | None:
        """Load a profile's storage state. Returns None if not found."""
        profile_dir = self.profiles_dir / name
        state_path = profile_dir / "storage_state.json"
        if not state_path.exists():
            return None
        raw = state_path.read_text(encoding="utf-8")
        loaded = json.loads(raw)
        return loaded if isinstance(loaded, dict) else None

    def get_storage_state_path(self, name: str) -> Path | None:
        """Get the path to a profile's storage_state.json.

        Returns None if the profile doesn't exist.
        """
        state_path = self.profiles_dir / name / "storage_state.json"
        return state_path if state_path.exists() else None

    def get_meta(self, name: str) -> dict[str, Any] | None:
        """Load a profile's metadata. Returns None if not found."""
        meta_path = self.profiles_dir / name / "meta.json"
        if not meta_path.exists():
            return None
        raw = meta_path.read_text(encoding="utf-8")
        loaded = json.loads(raw)
        return loaded if isinstance(loaded, dict) else None

    def update_last_used(self, name: str) -> None:
        """Update the last_used_at timestamp for a profile."""
        meta = self.get_meta(name)
        if meta is None:
            return
        meta["last_used_at"] = datetime.now(UTC).isoformat()
        meta_path = self.profiles_dir / name / "meta.json"
        meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    def list_profiles(self) -> list[dict[str, Any]]:
        """List all auth profiles with their metadata."""
        if not self.profiles_dir.exists():
            return []

        results: list[dict[str, Any]] = []
        for entry in sorted(self.profiles_dir.iterdir()):
            if not entry.is_dir():
                continue
            meta = self.get_meta(entry.name)
            has_state = (entry / "storage_state.json").exists()
            results.append({
                "name": entry.name,
                "has_storage_state": has_state,
                **(meta or {}),
            })
        return results

    def clear(self, name: str) -> bool:
        """Delete an auth profile. Returns True if it existed."""
        profile_dir = self.profiles_dir / name
        if not profile_dir.exists():
            return False

        import shutil

        shutil.rmtree(profile_dir)
        return True

    def exists(self, name: str) -> bool:
        """Check if a profile exists."""
        return (self.profiles_dir / name / "storage_state.json").exists()


def _validate_name(name: str) -> None:
    """Validate profile name is safe for filesystem use."""
    if not name or not name.strip():
        raise ValueError("Profile name cannot be empty")
    if "/" in name or "\\" in name or ".." in name:
        raise ValueError("Profile name cannot contain path separators or '..'")
    if name.startswith("."):
        raise ValueError("Profile name cannot start with '.'")


def _set_secure_permissions(path: Path) -> None:
    """Set file permissions to 0600 on POSIX systems."""
    if platform.system() == "Windows":
        return
    try:
        os.chmod(path, 0o600)
    except OSError:
        # Best effort — warn but don't fail
        print(
            f"Warning: Could not set secure permissions on {path}",
            file=sys.stderr,
        )
