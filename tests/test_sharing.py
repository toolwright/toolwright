"""Tests for toolpack sharing (.twp bundles with Ed25519 signing, Sprint 6)."""

from __future__ import annotations

import tarfile
from pathlib import Path

import pytest

from tests.helpers import write_demo_toolpack

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _setup_toolpack(tmp_path: Path) -> Path:
    """Create a minimal toolpack for sharing tests."""
    return write_demo_toolpack(tmp_path)


# ---------------------------------------------------------------------------
# Bundler
# ---------------------------------------------------------------------------


class TestBundler:
    """Package toolpack into .twp (gzipped tar)."""

    def test_create_twp_file(self, tmp_path: Path) -> None:
        """Should create a .twp file."""
        from toolwright.core.share.bundler import create_bundle

        toolpack_path = _setup_toolpack(tmp_path)
        output = create_bundle(toolpack_path, output_dir=tmp_path / "out")
        assert output.suffix == ".twp"
        assert output.exists()

    def test_twp_is_gzipped_tar(self, tmp_path: Path) -> None:
        """The .twp file should be a valid gzipped tar archive."""
        from toolwright.core.share.bundler import create_bundle

        toolpack_path = _setup_toolpack(tmp_path)
        output = create_bundle(toolpack_path, output_dir=tmp_path / "out")
        assert tarfile.is_tarfile(str(output))

    def test_twp_contains_manifest(self, tmp_path: Path) -> None:
        """The .twp file should contain a manifest.json."""
        from toolwright.core.share.bundler import create_bundle

        toolpack_path = _setup_toolpack(tmp_path)
        output = create_bundle(toolpack_path, output_dir=tmp_path / "out")
        with tarfile.open(str(output), "r:gz") as tf:
            names = tf.getnames()
            assert any("manifest.json" in n for n in names)

    def test_twp_contains_toolpack_yaml(self, tmp_path: Path) -> None:
        """The .twp file should contain toolpack.yaml."""
        from toolwright.core.share.bundler import create_bundle

        toolpack_path = _setup_toolpack(tmp_path)
        output = create_bundle(toolpack_path, output_dir=tmp_path / "out")
        with tarfile.open(str(output), "r:gz") as tf:
            names = tf.getnames()
            assert any("toolpack.yaml" in n for n in names)

    def test_twp_contains_signature(self, tmp_path: Path) -> None:
        """The .twp file should contain a signature file."""
        from toolwright.core.share.bundler import create_bundle

        toolpack_path = _setup_toolpack(tmp_path)
        output = create_bundle(toolpack_path, output_dir=tmp_path / "out")
        with tarfile.open(str(output), "r:gz") as tf:
            names = tf.getnames()
            assert any("signature.json" in n for n in names)

    def test_twp_excludes_private_keys(self, tmp_path: Path) -> None:
        """The .twp should never include private key files."""
        from toolwright.core.share.bundler import create_bundle

        toolpack_path = _setup_toolpack(tmp_path)
        # Create a fake private key file
        keys_dir = toolpack_path.parent / "state" / "keys"
        keys_dir.mkdir(parents=True, exist_ok=True)
        (keys_dir / "approval_ed25519_private.pem").write_text("PRIVATE KEY")

        output = create_bundle(toolpack_path, output_dir=tmp_path / "out")
        with tarfile.open(str(output), "r:gz") as tf:
            names = tf.getnames()
            assert not any("private" in n.lower() for n in names)


# ---------------------------------------------------------------------------
# Installer
# ---------------------------------------------------------------------------


class TestInstaller:
    """Install .twp bundles with signature verification."""

    def test_install_extracts_to_target(self, tmp_path: Path) -> None:
        """install_bundle should extract to the target directory."""
        from toolwright.core.share.bundler import create_bundle
        from toolwright.core.share.installer import install_bundle

        toolpack_path = _setup_toolpack(tmp_path)
        twp = create_bundle(toolpack_path, output_dir=tmp_path / "out")

        install_dir = tmp_path / "installed"
        install_bundle(twp, install_dir=install_dir)
        # Should have extracted toolpack.yaml
        assert any(install_dir.rglob("toolpack.yaml"))

    def test_install_verifies_signature(self, tmp_path: Path) -> None:
        """install_bundle should verify the signature."""
        from toolwright.core.share.bundler import create_bundle
        from toolwright.core.share.installer import install_bundle

        toolpack_path = _setup_toolpack(tmp_path)
        twp = create_bundle(toolpack_path, output_dir=tmp_path / "out")

        install_dir = tmp_path / "installed"
        result = install_bundle(twp, install_dir=install_dir)
        assert result.verified is True

    def test_install_rejects_tampered_bundle(self, tmp_path: Path) -> None:
        """Tampered bundles should be rejected."""
        from toolwright.core.share.bundler import create_bundle
        from toolwright.core.share.installer import install_bundle

        toolpack_path = _setup_toolpack(tmp_path)
        twp = create_bundle(toolpack_path, output_dir=tmp_path / "out")

        # Tamper: corrupt the archive by overwriting the middle
        tampered = tmp_path / "tampered.twp"
        data = bytearray(twp.read_bytes())
        mid = len(data) // 2
        for i in range(min(100, len(data) - mid)):
            data[mid + i] = 0xFF
        tampered.write_bytes(bytes(data))

        install_dir = tmp_path / "installed"
        with pytest.raises(ValueError, match="tamper|invalid|corrupt"):
            install_bundle(tampered, install_dir=install_dir)

    def test_round_trip(self, tmp_path: Path) -> None:
        """bundle → install should produce usable toolpack."""
        from toolwright.core.share.bundler import create_bundle
        from toolwright.core.share.installer import install_bundle

        toolpack_path = _setup_toolpack(tmp_path)
        twp = create_bundle(toolpack_path, output_dir=tmp_path / "out")

        install_dir = tmp_path / "installed"
        result = install_bundle(twp, install_dir=install_dir)
        assert result.verified is True

        # The installed toolpack.yaml should exist and be loadable
        installed_yamls = list(install_dir.rglob("toolpack.yaml"))
        assert len(installed_yamls) > 0
