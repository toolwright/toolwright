"""Variant-aware baseline store for the heal system.

Manages the directory layout, sample ring buffers, freeze/unfreeze,
and atomic writes for the heal pipeline.

Directory layout:
    {root}/
      {tool_id}/
        variants/
          {variant_slug}/
            schema.json           # Baseline inferred schema (READ-ONLY during drift)
            samples/              # Baseline ring buffer (READ-ONLY during drift)
            current/              # Current observations (WRITTEN during drift)
              samples/
            history/              # Schema version history
        frozen_variants.json      # Persisted freeze state (survives restart)
        variant_meta.json         # LRU order, variant count

All file writes use tmp + os.replace for atomicity.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import shutil
import time
import uuid
from pathlib import Path
from typing import Any

from toolwright.models.heal import InferredSchema, ResponseSample

logger = logging.getLogger("toolwright.heal.baseline_store")

DEFAULT_MAX_SAMPLES = 100
DEFAULT_MAX_VARIANTS = 10


class BaselineStore:
    """Variant-aware baseline storage engine."""

    def __init__(
        self,
        root: Path,
        *,
        max_samples: int = DEFAULT_MAX_SAMPLES,
        max_variants: int = DEFAULT_MAX_VARIANTS,
    ) -> None:
        self._root = root
        self._max_samples = max_samples
        self._max_variants = max_variants
        self._frozen: dict[str, set[str]] = {}  # tool_id → set of frozen variant keys
        self._load_all_frozen()

    # ── Variant key / slug ────────────────────────────────────────

    def variant_key(self, tool_id: str, args: dict[str, str] | None = None) -> str:
        """Compute variant key from tool_id and argument keys."""
        if not args:
            return f"{tool_id}:default"
        sorted_keys = ":".join(sorted(args.keys()))
        return f"{tool_id}:{sorted_keys}"

    def variant_slug(self, key: str) -> str:
        """SHA256[:12] of variant key for directory naming."""
        return hashlib.sha256(key.encode()).hexdigest()[:12]

    # ── Sample recording ──────────────────────────────────────────

    def record_sample(self, sample: ResponseSample) -> Path:
        """Record a sample, routing to baseline or current based on freeze state.

        Returns the path of the written file.
        """
        tool_id = sample.tool_id
        variant = sample.variant
        slug = self.variant_slug(variant)

        # Ensure variant dir exists
        variant_dir = self._variant_dir(tool_id, slug)
        self._ensure_dirs(variant_dir)

        # Update variant meta (LRU tracking)
        self._touch_variant(tool_id, variant, slug)

        # Route to correct sample directory
        if self.is_frozen(variant):
            sample_dir = variant_dir / "current" / "samples"
        else:
            sample_dir = variant_dir / "samples"
        sample_dir.mkdir(parents=True, exist_ok=True)

        # Collision-proof filename
        ms_ts = int(sample.timestamp * 1000)
        uid = uuid.uuid4().hex[:8]
        filename = f"{ms_ts}_{uid}.json"
        target = sample_dir / filename

        # Atomic write
        content = sample.model_dump_json(indent=2)
        self._atomic_write(target, content)

        # Evict oldest if ring buffer full
        self._enforce_ring_limit(sample_dir)

        return target

    def load_baseline_samples(self, tool_id: str, variant: str) -> list[ResponseSample]:
        """Load samples from baseline samples/ directory."""
        slug = self.variant_slug(variant)
        sample_dir = self._variant_dir(tool_id, slug) / "samples"
        return self._load_samples_from(sample_dir)

    def load_current_samples(self, tool_id: str, variant: str) -> list[ResponseSample]:
        """Load samples from current/samples/ directory."""
        slug = self.variant_slug(variant)
        sample_dir = self._variant_dir(tool_id, slug) / "current" / "samples"
        return self._load_samples_from(sample_dir)

    # ── Freeze / unfreeze ─────────────────────────────────────────

    def freeze(self, variant_key: str) -> None:
        """Freeze a variant — new samples go to current/ instead of samples/."""
        tool_id = variant_key.split(":")[0]
        if tool_id not in self._frozen:
            self._frozen[tool_id] = set()
        self._frozen[tool_id].add(variant_key)
        self._persist_frozen(tool_id)

    def unfreeze(self, variant_key: str) -> None:
        """Unfreeze a variant — new samples go back to samples/."""
        tool_id = variant_key.split(":")[0]
        if tool_id in self._frozen:
            self._frozen[tool_id].discard(variant_key)
            self._persist_frozen(tool_id)

    def is_frozen(self, variant_key: str) -> bool:
        """Check if a variant is frozen."""
        tool_id = variant_key.split(":")[0]
        return variant_key in self._frozen.get(tool_id, set())

    # ── Schema persistence ────────────────────────────────────────

    def save_schema(self, tool_id: str, variant: str, schema: InferredSchema) -> None:
        """Atomically save inferred schema."""
        slug = self.variant_slug(variant)
        schema_path = self._variant_dir(tool_id, slug) / "schema.json"
        schema_path.parent.mkdir(parents=True, exist_ok=True)
        self._atomic_write(schema_path, schema.model_dump_json(indent=2))

    def load_schema(self, tool_id: str, variant: str) -> InferredSchema | None:
        """Load inferred schema, or None if not found."""
        slug = self.variant_slug(variant)
        schema_path = self._variant_dir(tool_id, slug) / "schema.json"
        if not schema_path.exists():
            return None
        data = json.loads(schema_path.read_text())
        return InferredSchema.model_validate(data)

    # ── Internal helpers ──────────────────────────────────────────

    def _variant_dir(self, tool_id: str, slug: str) -> Path:
        return self._root / tool_id / "variants" / slug

    def _tool_dir(self, tool_id: str) -> Path:
        return self._root / tool_id

    def _ensure_dirs(self, variant_dir: Path) -> None:
        """Create the full variant directory structure."""
        (variant_dir / "samples").mkdir(parents=True, exist_ok=True)
        (variant_dir / "current" / "samples").mkdir(parents=True, exist_ok=True)
        (variant_dir / "history").mkdir(parents=True, exist_ok=True)

    def _atomic_write(self, path: Path, content: str) -> None:
        """Write content atomically via tmp + os.replace."""
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.parent / f".{path.name}.tmp"
        tmp.write_text(content)
        os.replace(str(tmp), str(path))

    def _enforce_ring_limit(self, sample_dir: Path) -> None:
        """Delete oldest samples if over max_samples."""
        files = sorted(sample_dir.glob("*.json"))
        while len(files) > self._max_samples:
            oldest = files.pop(0)
            with contextlib.suppress(FileNotFoundError):
                oldest.unlink()

    def _load_samples_from(self, sample_dir: Path) -> list[ResponseSample]:
        """Load all samples from a directory, sorted by filename (time-ordered)."""
        if not sample_dir.exists():
            return []
        samples = []
        for f in sorted(sample_dir.glob("*.json")):
            try:
                data = json.loads(f.read_text())
                samples.append(ResponseSample.model_validate(data))
            except (json.JSONDecodeError, FileNotFoundError):
                logger.warning("Skipping corrupt/missing sample: %s", f)
        return samples

    # ── Frozen state persistence ──────────────────────────────────

    def _persist_frozen(self, tool_id: str) -> None:
        """Persist frozen variants set for a tool."""
        tool_dir = self._tool_dir(tool_id)
        tool_dir.mkdir(parents=True, exist_ok=True)
        frozen_path = tool_dir / "frozen_variants.json"
        data = {"frozen": sorted(self._frozen.get(tool_id, set()))}
        self._atomic_write(frozen_path, json.dumps(data, indent=2))

    def _load_all_frozen(self) -> None:
        """Load frozen state from all tool directories on startup."""
        if not self._root.exists():
            return
        for tool_dir in self._root.iterdir():
            if not tool_dir.is_dir():
                continue
            frozen_path = tool_dir / "frozen_variants.json"
            if frozen_path.exists():
                try:
                    data = json.loads(frozen_path.read_text())
                    self._frozen[tool_dir.name] = set(data.get("frozen", []))
                except (json.JSONDecodeError, KeyError):
                    logger.warning("Corrupt frozen state: %s", frozen_path)

    # ── Variant metadata / LRU ────────────────────────────────────

    def _touch_variant(self, tool_id: str, variant_key: str, slug: str) -> None:
        """Update variant LRU metadata and evict if over max_variants."""
        tool_dir = self._tool_dir(tool_id)
        tool_dir.mkdir(parents=True, exist_ok=True)
        meta_path = tool_dir / "variant_meta.json"

        # Load existing
        meta: dict[str, Any] = {"variants": []}
        if meta_path.exists():
            with contextlib.suppress(json.JSONDecodeError):
                loaded = json.loads(meta_path.read_text())
                if isinstance(loaded, dict):
                    meta = loaded

        variants: list[dict[str, Any]] = list(meta.get("variants", []))

        # Remove existing entry for this key
        variants = [v for v in variants if v["key"] != variant_key]

        # Add at end (most recent)
        variants.append({
            "key": variant_key,
            "slug": slug,
            "last_accessed": time.time(),
        })

        # Evict LRU if over limit
        while len(variants) > self._max_variants:
            evicted = variants.pop(0)
            evicted_dir = self._variant_dir(tool_id, evicted["slug"])
            if evicted_dir.exists():
                shutil.rmtree(evicted_dir, ignore_errors=True)
            logger.info("Evicted LRU variant: %s", evicted["key"])

        meta["variants"] = variants
        self._atomic_write(meta_path, json.dumps(meta, indent=2))
