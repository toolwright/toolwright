"""Locate editable source code for wrapped MCP servers.

Used by the HEAL pillar for code-level auto-repair. Only returns a source
path when the source is deterministic and editable (vendored copies,
local Python/Node scripts). Returns None for npx cache installs, Docker,
remote HTTP, and binaries.
"""

from __future__ import annotations

from pathlib import Path

from toolwright.models.overlay import SourceInfo, WrapConfig


class SourceLocator:
    """Find editable source code for a wrapped server."""

    def locate(self, config: WrapConfig) -> SourceInfo | None:
        """Locate source code for the wrapped server.

        Priority:
        1. Vendored copy in state_dir/vendor/
        2. Direct Python script path in args
        3. Direct Node script path in args
        4. None (not editable)
        """
        # Vendored copy: always use if exists
        vendor_dir = config.state_dir / "vendor"
        if vendor_dir.exists() and any(vendor_dir.iterdir()):
            return SourceInfo(
                source_type="vendored",
                source_path=str(vendor_dir),
                editable=True,
            )

        # Direct script paths in args
        for arg in config.args:
            if arg.endswith(".py") and Path(arg).exists():
                return SourceInfo(
                    source_type="python_script",
                    source_path=arg,
                    editable=True,
                )
            if arg.endswith(".js") and Path(arg).exists():
                return SourceInfo(
                    source_type="node_script",
                    source_path=arg,
                    editable=True,
                )

        # Everything else: not editable
        return None
