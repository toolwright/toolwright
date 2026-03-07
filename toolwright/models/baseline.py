"""Baseline models for traffic-captured tool drift detection.

Stores per-tool response shape baselines and probe templates
in baselines.json alongside tools.json in the toolpack directory.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from toolwright.models.probe_template import ProbeTemplate
from toolwright.models.shape import ShapeModel


@dataclass
class ToolBaseline:
    """Stored baseline for a single traffic-captured tool."""

    shape: ShapeModel
    probe_template: ProbeTemplate
    content_hash: str
    source: str  # "har", "browser", "curl", "passive"

    def to_dict(self) -> dict[str, Any]:
        return {
            "shape": self.shape.to_dict(),
            "probe_template": self.probe_template.to_dict(),
            "content_hash": self.content_hash,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ToolBaseline:
        shape = ShapeModel.from_dict(data["shape"])
        return cls(
            shape=shape,
            probe_template=ProbeTemplate.from_dict(data["probe_template"]),
            content_hash=data.get("content_hash", shape.content_hash()),
            source=data.get("source", "unknown"),
        )


@dataclass
class BaselineIndex:
    """All baselines for a toolpack.

    CONCURRENCY: The reconciliation loop can trigger multiple merges from
    concurrent drift probes. All writes to baselines.json go through save(),
    which uses a lock and atomic file replacement to prevent corruption.
    """

    version: int = 1
    baselines: dict[str, ToolBaseline] = field(default_factory=dict)
    _save_lock: threading.Lock = field(
        default_factory=threading.Lock, repr=False
    )

    def save(self, path: Path) -> None:
        """Atomically save baselines to disk.

        Uses a single-writer lock to prevent concurrent saves from
        corrupting the file. Writes to a temp file first, then does
        an atomic rename.
        """
        with self._save_lock:
            snapshot = self._snapshot_baselines()
            data = {
                "version": self.version,
                "baselines": {tool_id: baseline.to_dict() for tool_id, baseline in snapshot},
            }
            serialized = json.dumps(data, indent=2)
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = path.with_suffix(".json.tmp")
            tmp_path.write_text(serialized)
            tmp_path.replace(path)

    def _snapshot_baselines(self) -> list[tuple[str, ToolBaseline]]:
        """Capture a stable snapshot even if another thread is adding entries.

        Some callers mutate ``baselines`` directly. A short retry loop prevents
        ``RuntimeError: dictionary changed size during iteration`` while save()
        is serializing a best-effort on-disk snapshot.
        """
        while True:
            try:
                return list(self.baselines.items())
            except RuntimeError:
                time.sleep(0)

    @classmethod
    def load(cls, path: Path) -> BaselineIndex:
        if not path.exists():
            return cls()
        data = json.loads(path.read_text())
        index = cls(version=data.get("version", 1))
        for tool_id, bd in data.get("baselines", {}).items():
            index.baselines[tool_id] = ToolBaseline.from_dict(bd)
        return index
