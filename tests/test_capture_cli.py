"""CLI tests for capture record Playwright dependency/error handling."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from click.testing import CliRunner

from toolwright.cli.main import cli
from toolwright.models.capture import CaptureSession, CaptureSource, HttpExchange, HTTPMethod


def _session_with_exchange() -> CaptureSession:
    return CaptureSession(
        id="cap_demo",
        name="Demo",
        source=CaptureSource.PLAYWRIGHT,
        created_at=datetime(2026, 2, 6, tzinfo=UTC),
        allowed_hosts=["api.example.com"],
        exchanges=[
            HttpExchange(
                url="https://api.example.com/users",
                method=HTTPMethod.GET,
                host="api.example.com",
                path="/users",
                response_status=200,
            )
        ],
    )


def test_capture_record_missing_playwright_exact_error(monkeypatch) -> None:
    runner = CliRunner()

    async def _raise_import_error(self, *args, **kwargs):  # noqa: ARG001, ANN001
        raise ImportError("No module named 'playwright'")

    monkeypatch.setattr(
        "toolwright.core.capture.playwright_capture.PlaywrightCapture.capture",
        _raise_import_error,
    )

    result = runner.invoke(
        cli,
        [
            "capture",
            "record",
            "https://app.example.com",
            "-a",
            "api.example.com",
        ],
    )

    assert result.exit_code != 0
    assert result.stdout == ""
    assert (
        result.stderr
        == 'Error: Playwright not installed. Install with: pip install "toolwright[playwright]"\n'
    )


def test_capture_record_missing_browsers_exact_error(monkeypatch) -> None:
    runner = CliRunner()

    async def _raise_missing_browser(self, *args, **kwargs):  # noqa: ARG001, ANN001
        raise RuntimeError(
            "BrowserType.launch: Executable doesn't exist at /tmp/chromium "
            "Please run: playwright install chromium"
        )

    monkeypatch.setattr(
        "toolwright.core.capture.playwright_capture.PlaywrightCapture.capture",
        _raise_missing_browser,
    )

    result = runner.invoke(
        cli,
        [
            "capture",
            "record",
            "https://app.example.com",
            "-a",
            "api.example.com",
        ],
    )

    assert result.exit_code != 0
    assert result.stdout == ""
    assert (
        result.stderr
        == "Error: Playwright browsers not installed. Run: playwright install chromium\n"
    )


def test_capture_record_missing_browsers_verbose_still_single_line(monkeypatch) -> None:
    runner = CliRunner()

    async def _raise_missing_browser(self, *args, **kwargs):  # noqa: ARG001, ANN001
        raise RuntimeError("Executable doesn't exist; run playwright install chromium")

    monkeypatch.setattr(
        "toolwright.core.capture.playwright_capture.PlaywrightCapture.capture",
        _raise_missing_browser,
    )

    result = runner.invoke(
        cli,
        [
            "-v",
            "capture",
            "record",
            "https://app.example.com",
            "-a",
            "api.example.com",
        ],
    )

    assert result.exit_code != 0
    assert "Traceback" not in result.stderr
    assert (
        result.stderr
        == "Error: Playwright browsers not installed. Run: playwright install chromium\n"
    )


def test_capture_record_unexpected_error_verbose_shows_traceback(monkeypatch) -> None:
    runner = CliRunner()

    async def _raise_unexpected(self, *args, **kwargs):  # noqa: ARG001, ANN001
        raise RuntimeError("boom")

    monkeypatch.setattr(
        "toolwright.core.capture.playwright_capture.PlaywrightCapture.capture",
        _raise_unexpected,
    )

    result = runner.invoke(
        cli,
        [
            "-v",
            "capture",
            "record",
            "https://app.example.com",
            "-a",
            "api.example.com",
        ],
    )

    assert result.exit_code != 0
    assert "Error during capture: boom" in result.stderr
    assert "Traceback (most recent call last):" in result.stderr


def test_capture_record_success_unchanged(monkeypatch) -> None:
    runner = CliRunner()

    async def _capture(self, *args, **kwargs):  # noqa: ARG001, ANN001
        return _session_with_exchange()

    monkeypatch.setattr(
        "toolwright.core.capture.playwright_capture.PlaywrightCapture.capture",
        _capture,
    )

    result = runner.invoke(
        cli,
        [
            "capture",
            "record",
            "https://app.example.com",
            "-a",
            "api.example.com",
        ],
    )

    assert result.exit_code == 0
    assert "Capture saved: cap_demo" in result.stdout
    assert result.stderr == ""


def _write_otel_export(tmp_path: Path) -> Path:
    payload = {
        "resourceSpans": [
            {
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "traceId": "trace-1",
                                "spanId": "span-1",
                                "attributes": [
                                    {
                                        "key": "http.request.method",
                                        "value": {"stringValue": "GET"},
                                    },
                                    {
                                        "key": "url.full",
                                        "value": {
                                            "stringValue": "https://api.example.com/users"
                                        },
                                    },
                                    {
                                        "key": "http.response.status_code",
                                        "value": {"intValue": "200"},
                                    },
                                ],
                            }
                        ]
                    }
                ]
            }
        ]
    }
    path = tmp_path / "otel-export.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_capture_import_otel_success(tmp_path: Path) -> None:
    runner = CliRunner()
    source = _write_otel_export(tmp_path)
    root = tmp_path / ".toolwright"

    result = runner.invoke(
        cli,
        [
            "--root",
            str(root),
            "capture",
            "import",
            str(source),
            "--input-format",
            "otel",
            "-a",
            "api.example.com",
            "--name",
            "OTEL Import",
        ],
    )

    assert result.exit_code == 0
    assert "Capture saved:" in result.stdout
    assert "Exchanges: 1" in result.stdout
    assert result.stderr == ""


def _write_har_file(tmp_path: Path) -> Path:
    """Write a minimal HAR file for CLI testing."""
    har = {
        "log": {
            "version": "1.2",
            "entries": [
                {
                    "startedDateTime": "2026-02-22T00:00:00.000Z",
                    "request": {
                        "method": "GET",
                        "url": "https://api.example.com/users",
                        "headers": [],
                        "queryString": [],
                        "headersSize": -1,
                        "bodySize": 0,
                    },
                    "response": {
                        "status": 200,
                        "statusText": "OK",
                        "headers": [{"name": "content-type", "value": "application/json"}],
                        "content": {
                            "size": 20,
                            "mimeType": "application/json",
                            "text": json.dumps([{"id": 1, "name": "Alice"}]),
                        },
                        "headersSize": -1,
                        "bodySize": 20,
                    },
                    "_resourceType": "xhr",
                }
            ],
        }
    }
    har_path = tmp_path / "test.har"
    har_path.write_text(json.dumps(har))
    return har_path


def test_capture_import_har_success(tmp_path: Path) -> None:
    """HAR import via CLI should parse and save a capture session."""
    runner = CliRunner()
    source = _write_har_file(tmp_path)
    root = tmp_path / ".toolwright"

    result = runner.invoke(
        cli,
        [
            "--root",
            str(root),
            "capture",
            "import",
            str(source),
            "-a",
            "api.example.com",
            "--name",
            "HAR Import",
        ],
    )

    assert result.exit_code == 0, f"HAR import failed: {result.output}"
    assert "Capture saved:" in result.stdout
    assert "Exchanges: 1" in result.stdout


def test_capture_record_rejects_otel_input_format() -> None:
    runner = CliRunner()

    result = runner.invoke(
        cli,
        [
            "capture",
            "record",
            "https://app.example.com",
            "--input-format",
            "otel",
            "-a",
            "api.example.com",
        ],
    )

    assert result.exit_code != 0
    assert result.stdout == ""
    assert "only supported for 'import'" in result.stderr
