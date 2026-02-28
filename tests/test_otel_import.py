"""Round-trip test for OTEL import via the CLI.

Writes a minimal OTEL trace JSON file, invokes `capture import --input-format otel`,
then loads the saved capture back from disk and verifies the exchange data.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from click.testing import CliRunner

from toolwright.cli.main import cli
from toolwright.models.capture import CaptureSource, HTTPMethod
from toolwright.storage.filesystem import Storage


def _minimal_otel_payload() -> dict:
    """Return a minimal OTLP JSON export with two HTTP spans and one non-HTTP span."""
    return {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [
                        {"key": "service.name", "value": {"stringValue": "my-service"}}
                    ]
                },
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "traceId": "aaaa1111",
                                "spanId": "span-get",
                                "kind": "SPAN_KIND_CLIENT",
                                "startTimeUnixNano": "1700000000000000000",
                                "endTimeUnixNano": "1700000000200000000",
                                "attributes": [
                                    {
                                        "key": "http.request.method",
                                        "value": {"stringValue": "GET"},
                                    },
                                    {
                                        "key": "url.full",
                                        "value": {
                                            "stringValue": "https://api.example.com/v1/items"
                                        },
                                    },
                                    {
                                        "key": "http.response.status_code",
                                        "value": {"intValue": "200"},
                                    },
                                ],
                            },
                            {
                                "traceId": "aaaa1111",
                                "spanId": "span-post",
                                "kind": "SPAN_KIND_CLIENT",
                                "startTimeUnixNano": "1700000000300000000",
                                "endTimeUnixNano": "1700000000600000000",
                                "attributes": [
                                    {
                                        "key": "http.request.method",
                                        "value": {"stringValue": "POST"},
                                    },
                                    {
                                        "key": "url.full",
                                        "value": {
                                            "stringValue": "https://api.example.com/v1/items"
                                        },
                                    },
                                    {
                                        "key": "http.response.status_code",
                                        "value": {"intValue": "201"},
                                    },
                                    {
                                        "key": "http.request.body",
                                        "value": {
                                            "stringValue": '{"name": "widget"}'
                                        },
                                    },
                                ],
                            },
                            # Non-HTTP span -- should be filtered out
                            {
                                "traceId": "aaaa1111",
                                "spanId": "span-db",
                                "kind": "SPAN_KIND_CLIENT",
                                "attributes": [
                                    {
                                        "key": "db.system",
                                        "value": {"stringValue": "postgresql"},
                                    }
                                ],
                            },
                        ]
                    }
                ],
            }
        ]
    }


def test_otel_import_round_trip(tmp_path: Path) -> None:
    """Import OTEL trace JSON via CLI, then load from disk and verify exchanges."""
    # Arrange: write OTEL export to a temp file
    otel_file = tmp_path / "traces.json"
    otel_file.write_text(json.dumps(_minimal_otel_payload()), encoding="utf-8")

    root = tmp_path / ".toolwright"
    runner = CliRunner()

    # Act: invoke capture import
    result = runner.invoke(
        cli,
        [
            "--root",
            str(root),
            "capture",
            "import",
            str(otel_file),
            "--input-format",
            "otel",
            "-a",
            "api.example.com",
            "--name",
            "otel-round-trip",
        ],
    )

    # Assert: CLI succeeded
    assert result.exit_code == 0, f"CLI failed:\nstdout={result.stdout}\nstderr={result.stderr}"
    assert "Capture saved:" in result.stdout
    assert "Exchanges: 2" in result.stdout

    # Extract the capture ID from CLI output (e.g. "Capture saved: cap_xxx")
    match = re.search(r"Capture saved:\s+(\S+)", result.stdout)
    assert match, f"Could not extract capture ID from output: {result.stdout}"
    capture_id = match.group(1)

    # Round-trip: load the saved capture from disk
    storage = Storage(base_path=root)
    session = storage.load_capture(capture_id)
    assert session is not None, f"Could not load capture {capture_id} from {root}"

    # Verify session metadata
    assert session.name == "otel-round-trip"
    assert session.source == CaptureSource.OTEL
    assert len(session.exchanges) == 2

    # Verify first exchange (GET)
    get_ex = session.exchanges[0]
    assert get_ex.method == HTTPMethod.GET
    assert get_ex.url == "https://api.example.com/v1/items"
    assert get_ex.host == "api.example.com"
    assert get_ex.path == "/v1/items"
    assert get_ex.response_status == 200
    assert get_ex.duration_ms == 200.0

    # Verify second exchange (POST)
    post_ex = session.exchanges[1]
    assert post_ex.method == HTTPMethod.POST
    assert post_ex.url == "https://api.example.com/v1/items"
    assert post_ex.response_status == 201
    assert post_ex.request_body == '{"name": "widget"}'
    assert post_ex.duration_ms == 300.0


def test_otel_import_filters_non_allowed_hosts(tmp_path: Path) -> None:
    """OTEL spans for hosts not in --allowed-hosts should be filtered out."""
    payload = {
        "resourceSpans": [
            {
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "traceId": "bbbb2222",
                                "spanId": "span-allowed",
                                "attributes": [
                                    {
                                        "key": "http.request.method",
                                        "value": {"stringValue": "GET"},
                                    },
                                    {
                                        "key": "url.full",
                                        "value": {
                                            "stringValue": "https://api.example.com/data"
                                        },
                                    },
                                ],
                            },
                            {
                                "traceId": "bbbb2222",
                                "spanId": "span-blocked",
                                "attributes": [
                                    {
                                        "key": "http.request.method",
                                        "value": {"stringValue": "GET"},
                                    },
                                    {
                                        "key": "url.full",
                                        "value": {
                                            "stringValue": "https://other.example.com/data"
                                        },
                                    },
                                ],
                            },
                        ]
                    }
                ]
            }
        ]
    }

    otel_file = tmp_path / "traces.json"
    otel_file.write_text(json.dumps(payload), encoding="utf-8")
    root = tmp_path / ".toolwright"
    runner = CliRunner()

    result = runner.invoke(
        cli,
        [
            "--root",
            str(root),
            "capture",
            "import",
            str(otel_file),
            "--input-format",
            "otel",
            "-a",
            "api.example.com",
        ],
    )

    assert result.exit_code == 0
    assert "Exchanges: 1" in result.stdout

    # Load and verify only the allowed-host exchange survived
    match = re.search(r"Capture saved:\s+(\S+)", result.stdout)
    assert match
    session = Storage(base_path=root).load_capture(match.group(1))
    assert session is not None
    assert len(session.exchanges) == 1
    assert session.exchanges[0].host == "api.example.com"


def test_otel_import_missing_file(tmp_path: Path) -> None:
    """Importing a non-existent OTEL file should fail gracefully."""
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "--root",
            str(tmp_path / ".toolwright"),
            "capture",
            "import",
            str(tmp_path / "does-not-exist.json"),
            "--input-format",
            "otel",
            "-a",
            "api.example.com",
        ],
    )
    assert result.exit_code != 0
    assert "not found" in result.stderr.lower() or "not found" in result.stdout.lower()
