"""Tests for the share and install CLI commands (Phase 3.4)."""

from __future__ import annotations

import tempfile
from pathlib import Path

from click.testing import CliRunner

from toolwright.cli.main import cli


def _make_toolpack(parent: Path) -> Path:
    """Create a minimal toolpack directory with a toolpack.yaml and artifacts."""
    tp_dir = parent / "my-toolpack"
    tp_dir.mkdir()
    (tp_dir / "toolpack.yaml").write_text(
        "toolpack_id: test\nallowed_hosts: []\n"
    )
    artifact_dir = tp_dir / "artifact"
    artifact_dir.mkdir()
    (artifact_dir / "tools.json").write_text('{"actions": []}')
    return tp_dir


class TestShareInstallRoundtrip:
    """Round-trip: share a toolpack, then install the .twp bundle."""

    def test_share_creates_twp(self) -> None:
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as td:
            tp_dir = _make_toolpack(Path(td))
            result = runner.invoke(
                cli, ["share", str(tp_dir / "toolpack.yaml")]
            )
            assert result.exit_code == 0, result.output
            assert "Created" in result.output
            twp_files = list(Path(td).glob("*.twp"))
            assert len(twp_files) == 1

    def test_share_with_output_dir(self) -> None:
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as td:
            tp_dir = _make_toolpack(Path(td))
            out_dir = Path(td) / "bundles"
            out_dir.mkdir()
            result = runner.invoke(
                cli,
                [
                    "share",
                    str(tp_dir / "toolpack.yaml"),
                    "--output",
                    str(out_dir),
                ],
            )
            assert result.exit_code == 0, result.output
            assert "Created" in result.output
            twp_files = list(out_dir.glob("*.twp"))
            assert len(twp_files) == 1

    def test_install_from_twp(self) -> None:
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as td:
            tp_dir = _make_toolpack(Path(td))
            # First share
            runner.invoke(cli, ["share", str(tp_dir / "toolpack.yaml")])
            twp_files = list(Path(td).glob("*.twp"))
            assert len(twp_files) == 1

            # Then install
            install_dir = Path(td) / "installed"
            result = runner.invoke(
                cli,
                ["install", str(twp_files[0]), "--target", str(install_dir)],
            )
            assert result.exit_code == 0, result.output
            assert "Installed" in result.output
            assert "Files:" in result.output

    def test_roundtrip_preserves_files(self) -> None:
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as td:
            tp_dir = _make_toolpack(Path(td))
            original_yaml = (tp_dir / "toolpack.yaml").read_text()
            original_tools = (tp_dir / "artifact" / "tools.json").read_text()

            # Share
            result = runner.invoke(
                cli, ["share", str(tp_dir / "toolpack.yaml")]
            )
            assert result.exit_code == 0

            twp_files = list(Path(td).glob("*.twp"))
            assert len(twp_files) == 1

            # Install
            install_dir = Path(td) / "installed"
            result = runner.invoke(
                cli,
                ["install", str(twp_files[0]), "--target", str(install_dir)],
            )
            assert result.exit_code == 0

            # Verify file content is preserved
            installed_yaml = (install_dir / "toolpack.yaml").read_text()
            installed_tools = (
                install_dir / "artifact" / "tools.json"
            ).read_text()
            assert installed_yaml == original_yaml
            assert installed_tools == original_tools


class TestShareErrors:
    """Error handling for the share command."""

    def test_share_nonexistent_path(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["share", "/no/such/path/toolpack.yaml"])
        assert result.exit_code != 0

    def test_share_shows_size(self) -> None:
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as td:
            tp_dir = _make_toolpack(Path(td))
            result = runner.invoke(
                cli, ["share", str(tp_dir / "toolpack.yaml")]
            )
            assert result.exit_code == 0
            # Should show size like "0.3 KB" or similar
            assert "KB" in result.output or "MB" in result.output


class TestInstallErrors:
    """Error handling for the install command."""

    def test_install_nonexistent_path(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["install", "/no/such/bundle.twp"])
        assert result.exit_code != 0

    def test_install_corrupt_file(self) -> None:
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as td:
            corrupt = Path(td) / "corrupt.twp"
            corrupt.write_text("not a valid tarfile")
            result = runner.invoke(cli, ["install", str(corrupt)])
            # Should fail with non-zero exit code
            assert result.exit_code != 0


class TestHelpOutput:
    """Commands appear in help output."""

    def test_share_in_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert "share" in result.output

    def test_install_in_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert "install" in result.output

    def test_share_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["share", "--help"])
        assert result.exit_code == 0
        assert "Package a toolpack" in result.output

    def test_install_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["install", "--help"])
        assert result.exit_code == 0
        assert "Verify and install" in result.output
