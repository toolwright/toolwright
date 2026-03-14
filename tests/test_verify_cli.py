"""Tests for verify command surface and report shape."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from tests.helpers import write_demo_toolpack
from toolwright.cli.main import cli
from toolwright.cli.verify import _score_candidate


def test_verify_provenance_generates_report(tmp_path: Path) -> None:
    toolpack = write_demo_toolpack(tmp_path)
    playbook = tmp_path / "playbook.yaml"
    playbook.write_text("version: 1\nstart_url: https://example.com\nsteps: []\n", encoding="utf-8")
    assertions = tmp_path / "assertions.json"
    assertions.write_text(
        json.dumps(
            [
                {
                    "name": "search_results_visible",
                    "locator": {"by": "role", "value": "list"},
                    "expect": {"type": "contains_text", "value": "shoe"},
                }
            ]
        ),
        encoding="utf-8",
    )
    output_dir = tmp_path / "reports"
    runner = CliRunner()

    result = runner.invoke(
        cli,
        [
            "verify",
            "--toolpack",
            str(toolpack),
            "--mode",
            "provenance",
            "--playbook",
            str(playbook),
            "--ui-assertions",
            str(assertions),
            "--output",
            str(output_dir),
            "--strict",
        ],
    )
    assert result.exit_code in {0, 1}
    assert "Verification complete:" in result.stdout
    report = output_dir / "verify_tp_demo.json"
    assert report.exists()
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["provenance"]["status"] in {"pass", "unknown"}
    assert payload["governance_mode"] == "pre-approval"


def test_verify_provenance_requires_inputs(tmp_path: Path) -> None:
    toolpack = write_demo_toolpack(tmp_path)
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "verify",
            "--toolpack",
            str(toolpack),
            "--mode",
            "provenance",
        ],
    )
    assert result.exit_code == 1
    assert "--playbook is required" in result.output


def test_verify_provenance_rejects_unknown_playbook_step(tmp_path: Path) -> None:
    toolpack = write_demo_toolpack(tmp_path)
    playbook = tmp_path / "playbook.yaml"
    playbook.write_text(
        "version: '1.0'\nstart_url: https://example.com\nsteps:\n  - type: hover_magic\n",
        encoding="utf-8",
    )
    assertions = tmp_path / "assertions.json"
    assertions.write_text(
        json.dumps(
            [
                {
                    "name": "search_results_visible",
                    "locator": {"by": "role", "value": "list"},
                    "expect": {"type": "contains_text", "value": "shoe"},
                }
            ]
        ),
        encoding="utf-8",
    )
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "verify",
            "--toolpack",
            str(toolpack),
            "--mode",
            "provenance",
            "--playbook",
            str(playbook),
            "--ui-assertions",
            str(assertions),
        ],
    )
    assert result.exit_code == 3
    assert "unsupported playbook step type" in result.output


def test_verify_provenance_accepts_versioned_assertion_payload(tmp_path: Path) -> None:
    toolpack = write_demo_toolpack(tmp_path)
    playbook = tmp_path / "playbook.yaml"
    playbook.write_text(
        "version: '1.0'\nstart_url: https://example.com\nsteps:\n  - type: goto\n    url: https://example.com/search?q=shoe\n",
        encoding="utf-8",
    )
    assertions = tmp_path / "assertions.yaml"
    assertions.write_text(
        "version: '1.0'\nui_assertions:\n  - name: search_results_visible\n    locator:\n      by: role\n      value: list\n    expect:\n      type: contains_text\n      value: shoe\n",
        encoding="utf-8",
    )
    output_dir = tmp_path / "reports"
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "verify",
            "--toolpack",
            str(toolpack),
            "--mode",
            "provenance",
            "--playbook",
            str(playbook),
            "--ui-assertions",
            str(assertions),
            "--output",
            str(output_dir),
        ],
    )
    assert result.exit_code in {0, 1}
    payload = json.loads((output_dir / "verify_tp_demo.json").read_text(encoding="utf-8"))
    assert payload["provenance"]["playbook_version"] == "1.0"
    assert payload["provenance"]["assertions_version"] == "1.0"


def test_verify_all_without_playbook_gives_clean_error(tmp_path: Path) -> None:
    """--mode all (default) without --playbook should exit 1 with a clear message, not crash."""
    toolpack = write_demo_toolpack(tmp_path)
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "verify",
            "--toolpack",
            str(toolpack),
            "--mode",
            "all",
        ],
    )
    assert result.exit_code == 1
    assert "--playbook is required" in result.output


def test_verify_provenance_without_playbook_gives_clean_error(tmp_path: Path) -> None:
    """--mode provenance without --playbook should exit cleanly with a clear message."""
    toolpack = write_demo_toolpack(tmp_path)
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "verify",
            "--toolpack",
            str(toolpack),
            "--mode",
            "provenance",
        ],
    )
    assert result.exit_code == 1
    assert "--playbook is required" in result.output


def test_verify_contracts_mode_without_playbook_succeeds(tmp_path: Path) -> None:
    """--mode contracts should work fine without --playbook."""
    toolpack = write_demo_toolpack(tmp_path)
    output_dir = tmp_path / "reports"
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "verify",
            "--toolpack",
            str(toolpack),
            "--mode",
            "contracts",
            "--no-strict",
            "--output",
            str(output_dir),
        ],
    )
    # contracts mode doesn't require playbook, so it should not error about playbook
    assert "--playbook is required" not in result.output
    assert "Verification complete:" in result.output


def test_provenance_scoring_does_not_use_assertion_text_as_content_match() -> None:
    action = {
        "tool_id": "tool_tag_manager",
        "name": "get_tag_script",
        "host": "analytics.example.com",
        "path": "/tag-manager/v1/tag.js",
        "method": "GET",
    }
    assertion = {
        "name": "search_results_list",
        "locator": {"by": "text", "value": "laptop"},
        "expect": {"type": "contains_text", "value": "laptop"},
    }

    candidate = _score_candidate(action=action, assertion=assertion, order_index=0)

    assert candidate["signals"]["content_match"] == 0.35
    assert candidate["signals"]["shape_match"] == 0.5
