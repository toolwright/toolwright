"""Project type detection — analyze a directory to determine project context."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ProjectDetection:
    """Results of project type detection."""

    project_type: str = "unknown"
    language: str = "unknown"
    package_manager: str = "unknown"
    api_specs: list[str] = field(default_factory=list)
    frameworks: list[str] = field(default_factory=list)
    has_existing_toolwright: bool = False
    suggestions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_type": self.project_type,
            "language": self.language,
            "package_manager": self.package_manager,
            "api_specs": self.api_specs,
            "frameworks": self.frameworks,
            "has_existing_toolwright": self.has_existing_toolwright,
            "suggestions": self.suggestions,
        }


# File patterns → (language, package_manager, project_type)
DETECTION_RULES: list[tuple[str, str, str, str]] = [
    ("requirements.txt", "python", "pip", "python"),
    ("pyproject.toml", "python", "pip", "python"),
    ("Pipfile", "python", "pipenv", "python"),
    ("setup.py", "python", "pip", "python"),
    ("package.json", "javascript", "npm", "node"),
    ("yarn.lock", "javascript", "yarn", "node"),
    ("pnpm-lock.yaml", "javascript", "pnpm", "node"),
    ("Gemfile", "ruby", "bundler", "ruby"),
    ("go.mod", "go", "go-mod", "go"),
    ("Cargo.toml", "rust", "cargo", "rust"),
    ("pom.xml", "java", "maven", "java"),
    ("build.gradle", "java", "gradle", "java"),
    ("build.gradle.kts", "kotlin", "gradle", "kotlin"),
    ("composer.json", "php", "composer", "php"),
    ("mix.exs", "elixir", "mix", "elixir"),
    ("Makefile", "unknown", "make", "unknown"),
]

# API spec file patterns
API_SPEC_PATTERNS: list[str] = [
    "openapi.yaml",
    "openapi.yml",
    "openapi.json",
    "swagger.yaml",
    "swagger.yml",
    "swagger.json",
    "api-spec.yaml",
    "api-spec.json",
]

# Framework detection (file → framework name)
FRAMEWORK_SIGNALS: list[tuple[str, str]] = [
    ("manage.py", "django"),
    ("app.py", "flask"),
    ("next.config.js", "nextjs"),
    ("next.config.mjs", "nextjs"),
    ("next.config.ts", "nextjs"),
    ("nuxt.config.ts", "nuxt"),
    ("angular.json", "angular"),
    ("svelte.config.js", "svelte"),
    ("astro.config.mjs", "astro"),
    ("vite.config.ts", "vite"),
    ("vite.config.js", "vite"),
    # fastapi: detected via dependency files, not a signal file (see _detect_fastapi)
    ("Procfile", "heroku"),
    ("vercel.json", "vercel"),
    ("fly.toml", "fly"),
    ("railway.json", "railway"),
]


def detect_project(directory: Path) -> ProjectDetection:
    """Detect project type, language, and API specs in a directory."""
    result = ProjectDetection()

    # Check for existing .toolwright/
    if (directory / ".toolwright").exists():
        result.has_existing_toolwright = True

    # Detect language and package manager
    for filename, language, pkg_manager, proj_type in DETECTION_RULES:
        if (directory / filename).exists():
            result.language = language
            result.package_manager = pkg_manager
            result.project_type = proj_type
            break

    # Detect API specs
    for spec_name in API_SPEC_PATTERNS:
        if (directory / spec_name).exists():
            result.api_specs.append(spec_name)
        # Also check common subdirectories
        for subdir in ("docs", "api", "spec", "specs"):
            spec_path = directory / subdir / spec_name
            if spec_path.exists():
                result.api_specs.append(f"{subdir}/{spec_name}")

    # Detect frameworks
    for signal_file, framework in FRAMEWORK_SIGNALS:
        if (directory / signal_file).exists() and framework not in result.frameworks:
            result.frameworks.append(framework)

    # Special detection for FastAPI (not a signal file — check deps and imports)
    if "fastapi" not in result.frameworks and _detect_fastapi(directory):
        result.frameworks.append("fastapi")

    # Generate suggestions
    if result.api_specs:
        result.suggestions.append(
            f"Found API spec(s): {', '.join(result.api_specs)}. "
            "Consider running: toolwright create --spec <path>"
        )
    if not result.has_existing_toolwright:
        result.suggestions.append("Will create .toolwright/ directory with starter config")
    if result.project_type == "unknown":
        result.suggestions.append("Could not detect project type — using defaults")

    return result


def generate_config(detection: ProjectDetection) -> dict[str, Any]:
    """Generate a starter config.yaml based on project detection."""
    config: dict[str, Any] = {
        "version": "1.0",
        "project": {
            "type": detection.project_type,
            "language": detection.language,
        },
        "capture": {
            "default_scope": "agent_safe_readonly",
            "redaction": "default_safe",
        },
        "verify": {
            "strict": True,
            "min_confidence": 0.6,
            "unknown_budget": 0.3,
        },
    }

    if detection.api_specs:
        config["capture"]["openapi_specs"] = detection.api_specs

    return config


def generate_gitignore_entries() -> list[str]:
    """Generate .gitignore entries for Toolwright."""
    return [
        "# Toolwright",
        ".toolwright/captures/",
        ".toolwright/state/",
        ".toolwright/audit.log.jsonl",
        "auth/",
        "drafts/",
        "evidence/",
    ]


def _detect_fastapi(directory: Path) -> bool:
    """Detect FastAPI via dependency files or Python imports."""
    import re

    # Pattern matches "fastapi" as a standalone package name in dependency lists
    dep_pattern = re.compile(r"(?:^|\s|[\"',])fastapi(?:[><=!~\s\"',\]]|$)", re.IGNORECASE)

    # Check requirements.txt
    req_path = directory / "requirements.txt"
    if req_path.exists():
        try:
            content = req_path.read_text(encoding="utf-8")
            for line in content.splitlines():
                stripped = line.strip()
                if stripped and not stripped.startswith("#") and re.match(
                    r"^fastapi\b", stripped, re.IGNORECASE
                ):
                    return True
        except OSError:
            pass

    # Check pyproject.toml
    pyproject_path = directory / "pyproject.toml"
    if pyproject_path.exists():
        try:
            content = pyproject_path.read_text(encoding="utf-8")
            if dep_pattern.search(content):
                return True
        except OSError:
            pass

    # Check Pipfile
    pipfile_path = directory / "Pipfile"
    if pipfile_path.exists():
        try:
            content = pipfile_path.read_text(encoding="utf-8")
            if dep_pattern.search(content):
                return True
        except OSError:
            pass

    # Check common entry point files for FastAPI imports
    for filename in ("main.py", "app.py", "api.py", "server.py"):
        py_path = directory / filename
        if py_path.exists():
            try:
                content = py_path.read_text(encoding="utf-8")
                if re.search(r"(?:from|import)\s+fastapi\b", content):
                    return True
            except OSError:
                pass

    return False
