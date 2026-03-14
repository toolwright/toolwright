"""Install a .twp bundle with signature verification.

Extracts a .twp bundle (gzipped tar) to a target directory, verifying the
content hash and signature before accepting the contents.
"""

from __future__ import annotations

import hashlib
import json
import tarfile
from dataclasses import dataclass
from pathlib import Path


@dataclass
class InstallResult:
    """Result of installing a .twp bundle."""

    verified: bool
    name: str = ""
    files: list[str] | None = None


def install_bundle(
    twp_path: Path,
    *,
    install_dir: Path,
) -> InstallResult:
    """Install a .twp bundle to the target directory.

    Args:
        twp_path: Path to the .twp file
        install_dir: Directory to extract into

    Returns:
        InstallResult with verification status

    Raises:
        ValueError: If the bundle is corrupt or tampered
    """
    try:
        tf = tarfile.open(str(twp_path), "r:gz")  # noqa: SIM115 — opened here, used as context manager below
    except (tarfile.TarError, EOFError) as exc:
        raise ValueError(f"corrupt or invalid bundle: {exc}") from exc

    with tf:
        # Read signature
        try:
            sig_member = tf.getmember("signature.json")
        except KeyError as exc:
            raise ValueError("invalid bundle: missing signature.json") from exc

        sig_file = tf.extractfile(sig_member)
        if sig_file is None:
            raise ValueError("invalid bundle: cannot read signature.json")
        signature = json.loads(sig_file.read())

        # Read manifest
        try:
            manifest_member = tf.getmember("manifest.json")
        except KeyError as exc:
            raise ValueError("invalid bundle: missing manifest.json") from exc

        manifest_file = tf.extractfile(manifest_member)
        if manifest_file is None:
            raise ValueError("invalid bundle: cannot read manifest.json")
        manifest = json.loads(manifest_file.read())

        # Verify signature against content hash
        content_hash = signature.get("content_hash", "")
        expected_sig = hashlib.sha256(f"twp-sign:{content_hash}".encode()).hexdigest()
        if signature.get("signature") != expected_sig:
            raise ValueError("tampered bundle: signature verification failed")

        # Verify manifest content hash matches signature
        if manifest.get("content_hash") != content_hash:
            raise ValueError("tampered bundle: manifest hash mismatch")

        # Verify content files against the hash before extracting
        content_members = [
            m for m in tf.getmembers()
            if m.name not in ("manifest.json", "signature.json")
        ]
        hasher = hashlib.sha256()
        for member in sorted(content_members, key=lambda m: m.name):
            f = tf.extractfile(member)
            if f is None:
                continue
            hasher.update(member.name.encode())
            hasher.update(f.read())
        actual_hash = hasher.hexdigest()
        if actual_hash != content_hash:
            raise ValueError("tampered bundle: content hash mismatch")

        # Extract content files (exclude manifest and signature)
        install_dir.mkdir(parents=True, exist_ok=True)
        for member in content_members:
            tf.extract(member, path=str(install_dir), filter="data")

    return InstallResult(
        verified=True,
        name=manifest.get("name", ""),
        files=manifest.get("files", []),
    )
