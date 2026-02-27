"""Tests for toolwright init — project detection, config generation, and initialization."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from toolwright.cli.main import cli
from toolwright.core.init.detector import (
    detect_project,
    generate_config,
    generate_gitignore_entries,
)

# --- Project detection ---

def test_detect_python_project(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text("flask\n")
    result = detect_project(tmp_path)
    assert result.language == "python"
    assert result.package_manager == "pip"
    assert result.project_type == "python"


def test_detect_node_project(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"name": "test"}')
    result = detect_project(tmp_path)
    assert result.language == "javascript"
    assert result.project_type == "node"


def test_detect_go_project(tmp_path: Path) -> None:
    (tmp_path / "go.mod").write_text("module example.com/test\n")
    result = detect_project(tmp_path)
    assert result.language == "go"


def test_detect_rust_project(tmp_path: Path) -> None:
    (tmp_path / "Cargo.toml").write_text("[package]\nname = 'test'\n")
    result = detect_project(tmp_path)
    assert result.language == "rust"


def test_detect_unknown_project(tmp_path: Path) -> None:
    result = detect_project(tmp_path)
    assert result.project_type == "unknown"
    assert result.language == "unknown"


def test_detect_existing_toolwright(tmp_path: Path) -> None:
    (tmp_path / ".toolwright").mkdir()
    result = detect_project(tmp_path)
    assert result.has_existing_toolwright is True


def test_detect_no_existing_toolwright(tmp_path: Path) -> None:
    result = detect_project(tmp_path)
    assert result.has_existing_toolwright is False


# --- API spec detection ---

def test_detect_openapi_yaml(tmp_path: Path) -> None:
    (tmp_path / "openapi.yaml").write_text("openapi: 3.1.0\n")
    result = detect_project(tmp_path)
    assert "openapi.yaml" in result.api_specs


def test_detect_swagger_json(tmp_path: Path) -> None:
    (tmp_path / "swagger.json").write_text('{"swagger": "2.0"}')
    result = detect_project(tmp_path)
    assert "swagger.json" in result.api_specs


def test_detect_api_spec_in_subdirectory(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "openapi.json").write_text("{}")
    result = detect_project(tmp_path)
    assert "docs/openapi.json" in result.api_specs


def test_detect_no_api_specs(tmp_path: Path) -> None:
    result = detect_project(tmp_path)
    assert result.api_specs == []


# --- Framework detection ---

def test_detect_django(tmp_path: Path) -> None:
    (tmp_path / "manage.py").write_text("#!/usr/bin/env python\n")
    result = detect_project(tmp_path)
    assert "django" in result.frameworks


def test_detect_nextjs(tmp_path: Path) -> None:
    (tmp_path / "next.config.js").write_text("module.exports = {}\n")
    result = detect_project(tmp_path)
    assert "nextjs" in result.frameworks


# --- Config generation ---

def test_generate_config_basic() -> None:
    from toolwright.core.init.detector import ProjectDetection

    detection = ProjectDetection(project_type="python", language="python")
    config = generate_config(detection)
    assert config["version"] == "1.0"
    assert config["project"]["type"] == "python"
    assert config["capture"]["default_scope"] == "agent_safe_readonly"


def test_generate_config_with_api_specs() -> None:
    from toolwright.core.init.detector import ProjectDetection

    detection = ProjectDetection(api_specs=["openapi.yaml"])
    config = generate_config(detection)
    assert "openapi_specs" in config["capture"]
    assert "openapi.yaml" in config["capture"]["openapi_specs"]


def test_generate_config_verify_defaults() -> None:
    from toolwright.core.init.detector import ProjectDetection

    config = generate_config(ProjectDetection())
    assert config["verify"]["strict"] is True
    assert config["verify"]["min_confidence"] == 0.6
    assert config["verify"]["unknown_budget"] == 0.3


# --- Gitignore ---

def test_gitignore_entries() -> None:
    entries = generate_gitignore_entries()
    assert any("Toolwright" in e for e in entries)
    assert any("auth/" in e for e in entries)
    assert any("drafts/" in e for e in entries)
    assert any("evidence/" in e for e in entries)


# --- Suggestions ---

def test_suggestions_with_api_spec(tmp_path: Path) -> None:
    (tmp_path / "openapi.yaml").write_text("openapi: 3.1.0\n")
    result = detect_project(tmp_path)
    assert any("toolwright capture import" in s for s in result.suggestions)


def test_suggestions_for_unknown_project(tmp_path: Path) -> None:
    result = detect_project(tmp_path)
    assert any("defaults" in s for s in result.suggestions)


def test_init_shows_all_three_entry_paths(tmp_path: Path) -> None:
    """Init output must show all 3 entry paths so users know how to start."""
    runner = CliRunner()
    result = runner.invoke(cli, ["init", "--directory", str(tmp_path)])

    assert result.exit_code == 0
    # Path 1: "I have a URL" -> toolwright mint
    assert "toolwright mint" in result.output
    # Path 2: "I have a HAR" -> toolwright capture import
    assert "toolwright capture import" in result.output
    # Path 3: "I have an OpenAPI spec" -> toolwright capture import --input-format openapi
    assert "openapi" in result.output.lower()


def test_init_next_steps_use_openapi_command(tmp_path: Path) -> None:
    (tmp_path / "openapi.yaml").write_text("openapi: 3.1.0\n")
    runner = CliRunner()

    result = runner.invoke(cli, ["init", "--directory", str(tmp_path)])

    assert result.exit_code == 0
    assert "toolwright capture import openapi.yaml" in result.output
    assert "--input-format openapi" in result.output
    assert "mint --openapi" not in result.output
    assert "gate allow" in result.output.lower()
    assert "--tools <tools.json>" not in result.output
    assert "--policy <policy.yaml>" not in result.output


# --- demo command in next steps ---

def test_init_next_steps_mention_demo(tmp_path: Path) -> None:
    """Init output must mention 'toolwright demo' so new users discover it."""
    runner = CliRunner()
    result = runner.invoke(cli, ["init", "--directory", str(tmp_path)])

    assert result.exit_code == 0
    assert "toolwright demo" in result.output


def test_init_next_steps_demo_appears_before_mint(tmp_path: Path) -> None:
    """Demo should be the first suggestion (easiest path for new users)."""
    runner = CliRunner()
    result = runner.invoke(cli, ["init", "--directory", str(tmp_path)])

    assert result.exit_code == 0
    demo_pos = result.output.index("toolwright demo")
    mint_pos = result.output.index("toolwright mint")
    assert demo_pos < mint_pos, "toolwright demo should appear before toolwright mint"


# --- to_dict ---

def test_detection_to_dict(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text("flask\n")
    result = detect_project(tmp_path)
    d = result.to_dict()
    assert d["language"] == "python"
    assert isinstance(d["api_specs"], list)
    assert isinstance(d["frameworks"], list)
