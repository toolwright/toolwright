"""Tool group data model for organizing tools by URL resource."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolGroup:
    """A named group of tools sharing a URL resource prefix."""

    name: str
    tools: list[str]
    path_prefix: str
    description: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "tools": self.tools,
            "path_prefix": self.path_prefix,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ToolGroup:
        return cls(
            name=data["name"],
            tools=data["tools"],
            path_prefix=data["path_prefix"],
            description=data.get("description"),
        )


@dataclass
class ToolGroupIndex:
    """Top-level container written to groups.json."""

    groups: list[ToolGroup] = field(default_factory=list)
    ungrouped: list[str] = field(default_factory=list)
    generated_from: str = "auto"

    def to_dict(self) -> dict[str, Any]:
        return {
            "groups": [g.to_dict() for g in self.groups],
            "ungrouped": self.ungrouped,
            "generated_from": self.generated_from,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ToolGroupIndex:
        groups = [ToolGroup.from_dict(g) for g in data.get("groups", [])]
        return cls(
            groups=groups,
            ungrouped=data.get("ungrouped", []),
            generated_from=data.get("generated_from", "auto"),
        )
