"""Tests for --load-storage-state / --save-storage-state capture CLI flags."""

from unittest.mock import patch

from click.testing import CliRunner

from toolwright.cli.main import cli


class TestStorageStateCLIFlags:
    """Tests for storage state CLI flag validation."""

    @patch("toolwright.cli.capture.run_capture")
    def test_capture_record_accepts_load_storage_state(self, mock_run):
        """--load-storage-state flag should be accepted by capture record."""
        runner = CliRunner()
        # Create a temp file for load-storage-state (exists=True validation)
        import tempfile
        from pathlib import Path

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            f.write(b'{"cookies": []}')
            state_path = f.name

        try:
            result = runner.invoke(
                cli,
                [
                    "capture", "record", "https://example.com",
                    "-a", "example.com",
                    "--load-storage-state", state_path,
                ],
            )
            assert "No such option" not in (result.output or "")
            assert result.exit_code == 0
            # Verify the parameter was passed through
            mock_run.assert_called_once()
            _, kwargs = mock_run.call_args
            assert kwargs.get("load_storage_state") == state_path
        finally:
            Path(state_path).unlink(missing_ok=True)

    @patch("toolwright.cli.capture.run_capture")
    def test_capture_record_accepts_save_storage_state(self, _mock_run):
        """--save-storage-state flag should be accepted by capture record."""
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "capture", "record", "https://example.com",
                "-a", "example.com",
                "--save-storage-state", "/tmp/out_state.json",
            ],
        )
        assert "No such option" not in (result.output or "")
        assert result.exit_code == 0

    def test_load_storage_state_must_exist(self):
        """--load-storage-state should error if file doesn't exist."""
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "capture", "record", "https://example.com",
                "-a", "example.com",
                "--load-storage-state", "/nonexistent/state.json",
            ],
        )
        assert result.exit_code != 0


class TestPlaywrightCaptureStorageState:
    """Tests for storage state parameter passing to PlaywrightCapture."""

    def test_storage_state_passed_to_context(self):
        """PlaywrightCapture should accept and store storage_state_path."""
        from toolwright.core.capture.playwright_capture import PlaywrightCapture

        capture = PlaywrightCapture(
            allowed_hosts=["example.com"],
            storage_state_path="/tmp/state.json",
        )
        assert capture.storage_state_path == "/tmp/state.json"

    def test_storage_state_default_none(self):
        """PlaywrightCapture should default storage_state_path to None."""
        from toolwright.core.capture.playwright_capture import PlaywrightCapture

        capture = PlaywrightCapture(allowed_hosts=["example.com"])
        assert capture.storage_state_path is None

    def test_save_storage_state_path(self):
        """PlaywrightCapture should accept save_storage_state_path."""
        from toolwright.core.capture.playwright_capture import PlaywrightCapture

        capture = PlaywrightCapture(
            allowed_hosts=["example.com"],
            save_storage_state_path="/tmp/out_state.json",
        )
        assert capture.save_storage_state_path == "/tmp/out_state.json"
