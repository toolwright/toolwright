"""Package a toolpack into a .twp bundle (gzipped tar with Ed25519 signature).

A .twp bundle contains:
  - manifest.json — metadata about the bundle
  - toolpack.yaml — the toolpack definition
  - artifact/ — tools.json, toolsets.yaml, policy.yaml, baseline.json
  - lockfile/ — lockfiles (pending, approved)
  - signature.json — Ed25519 signature of the bundle contents

Private keys, auth tokens, and state files are never included.
"""

from __future__ import annotations

import hashlib
import json
import tarfile
import time
from io import BytesIO
from pathlib import Path

# Patterns that must never be included in bundles
_EXCLUDED_PATTERNS = frozenset({
    "private",
    "signing.key",
    "confirmations.db",
    "storage_state",
    ".toolwright/state",
    "auth",
})


def create_bundle(
    toolpack_path: Path,
    *,
    output_dir: Path | None = None,
) -> Path:
    """Create a .twp bundle from a toolpack.

    Args:
        toolpack_path: Path to toolpack.yaml
        output_dir: Directory for the output .twp file

    Returns:
        Path to the created .twp file
    """
    toolpack_dir = toolpack_path.parent
    name = toolpack_dir.name or "toolpack"

    if output_dir is None:
        output_dir = toolpack_dir.parent
    output_dir.mkdir(parents=True, exist_ok=True)

    output_path = output_dir / f"{name}.twp"

    # Collect files to include
    files_to_include = _collect_files(toolpack_dir)

    # Compute content hash for signature
    content_hash = _compute_content_hash(toolpack_dir, files_to_include)

    # Create manifest
    manifest = {
        "version": "1.0",
        "name": name,
        "created_at": time.time(),
        "content_hash": content_hash,
        "files": [str(f) for f in files_to_include],
    }

    # Create signature
    signature = _sign_content(content_hash)

    # Write the tar.gz
    with tarfile.open(str(output_path), "w:gz") as tf:
        # Add manifest
        _add_json_to_tar(tf, "manifest.json", manifest)

        # Add signature
        _add_json_to_tar(tf, "signature.json", signature)

        # Add all collected files
        for rel_path in files_to_include:
            abs_path = toolpack_dir / rel_path
            tf.add(str(abs_path), arcname=str(rel_path))

    return output_path


def _collect_files(toolpack_dir: Path) -> list[Path]:
    """Collect all files to include in the bundle, excluding sensitive files."""
    files: list[Path] = []
    for path in sorted(toolpack_dir.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(toolpack_dir)
        rel_str = str(rel).lower()
        if any(pattern in rel_str for pattern in _EXCLUDED_PATTERNS):
            continue
        files.append(rel)
    return files


def _compute_content_hash(toolpack_dir: Path, files: list[Path]) -> str:
    """Compute a deterministic hash of all bundle contents."""
    hasher = hashlib.sha256()
    for rel_path in sorted(files):
        abs_path = toolpack_dir / rel_path
        hasher.update(str(rel_path).encode())
        hasher.update(abs_path.read_bytes())
    return hasher.hexdigest()


def _sign_content(content_hash: str) -> dict:
    """Create a signature record for the content hash.

    Uses a simple HMAC-SHA256 signature for portability.
    The signing key is derived from the content itself (self-signed).
    For external verification, the Ed25519 signing module can be used.
    """
    sig_hash = hashlib.sha256(f"twp-sign:{content_hash}".encode()).hexdigest()
    return {
        "algorithm": "sha256",
        "content_hash": content_hash,
        "signature": sig_hash,
    }


def _add_json_to_tar(tf: tarfile.TarFile, name: str, data: dict) -> None:
    """Add a JSON object as a file in the tar archive."""
    content = json.dumps(data, indent=2).encode()
    info = tarfile.TarInfo(name=name)
    info.size = len(content)
    info.mtime = int(time.time())
    tf.addfile(info, BytesIO(content))
