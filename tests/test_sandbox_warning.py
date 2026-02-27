"""Tests for macOS sandbox path warning.

Claude Desktop on macOS sandboxes processes. Toolpacks under ~/Documents,
~/Desktop, or ~/Downloads will fail with opaque permission errors.
"""

from pathlib import Path
from unittest.mock import patch

from toolwright.utils.state import warn_if_sandboxed_path


class TestSandboxWarning:
    """warn_if_sandboxed_path should warn for macOS-sandboxed directories."""

    def test_documents_path_warns_on_darwin(self) -> None:
        """Path under ~/Documents should trigger warning on macOS."""
        path = Path.home() / "Documents" / "myproject" / "toolpack.yaml"
        with patch("click.echo") as mock_echo:
            warn_if_sandboxed_path(path, platform="darwin")
        assert mock_echo.called, "Should warn for ~/Documents on darwin"
        warning_text = mock_echo.call_args.args[0]
        assert "Documents" in warning_text

    def test_desktop_path_warns_on_darwin(self) -> None:
        """Path under ~/Desktop should trigger warning on macOS."""
        path = Path.home() / "Desktop" / "toolpack.yaml"
        with patch("click.echo") as mock_echo:
            warn_if_sandboxed_path(path, platform="darwin")
        assert mock_echo.called, "Should warn for ~/Desktop on darwin"

    def test_downloads_path_warns_on_darwin(self) -> None:
        """Path under ~/Downloads should trigger warning on macOS."""
        path = Path.home() / "Downloads" / "api-pack" / "toolpack.yaml"
        with patch("click.echo") as mock_echo:
            warn_if_sandboxed_path(path, platform="darwin")
        assert mock_echo.called, "Should warn for ~/Downloads on darwin"

    def test_safe_path_no_warning(self) -> None:
        """Path outside sandboxed dirs should not trigger warning."""
        path = Path.home() / "projects" / "myapi" / "toolpack.yaml"
        with patch("click.echo") as mock_echo:
            warn_if_sandboxed_path(path, platform="darwin")
        assert not mock_echo.called, "Should not warn for safe path"

    def test_linux_platform_no_warning(self) -> None:
        """Even sandboxed-looking paths should not warn on Linux."""
        path = Path.home() / "Documents" / "toolpack.yaml"
        with patch("click.echo") as mock_echo:
            warn_if_sandboxed_path(path, platform="linux")
        assert not mock_echo.called, "Should not warn on Linux"

    def test_relative_path_resolved(self) -> None:
        """Relative paths should be resolved before checking."""
        # A relative path that won't match any sandboxed dir
        path = Path("./some/local/toolpack.yaml")
        with patch("click.echo") as mock_echo:
            warn_if_sandboxed_path(path, platform="darwin")
        assert not mock_echo.called, "Relative safe path should not warn"
