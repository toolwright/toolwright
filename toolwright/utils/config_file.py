"""Load and save .toolwright/config.yaml."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def load_config(root: Path) -> dict[str, Any]:
    """Load .toolwright/config.yaml, returning empty dict if missing."""
    config_path = root / "config.yaml"
    if not config_path.exists():
        return {}
    return yaml.safe_load(config_path.read_text()) or {}


def save_config(root: Path, cfg: dict[str, Any]) -> None:
    """Save config to .toolwright/config.yaml."""
    config_path = root / "config.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(yaml.dump(cfg, default_flow_style=False, sort_keys=False))
