"""Load bundled API recipes."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

_RECIPES_DIR = Path(__file__).parent


def list_recipes() -> list[dict[str, Any]]:
    """Return metadata for all bundled recipes."""
    results = []
    for path in sorted(_RECIPES_DIR.glob("*.yaml")):
        with open(path) as f:
            data = yaml.safe_load(f)
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
    with open(path) as f:
        return yaml.safe_load(f)
