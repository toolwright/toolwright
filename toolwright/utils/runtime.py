"""Runtime environment helpers."""

from __future__ import annotations

import re
import shutil

_STABLE_VERSION_RE = re.compile(r"^\\d+(?:\\.\\d+)*$")


def is_stable_release(version: str) -> bool:
    """Return True if version looks like a stable PEP440 release."""
    return bool(_STABLE_VERSION_RE.match(version.strip()))


def docker_available() -> bool:
    """Return True if docker is available in PATH."""
    return shutil.which("docker") is not None
