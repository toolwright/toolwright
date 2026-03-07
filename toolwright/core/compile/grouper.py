"""Tool grouping by URL resource path.

Groups tools by their first semantic URL segment, auto-splits large groups,
and provides scope filtering and fuzzy name suggestions.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from toolwright.models.groups import ToolGroup, ToolGroupIndex

# Noise segments stripped during path cleaning (case-insensitive).
_NOISE_SEGMENTS: set[str] = {
    "admin",
    "api",
    "rest",
    "unstable",
    "stable",
    "latest",
}

# Version-like patterns: v1, v2, v3, etc.
_VERSION_RE = re.compile(r"^v\d+$", re.IGNORECASE)

# Azure-style date versions: 2024-01, 2026-06, etc.
_DATE_VERSION_RE = re.compile(r"^\d{4}-\d{2}$")

# Path parameter patterns: {id}, :id
_PARAM_CURLY_RE = re.compile(r"^\{.+\}$")
_PARAM_COLON_RE = re.compile(r"^:.+$")

# File extensions to strip.
_FILE_EXTENSIONS = {".json", ".xml", ".yaml", ".yml"}

# Auto-split threshold.
_SPLIT_THRESHOLD = 80

# Maximum recursive split depth.
_MAX_SPLIT_DEPTH = 3


def extract_semantic_segments(path: str) -> list[str]:
    """Strip noise from a URL path and return meaningful segments.

    Removes: version prefixes (v1/v2/v3), noise words (admin/api/rest),
    date versions (2026-01), path parameters ({id}, :id), and file
    extensions (.json/.xml/.yaml).
    """
    raw_segments = [s for s in path.strip("/").split("/") if s]
    result: list[str] = []

    for segment in raw_segments:
        lower = segment.lower()

        # Skip noise words.
        if lower in _NOISE_SEGMENTS:
            continue

        # Skip version segments like v1, v2, v3.
        if _VERSION_RE.match(lower):
            continue

        # Skip date version segments like 2024-01.
        if _DATE_VERSION_RE.match(lower):
            continue

        # Strip file extensions before param check so {id}.json is detected.
        cleaned = lower
        for ext in _FILE_EXTENSIONS:
            if cleaned.endswith(ext):
                cleaned = cleaned[: -len(ext)]
                break

        # Skip path parameters: {id} or :id (checked after extension strip).
        if _PARAM_CURLY_RE.match(cleaned) or _PARAM_COLON_RE.match(cleaned):
            continue

        if cleaned:
            result.append(cleaned)

    return result


def generate_tool_groups(actions: list[dict[str, Any]]) -> ToolGroupIndex:
    """Group tools by first semantic URL segment with auto-split.

    1. Extract semantic segments from each action's path.
    2. Group by first segment.
    3. Auto-split groups exceeding _SPLIT_THRESHOLD tools by next segment.
    4. Generate descriptions and sort everything alphabetically.
    """
    if not actions:
        return ToolGroupIndex(groups=[], ungrouped=[], generated_from="auto")

    # Map first segment -> list of (action_name, full_segments).
    segment_map: dict[str, list[tuple[str, list[str]]]] = defaultdict(list)
    ungrouped: list[str] = []

    for action in actions:
        name = action.get("name", "")
        path = action.get("path", "/")
        segments = extract_semantic_segments(path)

        if not segments:
            ungrouped.append(name)
            continue

        first = segments[0]
        segment_map[first].append((name, segments))

    # Build groups with auto-split.
    groups: list[ToolGroup] = []

    for first_segment in sorted(segment_map.keys()):
        entries = segment_map[first_segment]
        tool_names = [name for name, _ in entries]

        if len(tool_names) <= _SPLIT_THRESHOLD:
            groups.append(
                ToolGroup(
                    name=first_segment,
                    tools=sorted(tool_names),
                    path_prefix=f"/{first_segment}",
                    description=_describe(first_segment, len(tool_names)),
                )
            )
        else:
            sub_groups = _split_by_depth(first_segment, entries, depth=1)
            groups.extend(sub_groups)

    return ToolGroupIndex(
        groups=groups,
        ungrouped=sorted(ungrouped),
        generated_from="auto",
    )


def _split_by_depth(
    prefix: str,
    entries: list[tuple[str, list[str]]],
    depth: int,
) -> list[ToolGroup]:
    """Recursively split entries by segment at `depth`.

    Falls back to a single catch-all group when:
    - Max depth is reached.
    - All entries share the same sub-segment (no useful split).
    """
    if depth >= _MAX_SPLIT_DEPTH or len(entries) <= _SPLIT_THRESHOLD:
        tools = sorted(name for name, _ in entries)
        return [
            ToolGroup(
                name=prefix,
                tools=tools,
                path_prefix=f"/{prefix}",
                description=_describe(prefix, len(tools)),
            )
        ]

    # Bucket by segment at `depth`.
    sub_map: dict[str, list[tuple[str, list[str]]]] = defaultdict(list)
    no_sub: list[tuple[str, list[str]]] = []

    for name, segments in entries:
        if len(segments) > depth:
            sub_key = segments[depth]
            sub_map[sub_key].append((name, segments))
        else:
            no_sub.append((name, segments))

    # If only one bucket (or none), no useful split possible.
    if len(sub_map) <= 1 and not no_sub:
        tools = sorted(name for name, _ in entries)
        return [
            ToolGroup(
                name=prefix,
                tools=tools,
                path_prefix=f"/{prefix}",
                description=_describe(prefix, len(tools)),
            )
        ]

    result: list[ToolGroup] = []

    # Items without a sub-segment go into the parent group.
    if no_sub:
        tools = sorted(name for name, _ in no_sub)
        result.append(
            ToolGroup(
                name=prefix,
                tools=tools,
                path_prefix=f"/{prefix}",
                description=_describe(prefix, len(tools)),
            )
        )

    for sub_key in sorted(sub_map.keys()):
        sub_entries = sub_map[sub_key]
        sub_prefix = f"{prefix}/{sub_key}"

        if len(sub_entries) > _SPLIT_THRESHOLD:
            result.extend(_split_by_depth(sub_prefix, sub_entries, depth + 1))
        else:
            tools = sorted(name for name, _ in sub_entries)
            result.append(
                ToolGroup(
                    name=sub_prefix,
                    tools=tools,
                    path_prefix=f"/{sub_prefix}",
                    description=_describe(sub_prefix, len(tools)),
                )
            )

    return result


def _describe(name: str, count: int) -> str:
    """Generate a human-readable group description."""
    display = name.replace("/", " ").strip().capitalize()
    return f"{display} endpoints ({count} tools)"


def filter_by_scope(
    actions: list[dict[str, Any]],
    scope: str,
    groups_index: ToolGroupIndex,
) -> list[dict[str, Any]]:
    """Filter actions to those belonging to named groups.

    ``scope`` is a comma-separated list of group names. Prefix matching
    is used: ``repos`` matches ``repos``, ``repos/issues``, ``repos/pulls``.

    Raises ``ValueError`` with a suggestion for unknown group names.
    """
    requested = [s.strip() for s in scope.split(",") if s.strip()]
    available_names = [g.name for g in groups_index.groups]

    # Validate requested names exist (with prefix matching).
    for req in requested:
        matched = any(
            name == req or name.startswith(req + "/") for name in available_names
        )
        if not matched:
            suggestion = suggest_group_name(req, available_names)
            hint = f" Did you mean '{suggestion}'?" if suggestion else ""
            raise ValueError(f"Unknown group: '{req}'.{hint}")

    # Build set of tool names from matching groups.
    included_tools: set[str] = set()
    for group in groups_index.groups:
        for req in requested:
            if group.name == req or group.name.startswith(req + "/"):
                included_tools.update(group.tools)
                break

    # Also include ungrouped tools if explicitly requested.
    # (No special handling needed; ungrouped tools are not in any group.)

    return [a for a in actions if a.get("name") in included_tools]


def suggest_group_name(name: str, available: list[str]) -> str | None:
    """Return the closest group name using Levenshtein distance or prefix match.

    Returns ``None`` if no reasonable match is found.
    """
    if not available:
        return None

    # Exact match.
    if name in available:
        return name

    # Prefix match.
    prefix_matches = [a for a in available if a.startswith(name)]
    if len(prefix_matches) == 1:
        return prefix_matches[0]
    if prefix_matches:
        return sorted(prefix_matches)[0]

    # Levenshtein distance <= 2.
    best: str | None = None
    best_dist = 3  # Only accept distance <= 2.
    for candidate in available:
        dist = _levenshtein(name, candidate)
        if dist < best_dist:
            best_dist = dist
            best = candidate

    return best


def load_groups_index(groups_path: Path | None) -> ToolGroupIndex | None:
    """Load a ToolGroupIndex from a JSON file.

    Returns ``None`` if ``groups_path`` is ``None`` or the file does not exist.
    """
    if groups_path is None:
        return None
    path = Path(groups_path)
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return ToolGroupIndex.from_dict(data)


def _levenshtein(a: str, b: str) -> int:
    """Compute Levenshtein edit distance between two strings."""
    if len(a) < len(b):
        return _levenshtein(b, a)

    if not b:
        return len(a)

    prev_row = list(range(len(b) + 1))

    for i, ca in enumerate(a):
        curr_row = [i + 1]
        for j, cb in enumerate(b):
            cost = 0 if ca == cb else 1
            curr_row.append(
                min(
                    prev_row[j + 1] + 1,  # deletion
                    curr_row[j] + 1,  # insertion
                    prev_row[j] + cost,  # substitution
                )
            )
        prev_row = curr_row

    return prev_row[-1]
