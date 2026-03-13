"""Tests for cross-platform compatibility fixes (Phase 2)."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


class TestPidAlive:
    """Cross-platform PID liveness check."""

    def test_current_pid_alive(self) -> None:
        from toolwright.utils.locks import _pid_alive

        assert _pid_alive(os.getpid()) is True

    def test_dead_pid_not_alive(self) -> None:
        from toolwright.utils.locks import _pid_alive

        assert _pid_alive(99999999) is False

    def test_zero_pid_not_alive(self) -> None:
        from toolwright.utils.locks import _pid_alive

        assert _pid_alive(0) is False

    def test_negative_pid_not_alive(self) -> None:
        from toolwright.utils.locks import _pid_alive

        assert _pid_alive(-1) is False


class TestFsyncDirectory:
    """_fsync_directory should not raise on any platform."""

    def test_fsync_real_directory(self) -> None:
        from toolwright.utils.files import _fsync_directory

        with tempfile.TemporaryDirectory() as td:
            _fsync_directory(Path(td))  # Should not raise


class TestResolveApprover:
    """resolve_approver uses getpass.getuser() (cross-platform)."""

    def test_resolve_approver_no_actor(self) -> None:
        import getpass

        from toolwright.core.approval.signing import resolve_approver

        result = resolve_approver(None)
        assert result == getpass.getuser()
        assert result != "unknown"  # Should not fall back to "unknown"

    def test_resolve_approver_explicit_actor(self) -> None:
        from toolwright.core.approval.signing import resolve_approver

        result = resolve_approver("admin@example.com")
        assert result == "admin@example.com"


class TestConfigPathExpansion:
    """Config path expansion handles %APPDATA% on Windows."""

    def test_expandvars_in_config_path(self) -> None:
        """Verify os.path.expandvars is used for Windows paths."""
        import inspect

        import toolwright.ui.flows.config as config_mod

        source = inspect.getsource(config_mod)
        assert "expandvars" in source, (
            "config.py must use os.path.expandvars to handle %APPDATA%"
        )


class TestPythonVersionGuard:
    """Python version is guarded via requires-python in pyproject.toml."""

    def test_requires_python_in_pyproject(self) -> None:
        """pyproject.toml must declare requires-python >= 3.11."""
        from pathlib import Path

        root = Path(__file__).resolve().parent.parent
        pyproject = root / "pyproject.toml"
        content = pyproject.read_text(encoding="utf-8")
        assert 'requires-python = ">=3.11"' in content
