#!/usr/bin/env python3
"""Curate a scoped Jira Cloud Platform REST API OpenAPI spec for Toolwright dogfooding.

Downloads the official Jira OpenAPI spec from Atlassian's developer portal,
prunes to an allowlist of paths+methods, and writes the curated result to
jira-api-scoped.yaml with content-hash metadata for drift detection.

Usage:
    python3 curate_spec.py              # Download and curate
    python3 curate_spec.py --refresh    # Re-download even if cached
    python3 curate_spec.py --check      # Check for upstream drift (exits 1 if changed)
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import urlopen

import yaml

# Jira Cloud Platform REST API spec URL (rolling, no pinned version)
SPEC_URL = "https://developer.atlassian.com/cloud/jira/platform/swagger-v3.v3.json"

# API version prefix. Absorbed into server URL during curation so the compiler
# does not treat the bare "3" as a dynamic path parameter.
API_PREFIX = "/rest/api/3"

# Allowed paths + methods. Dict maps FULL path (with prefix) -> set of allowed
# HTTP methods. Only these method+path combos survive curation.
ALLOWED_PATHS: dict[str, set[str]] = {
    # Read-only
    "/rest/api/3/issue/{issueIdOrKey}": {"get"},
    "/rest/api/3/search/jql": {"get"},
    "/rest/api/3/issue/{issueIdOrKey}/comment": {"get", "post"},
    "/rest/api/3/issue/{issueIdOrKey}/comment/{id}": {"get"},
    "/rest/api/3/issue/{issueIdOrKey}/transitions": {"get", "post"},
    "/rest/api/3/project": {"get"},
    "/rest/api/3/project/{projectIdOrKey}": {"get"},
    "/rest/api/3/users/search": {"get"},
    "/rest/api/3/user": {"get"},
    # Write (behind confirmation)
    "/rest/api/3/issue": {"post"},
}

HTTP_METHODS = ("get", "post", "put", "patch", "delete", "head")

OUTPUT_DIR = Path(__file__).parent
OUTPUT_FILE = OUTPUT_DIR / "jira-api-scoped.yaml"
CACHE_FILE = OUTPUT_DIR / ".full-spec-cache.json"


def download_spec(force: bool = False) -> tuple[dict, bytes, int, str | None]:
    """Download the full Jira OpenAPI spec (cached locally).

    Returns (parsed_spec, raw_bytes, http_status, etag).
    """
    if CACHE_FILE.exists() and not force:
        print(f"  Using cached spec: {CACHE_FILE}", file=sys.stderr)
        raw = CACHE_FILE.read_bytes()
        return json.loads(raw), raw, 200, None

    print(f"  Downloading spec from {SPEC_URL}...", file=sys.stderr)
    with urlopen(SPEC_URL) as resp:
        raw = resp.read()
        http_status = resp.status
        etag = resp.headers.get("ETag")
        content_type = resp.headers.get("Content-Type", "")

    CACHE_FILE.write_bytes(raw)
    print(
        f"  Cached to: {CACHE_FILE} ({len(raw)} bytes, {content_type})",
        file=sys.stderr,
    )
    return json.loads(raw), raw, http_status, etag


def curate(
    spec: dict,
    *,
    raw_bytes: bytes,
    http_status: int,
    etag: str | None,
) -> dict:
    """Prune paths+methods to the allowlist, add content-hash metadata."""
    original_path_count = len(spec.get("paths", {}))

    # Filter paths and methods
    curated_paths: dict = {}
    for path_key, path_item in spec.get("paths", {}).items():
        if path_key not in ALLOWED_PATHS:
            continue

        allowed_methods = ALLOWED_PATHS[path_key]
        curated_item = {}
        for method, operation in path_item.items():
            if method in allowed_methods:
                curated_item[method] = operation
            elif method == "parameters":
                # Path-level parameters should be preserved
                curated_item[method] = operation

        if curated_item:
            curated_paths[path_key] = curated_item

    # Rewrite paths: strip the /rest/api/3 prefix so the compiler does not
    # treat the bare "3" as a dynamic {id} parameter.  The prefix is absorbed
    # into the server URL instead.
    short_paths: dict = {}
    for full_path, path_item in curated_paths.items():
        if full_path.startswith(API_PREFIX):
            short = full_path[len(API_PREFIX):]
            if not short:
                short = "/"
        else:
            short = full_path
        short_paths[short] = path_item

    spec["paths"] = short_paths

    # Update server URL to include the API prefix so the full URL is preserved
    spec["servers"] = [
        {
            "url": "https://your-domain.atlassian.net" + API_PREFIX,
            "description": "Jira Cloud REST API v3",
        }
    ]

    # Content-hash of raw bytes BEFORE JSON parsing
    content_sha256 = hashlib.sha256(raw_bytes).hexdigest()

    # Add metadata about curation
    spec.setdefault("info", {})
    spec["info"]["x-toolwright-dogfood"] = {
        "content_sha256": content_sha256,
        "download_url": SPEC_URL,
        "downloaded_at": datetime.now(UTC).isoformat(),
        "content_length": len(raw_bytes),
        "content_type": "application/json",
        "http_status": http_status,
        "etag": etag,
        "original_path_count": original_path_count,
        "curated_path_count": len(short_paths),
        "allowed_paths": sorted(ALLOWED_PATHS.keys()),
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
    committed = yaml.safe_load(committed_spec_path.read_text())

    # Strip volatile metadata before comparison (downloaded_at changes every time)
    for s in (committed, fresh_spec):
        meta = s.get("info", {}).get("x-toolwright-dogfood", {})
        meta.pop("downloaded_at", None)

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

    new_operations = sum(fresh_ops[p] for p in new_paths)
    removed_operations = sum(committed_ops[p] for p in removed_paths)

    changed_paths = []
    for p in sorted(committed_paths & fresh_paths):
        if committed_ops[p] != fresh_ops[p]:
            changed_paths.append(p)
            new_operations += max(0, fresh_ops[p] - committed_ops[p])
            removed_operations += max(0, committed_ops[p] - fresh_ops[p])

    all_changed = sorted(list(new_paths) + list(removed_paths) + changed_paths)

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

    summary = {
        "new_operations": new_operations,
        "removed_operations": removed_operations,
        "changed_paths": all_changed,
    }
    summary_file = output_dir / "spec-drift-summary.json"
    summary_file.write_text(json.dumps(summary, indent=2))

    print(
        f"Drift detected: {new_operations} new operations, "
        f"{removed_operations} removed operations, "
        f"{len(all_changed)} changed paths. "
        f"Diff written to {diff_file}."
    )
    return 1


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Curate Jira Cloud Platform OpenAPI spec for dogfooding"
    )
    parser.add_argument("--refresh", action="store_true", help="Re-download the spec")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check for upstream drift (exit 1 if spec changed)",
    )
    args = parser.parse_args()

    if args.check:
        spec, raw, status, etag = download_spec(force=True)
        curated = curate(spec, raw_bytes=raw, http_status=status, etag=etag)
        exit_code = check_for_drift(
            committed_spec_path=OUTPUT_FILE,
            fresh_spec=curated,
            output_dir=OUTPUT_DIR,
        )
        sys.exit(exit_code)

    print("Curating Jira Cloud Platform REST API OpenAPI spec for Toolwright dogfood\n")

    spec, raw, status, etag = download_spec(force=args.refresh)
    full_count = len(spec.get("paths", {}))
    print(f"  Full spec: {full_count} paths")

    curated = curate(spec, raw_bytes=raw, http_status=status, etag=etag)
    curated_count = len(curated["paths"])
    print(f"  Curated:   {curated_count} paths ({len(ALLOWED_PATHS)} path patterns)")

    op_count = sum(_count_operations(curated).values())
    print(f"  Operations: {op_count}")

    with open(OUTPUT_FILE, "w") as f:
        yaml.dump(curated, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    content_hash = curated["info"]["x-toolwright-dogfood"]["content_sha256"]
    print(f"\n  Output: {OUTPUT_FILE}")
    print(f"  Content SHA-256: {content_hash[:16]}...")
    print("\nDone.")


if __name__ == "__main__":
    main()
