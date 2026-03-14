"""Tests for spec parsing error handling (C2).

Invalid specs must produce clean click.ClickException errors, never raw tracebacks.
"""

from __future__ import annotations

import json
from pathlib import Path

import click
import pytest


def _run_create_with_spec(tmp_path: Path, content: str, suffix: str = ".yaml") -> None:
    from toolwright.cli.commands_create import run_create

    spec_path = tmp_path / f"spec{suffix}"
    spec_path.write_text(content)

    run_create(
        api_name=None,
        spec=str(spec_path),
        name="test",
        auto_approve=True,
        apply_rules=False,
        output_root=str(tmp_path / ".toolwright"),
        verbose=False,
    )


class TestInvalidSpecErrorHandling:
    """C2: malformed specs must produce clean error messages."""

    def test_invalid_yaml_syntax(self, tmp_path: Path) -> None:
        """Invalid YAML should raise ClickException with a clean message."""
        with pytest.raises(click.ClickException, match="(?i)(yaml|parse|spec)"):
            _run_create_with_spec(tmp_path, "{{{{not: valid: yaml: [")

    def test_plain_text_file(self, tmp_path: Path) -> None:
        """A plain text file should raise ClickException."""
        with pytest.raises(click.ClickException):
            _run_create_with_spec(tmp_path, "This is just plain text, not a spec.")

    def test_swagger_2_spec(self, tmp_path: Path) -> None:
        """Swagger 2.0 spec should raise ClickException about unsupported version."""
        swagger_spec = json.dumps({
            "swagger": "2.0",
            "info": {"title": "Old API", "version": "1.0"},
            "paths": {},
        })
        with pytest.raises(click.ClickException, match="(?i)(swagger|2.0|supported|parse|spec|failed)"):
            _run_create_with_spec(tmp_path, swagger_spec, suffix=".json")

    def test_empty_json_object(self, tmp_path: Path) -> None:
        """Empty JSON should raise ClickException about missing fields."""
        with pytest.raises(click.ClickException, match="(?i)(missing|field|parse|spec|failed)"):
            _run_create_with_spec(tmp_path, "{}", suffix=".json")

    def test_json_array_instead_of_object(self, tmp_path: Path) -> None:
        """A JSON array should raise ClickException about malformed structure."""
        with pytest.raises(click.ClickException):
            _run_create_with_spec(tmp_path, "[]", suffix=".json")

    def test_binary_content(self, tmp_path: Path) -> None:
        """Binary content should raise ClickException."""
        spec_path = tmp_path / "spec.yaml"
        spec_path.write_bytes(b"\x00\x01\x02\x03\xff\xfe")
        with pytest.raises((click.ClickException, UnicodeDecodeError)):
            from toolwright.cli.commands_create import run_create

            run_create(
                api_name=None,
                spec=str(spec_path),
                name="test",
                auto_approve=True,
                apply_rules=False,
                output_root=str(tmp_path / ".toolwright"),
                verbose=False,
            )
