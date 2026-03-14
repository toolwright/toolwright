"""Minimal .env file reader/writer for toolwright auth tokens."""

from __future__ import annotations

import os
from pathlib import Path


class DotenvFile:
    """Minimal .env file reader/writer for toolwright auth tokens."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._entries: dict[str, str] = {}
        self._raw_lines: list[str] = []

    def load(self) -> dict[str, str]:
        """Parse .env file. Returns dict of KEY=VALUE pairs.

        Skip # comments and blank lines. Split on first = only.
        Handle \\r\\n line endings.
        """
        self._entries.clear()
        self._raw_lines.clear()

        if not self.path.exists():
            return {}

        text = self.path.read_text()
        for raw_line in text.splitlines():
            line = raw_line.strip()
            self._raw_lines.append(raw_line)

            if not line or line.startswith("#"):
                continue

            if "=" not in line:
                continue

            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            self._entries[key] = value

        return dict(self._entries)

    def get(self, key: str) -> str | None:
        """Get a value by key."""
        return self._entries.get(key)

    def set(self, key: str, value: str) -> None:
        """Set a key. Updates in-place if exists, appends if new."""
        if key in self._entries:
            # Update existing line in _raw_lines
            for i, raw_line in enumerate(self._raw_lines):
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                k, _, _ = line.partition("=")
                if k.strip() == key:
                    self._raw_lines[i] = f"{key}={value}"
                    break
        else:
            self._raw_lines.append(f"{key}={value}")

        self._entries[key] = value

    def save(self) -> None:
        """Write to disk with 0600 permissions. Creates parent dirs."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        content = "\n".join(self._raw_lines) + "\n"
        self.path.write_text(content)
        os.chmod(self.path, 0o600)

    @staticmethod
    def ensure_gitignored(dotenv_path: Path) -> bool:
        """Check and auto-add .env path to .gitignore. Returns True if added."""
        # Walk up to find the repo root (where .git lives or just use parent)
        search = dotenv_path.parent
        gitignore_path: Path | None = None

        # Walk up to find an existing .gitignore or .git directory
        current = search
        while True:
            candidate = current / ".gitignore"
            git_dir = current / ".git"
            if candidate.exists() or git_dir.exists():
                gitignore_path = candidate
                break
            parent = current.parent
            if parent == current:
                break
            current = parent

        if gitignore_path is None:
            # Default: create .gitignore next to the dotenv_path's grandparent
            gitignore_path = dotenv_path.parent.parent / ".gitignore"

        # Compute relative pattern
        try:
            pattern = str(dotenv_path.relative_to(gitignore_path.parent))
        except ValueError:
            pattern = dotenv_path.name

        # Check if already present
        if gitignore_path.exists():
            existing = gitignore_path.read_text()
            if pattern in existing.splitlines():
                return False

        # Append pattern
        with open(gitignore_path, "a") as f:
            f.write(f"{pattern}\n")

        return True
