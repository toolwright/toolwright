#!/usr/bin/env python3
"""Curate a scoped GitHub REST API OpenAPI spec for Toolwright dogfooding.

Downloads the official GitHub OpenAPI spec from github/rest-api-description
at a pinned commit SHA, prunes paths to a small allowlist, and writes the
result to github-api-scoped.yaml.

Usage:
    python3 curate_spec.py              # Download and curate
    python3 curate_spec.py --refresh    # Re-download even if cached
    python3 curate_spec.py --check      # Check for upstream drift (exits 1 if changed)
"""

from __future__ import annotations

import argparse
import difflib
import json
import sys
from pathlib import Path
from urllib.request import urlopen

import yaml

# Pinned commit SHA for reproducibility
PINNED_SHA = "f710064757236b11a150543536a59c383344474a"
SPEC_URL = (
    f"https://raw.githubusercontent.com/github/rest-api-description/"
    f"{PINNED_SHA}/descriptions/api.github.com/api.github.com.yaml"
)

# Curated path allowlist -- covers repos, issues, pulls, commits, labels, user
ALLOWED_PATHS = {
    "/repos/{owner}/{repo}",
    "/repos/{owner}/{repo}/issues",
    "/repos/{owner}/{repo}/issues/{issue_number}",
    "/repos/{owner}/{repo}/issues/{issue_number}/comments",
    "/repos/{owner}/{repo}/pulls",
    "/repos/{owner}/{repo}/pulls/{pull_number}",
    "/repos/{owner}/{repo}/commits",
    "/repos/{owner}/{repo}/contents/{path}",
    "/repos/{owner}/{repo}/labels",
    "/user",
}

HTTP_METHODS = ("get", "post", "put", "patch", "delete", "head")

OUTPUT_DIR = Path(__file__).parent
OUTPUT_FILE = OUTPUT_DIR / "github-api-scoped.yaml"
CACHE_FILE = OUTPUT_DIR / ".full-spec-cache.yaml"


def download_spec(force: bool = False) -> dict:
    """Download the full GitHub OpenAPI spec (cached locally)."""
    if CACHE_FILE.exists() and not force:
        print(f"  Using cached spec: {CACHE_FILE}", file=sys.stderr)
        return yaml.safe_load(CACHE_FILE.read_text())

    print(f"  Downloading spec from commit {PINNED_SHA[:12]}...", file=sys.stderr)
    with urlopen(SPEC_URL) as resp:
        content = resp.read().decode("utf-8")

    CACHE_FILE.write_text(content)
    print(f"  Cached to: {CACHE_FILE}", file=sys.stderr)
    return yaml.safe_load(content)


def curate(spec: dict) -> dict:
    """Prune paths to the allowlist, keep everything else intact."""
    original_path_count = len(spec.get("paths", {}))

    # Filter paths
    curated_paths = {}
    for path_key, path_item in spec.get("paths", {}).items():
        if path_key in ALLOWED_PATHS:
            curated_paths[path_key] = path_item

    spec["paths"] = curated_paths

    # Add metadata about curation
    spec.setdefault("info", {})
    spec["info"]["x-toolwright-dogfood"] = {
        "pinned_sha": PINNED_SHA,
        "original_path_count": original_path_count,
        "curated_path_count": len(curated_paths),
        "allowed_paths": sorted(ALLOWED_PATHS),
    }

    return spec


def _count_operations(spec: dict) -> dict[str, int]:
    """Count operations per path in a spec."""
    counts: dict[str, int] = {}
    for path_key, path_item in spec.get("paths", {}).items():
        n = sum(1 for m in HTTP_METHODS if m in path_item)
        if n > 0:
            counts[path_key] = n
    return counts


def check_for_drift(
    committed_spec_path: Path,
    fresh_spec: dict,
    output_dir: Path,
) -> int:
    """Compare freshly curated spec against committed spec.

    Returns 0 if identical, 1 if different.
    Writes diff + summary files on drift.
    Prints one-line summary to stdout.
    """
    # Load committed spec
    committed = yaml.safe_load(committed_spec_path.read_text())

    # Normalize both to sorted JSON for stable comparison
    committed_json = json.dumps(committed, sort_keys=True, indent=2)
    fresh_json = json.dumps(fresh_spec, sort_keys=True, indent=2)

    if committed_json == fresh_json:
        print("No changes detected.")
        return 0

    # Compute operation-level diff summary
    committed_ops = _count_operations(committed)
    fresh_ops = _count_operations(fresh_spec)

    committed_paths = set(committed_ops.keys())
    fresh_paths = set(fresh_ops.keys())

    new_paths = fresh_paths - committed_paths
    removed_paths = committed_paths - fresh_paths
    common_paths = committed_paths & fresh_paths

    # Count new and removed operations
    new_operations = sum(fresh_ops[p] for p in new_paths)
    removed_operations = sum(committed_ops[p] for p in removed_paths)

    # Check for changed operations on common paths
    changed_paths = []
    for p in sorted(common_paths):
        if committed_ops[p] != fresh_ops[p]:
            changed_paths.append(p)
            new_operations += max(0, fresh_ops[p] - committed_ops[p])
            removed_operations += max(0, committed_ops[p] - fresh_ops[p])

    all_changed = sorted(list(new_paths) + list(removed_paths) + changed_paths)

    # Write unified diff to file
    diff_lines = list(
        difflib.unified_diff(
            committed_json.splitlines(keepends=True),
            fresh_json.splitlines(keepends=True),
            fromfile="committed",
            tofile="fresh",
        )
    )
    diff_file = output_dir / "spec-drift.diff"
    diff_file.write_text("".join(diff_lines))

    # Write machine-readable summary
    summary = {
        "new_operations": new_operations,
        "removed_operations": removed_operations,
        "changed_paths": all_changed,
    }
    summary_file = output_dir / "spec-drift-summary.json"
    summary_file.write_text(json.dumps(summary, indent=2))

    # One-line stdout summary
    print(
        f"Drift detected: {new_operations} new operations, "
        f"{removed_operations} removed operations, "
        f"{len(all_changed)} changed paths. "
        f"Diff written to {diff_file}."
    )

    return 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Curate GitHub OpenAPI spec for dogfooding")
    parser.add_argument("--refresh", action="store_true", help="Re-download the spec")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check for upstream drift (exit 1 if spec changed)",
    )
    args = parser.parse_args()

    if args.check:
        # Check mode: always refresh, compare against committed spec
        spec = download_spec(force=True)
        curated = curate(spec)
        exit_code = check_for_drift(
            committed_spec_path=OUTPUT_FILE,
            fresh_spec=curated,
            output_dir=OUTPUT_DIR,
        )
        sys.exit(exit_code)

    print("Curating GitHub REST API OpenAPI spec for Toolwright dogfood\n")

    spec = download_spec(force=args.refresh)
    full_count = len(spec.get("paths", {}))
    print(f"  Full spec: {full_count} paths")

    curated = curate(spec)
    curated_count = len(curated["paths"])
    print(f"  Curated:   {curated_count} paths ({len(ALLOWED_PATHS)} path patterns)")

    # Count operations
    op_count = sum(_count_operations(curated).values())
    print(f"  Operations: {op_count}")

    # Write output
    with open(OUTPUT_FILE, "w") as f:
        yaml.dump(curated, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    print(f"\n  Output: {OUTPUT_FILE}")
    print(f"  Pinned SHA: {PINNED_SHA}")
    print("\nDone.")


if __name__ == "__main__":
    main()
