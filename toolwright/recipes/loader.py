"""Load bundled API recipes."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

_RECIPES_DIR = Path(__file__).parent


def _load_yaml_dict(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Recipe file must contain a mapping: {path}")
    return dict(data)


def list_recipes() -> list[dict[str, Any]]:
    """Return metadata for all bundled recipes."""
    results = []
    for path in sorted(_RECIPES_DIR.glob("*.yaml")):
        data = _load_yaml_dict(path)
        results.append({
            "name": data["name"],
            "description": data.get("description", ""),
            "hosts": [h.get("pattern", "") for h in data.get("hosts", [])],
        })
    return results


def load_recipe(name: str) -> dict[str, Any]:
    """Load a recipe by name. Raises ValueError if not found."""
    path = _RECIPES_DIR / f"{name}.yaml"
    if not path.exists():
        available = [p.stem for p in sorted(_RECIPES_DIR.glob("*.yaml"))]
        raise ValueError(
            f"Unknown recipe: {name}. "
            f"Available: {', '.join(available)}"
        )
    return _load_yaml_dict(path)
