"""Shared project-initialization service for CLI and UI flows."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from toolwright.core.init.detector import (
    ProjectDetection,
    detect_project,
    generate_config,
    generate_gitignore_entries,
)


@dataclass(frozen=True)
class InitProjectResult:
    """Structured result for Toolwright project initialization."""

    project_dir: Path
    toolwright_dir: Path
    config_path: Path
    detection: ProjectDetection
    created: bool


def initialize_project(directory: str | Path) -> InitProjectResult:
    """Initialize Toolwright in a project directory without printing."""
    project_dir = Path(directory).resolve()
    if not project_dir.exists():
        raise FileNotFoundError(f"Directory not found: {project_dir}")

    detection = detect_project(project_dir)
    toolwright_dir = project_dir / ".toolwright"
    config_path = toolwright_dir / "config.yaml"

    if detection.has_existing_toolwright:
        return InitProjectResult(
            project_dir=project_dir,
            toolwright_dir=toolwright_dir,
            config_path=config_path,
            detection=detection,
            created=False,
        )

    toolwright_dir.mkdir(parents=True, exist_ok=True)
    (toolwright_dir / "captures").mkdir(exist_ok=True)
    (toolwright_dir / "artifacts").mkdir(exist_ok=True)
    (toolwright_dir / "reports").mkdir(exist_ok=True)

    config = generate_config(detection)
    config_path.write_text(yaml.dump(config, sort_keys=False), encoding="utf-8")

    gitignore_path = project_dir / ".gitignore"
    gitignore_entries = generate_gitignore_entries()
    if gitignore_path.exists():
        existing = gitignore_path.read_text(encoding="utf-8")
        if "# Toolwright" not in existing:
            with open(gitignore_path, "a", encoding="utf-8") as f:
                f.write("\n" + "\n".join(gitignore_entries) + "\n")
    else:
        gitignore_path.write_text("\n".join(gitignore_entries) + "\n", encoding="utf-8")

    return InitProjectResult(
        project_dir=project_dir,
        toolwright_dir=toolwright_dir,
        config_path=config_path,
        detection=detection,
        created=True,
    )
