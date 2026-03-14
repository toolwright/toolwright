"""Tests for Jira API curate_spec.py.

Tests the curation script that downloads the Jira Cloud Platform OpenAPI spec,
filters to an allowlist of paths+methods, and stores content-hash metadata.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

# Path to the module under test
JIRA_DIR = Path(__file__).parent.parent / "dogfood" / "jira"
CURATE_SCRIPT = JIRA_DIR / "curate_spec.py"


# ---------------------------------------------------------------------------
# Helpers: import Jira's curate_spec as a uniquely-named module to avoid
# collisions with GitHub's curate_spec in sys.modules
# ---------------------------------------------------------------------------


def _load_jira_curate_spec():
    """Load dogfood/jira/curate_spec.py as 'jira_curate_spec' module."""
    if not CURATE_SCRIPT.exists():
        pytest.skip("dogfood/jira/curate_spec.py not found (dogfood/ is gitignored)")

    module_name = "jira_curate_spec"
    if module_name in sys.modules:
        return sys.modules[module_name]

    spec = importlib.util.spec_from_file_location(module_name, CURATE_SCRIPT)
    if spec is None or spec.loader is None:
        pytest.skip("Jira curate_spec.py not found")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


MOCK_JIRA_SPEC = {
    "openapi": "3.0.1",
    "info": {"title": "The Jira Cloud platform REST API", "version": "1001.0.0-SNAPSHOT"},
    "servers": [{"url": "https://{domain}.atlassian.net", "variables": {"domain": {"default": "your-domain"}}}],
    "paths": {
        "/rest/api/3/issue": {
            "post": {"operationId": "createIssue", "responses": {"201": {"description": "Created"}}}
        },
        "/rest/api/3/issue/{issueIdOrKey}": {
            "get": {"operationId": "getIssue", "responses": {"200": {"description": "OK"}}},
            "put": {"operationId": "editIssue", "responses": {"204": {"description": "No Content"}}},
            "delete": {"operationId": "deleteIssue", "responses": {"204": {"description": "No Content"}}},
        },
        "/rest/api/3/issue/{issueIdOrKey}/comment": {
            "get": {"operationId": "getComments", "responses": {"200": {"description": "OK"}}},
            "post": {"operationId": "addComment", "responses": {"201": {"description": "Created"}}},
        },
        "/rest/api/3/issue/{issueIdOrKey}/comment/{id}": {
            "get": {"operationId": "getComment", "responses": {"200": {"description": "OK"}}},
            "put": {"operationId": "updateComment", "responses": {"200": {"description": "OK"}}},
            "delete": {"operationId": "deleteComment", "responses": {"204": {"description": "No Content"}}},
        },
        "/rest/api/3/issue/{issueIdOrKey}/transitions": {
            "get": {"operationId": "getTransitions", "responses": {"200": {"description": "OK"}}},
            "post": {"operationId": "doTransition", "responses": {"204": {"description": "No Content"}}},
        },
        "/rest/api/3/project": {
            "get": {"operationId": "getAllProjects", "responses": {"200": {"description": "OK"}}},
            "post": {"operationId": "createProject", "responses": {"201": {"description": "Created"}}},
        },
        "/rest/api/3/project/{projectIdOrKey}": {
            "get": {"operationId": "getProject", "responses": {"200": {"description": "OK"}}},
            "put": {"operationId": "updateProject", "responses": {"200": {"description": "OK"}}},
            "delete": {"operationId": "deleteProject", "responses": {"204": {"description": "No Content"}}},
        },
        "/rest/api/3/search/jql": {
            "get": {"operationId": "searchForIssuesUsingJqlGet", "responses": {"200": {"description": "OK"}}},
            "post": {"operationId": "searchForIssuesUsingJql", "responses": {"200": {"description": "OK"}}},
        },
        "/rest/api/3/users/search": {
            "get": {"operationId": "findUsers", "responses": {"200": {"description": "OK"}}},
        },
        "/rest/api/3/user": {
            "get": {"operationId": "getUser", "responses": {"200": {"description": "OK"}}},
            "post": {"operationId": "createUser", "responses": {"201": {"description": "Created"}}},
            "delete": {"operationId": "removeUser", "responses": {"204": {"description": "No Content"}}},
        },
        # Paths NOT in our allowlist
        "/rest/api/3/dashboard": {
            "get": {"operationId": "getAllDashboards", "responses": {"200": {"description": "OK"}}},
        },
        "/rest/api/3/field": {
            "get": {"operationId": "getFields", "responses": {"200": {"description": "OK"}}},
        },
    },
    "components": {
        "schemas": {"IssueBean": {"type": "object"}},
        "securitySchemes": {"basicAuth": {"type": "http", "scheme": "basic"}},
    },
}

MOCK_RAW_BYTES = json.dumps(MOCK_JIRA_SPEC, indent=2).encode("utf-8")
MOCK_CONTENT_HASH = hashlib.sha256(MOCK_RAW_BYTES).hexdigest()


# ---------------------------------------------------------------------------
# Tests for ALLOWED_PATHS
# ---------------------------------------------------------------------------


class TestAllowedPaths:
    """Test that ALLOWED_PATHS matches our expected endpoint scope."""

    def test_allowed_paths_exist(self):
        """The curate_spec module should export ALLOWED_PATHS."""
        mod = _load_jira_curate_spec()
        assert isinstance(mod.ALLOWED_PATHS, set | dict)

    def test_allowed_paths_contains_core_issue_endpoints(self):
        """Must include issue CRUD, comments, transitions."""
        mod = _load_jira_curate_spec()
        allowed = mod.ALLOWED_PATHS

        required_paths = {
            "/rest/api/3/issue",
            "/rest/api/3/issue/{issueIdOrKey}",
            "/rest/api/3/issue/{issueIdOrKey}/comment",
            "/rest/api/3/issue/{issueIdOrKey}/comment/{id}",
            "/rest/api/3/issue/{issueIdOrKey}/transitions",
        }
        if isinstance(allowed, dict):
            assert required_paths.issubset(set(allowed.keys()))
        else:
            assert required_paths.issubset(allowed)

    def test_allowed_paths_contains_project_and_user_endpoints(self):
        """Must include project list/get and user search."""
        mod = _load_jira_curate_spec()
        allowed = mod.ALLOWED_PATHS

        required_paths = {
            "/rest/api/3/project",
            "/rest/api/3/project/{projectIdOrKey}",
            "/rest/api/3/users/search",
            "/rest/api/3/user",
            "/rest/api/3/search/jql",
        }
        if isinstance(allowed, dict):
            assert required_paths.issubset(set(allowed.keys()))
        else:
            assert required_paths.issubset(allowed)


# ---------------------------------------------------------------------------
# Tests for content-hash metadata
# ---------------------------------------------------------------------------


class TestContentHashMetadata:
    """Test that curated spec includes content-hash pinning metadata."""

    def test_curate_adds_metadata(self):
        """curate() should add x-toolwright-dogfood metadata to info."""
        mod = _load_jira_curate_spec()

        spec = json.loads(json.dumps(MOCK_JIRA_SPEC))
        result = mod.curate(spec, raw_bytes=MOCK_RAW_BYTES, http_status=200, etag='"abc123"')

        metadata = result.get("info", {}).get("x-toolwright-dogfood", {})
        assert metadata, "x-toolwright-dogfood metadata missing"

    def test_content_hash_is_sha256_of_raw_bytes(self):
        """content_sha256 must be SHA-256 of raw bytes BEFORE JSON parsing."""
        mod = _load_jira_curate_spec()

        spec = json.loads(json.dumps(MOCK_JIRA_SPEC))
        result = mod.curate(spec, raw_bytes=MOCK_RAW_BYTES, http_status=200, etag=None)

        metadata = result["info"]["x-toolwright-dogfood"]
        assert metadata["content_sha256"] == MOCK_CONTENT_HASH

    def test_metadata_includes_http_status_and_etag(self):
        """Metadata must include http_status and etag fields."""
        mod = _load_jira_curate_spec()

        spec = json.loads(json.dumps(MOCK_JIRA_SPEC))
        result = mod.curate(spec, raw_bytes=MOCK_RAW_BYTES, http_status=200, etag='"etag-val"')

        metadata = result["info"]["x-toolwright-dogfood"]
        assert metadata["http_status"] == 200
        assert metadata["etag"] == '"etag-val"'

    def test_metadata_etag_null_when_absent(self):
        """When ETag header is absent, etag field should be null."""
        mod = _load_jira_curate_spec()

        spec = json.loads(json.dumps(MOCK_JIRA_SPEC))
        result = mod.curate(spec, raw_bytes=MOCK_RAW_BYTES, http_status=200, etag=None)

        metadata = result["info"]["x-toolwright-dogfood"]
        assert metadata["etag"] is None

    def test_metadata_includes_download_url(self):
        """Metadata must include the download URL."""
        mod = _load_jira_curate_spec()

        spec = json.loads(json.dumps(MOCK_JIRA_SPEC))
        result = mod.curate(spec, raw_bytes=MOCK_RAW_BYTES, http_status=200, etag=None)

        metadata = result["info"]["x-toolwright-dogfood"]
        assert "download_url" in metadata
        assert metadata["download_url"] == mod.SPEC_URL


# ---------------------------------------------------------------------------
# Tests for path+method filtering
# ---------------------------------------------------------------------------


class TestPathMethodFiltering:
    """Test that curate() filters both paths AND methods correctly."""

    def test_curate_removes_non_allowlisted_paths(self):
        """Paths like /dashboard should be removed (prefix stripped)."""
        mod = _load_jira_curate_spec()

        spec = json.loads(json.dumps(MOCK_JIRA_SPEC))
        result = mod.curate(spec, raw_bytes=MOCK_RAW_BYTES, http_status=200, etag=None)

        # After curation, paths have /rest/api/3 prefix stripped
        assert "/dashboard" not in result["paths"]
        assert "/field" not in result["paths"]
        # Full paths should also not appear (prefix absorbed into server URL)
        assert "/rest/api/3/dashboard" not in result["paths"]

    def test_curate_strips_api_prefix_from_paths(self):
        """Curated paths should have /rest/api/3 stripped (absorbed into server URL)."""
        mod = _load_jira_curate_spec()

        spec = json.loads(json.dumps(MOCK_JIRA_SPEC))
        result = mod.curate(spec, raw_bytes=MOCK_RAW_BYTES, http_status=200, etag=None)

        # All curated paths should NOT start with /rest/api/3
        for path in result["paths"]:
            assert not path.startswith("/rest/api/3"), f"Path still has prefix: {path}"

        # Server URL should contain the prefix
        assert any(
            "/rest/api/3" in s.get("url", "") for s in result.get("servers", [])
        ), "Server URL should contain /rest/api/3"

    def test_curate_filters_methods_on_multi_method_paths(self):
        """Only allowed methods should remain on each path."""
        mod = _load_jira_curate_spec()

        spec = json.loads(json.dumps(MOCK_JIRA_SPEC))
        result = mod.curate(spec, raw_bytes=MOCK_RAW_BYTES, http_status=200, etag=None)

        # Paths are now short (prefix stripped)
        # /issue/{issueIdOrKey} has GET, PUT, DELETE in mock but we only want GET
        issue_path = result["paths"].get("/issue/{issueIdOrKey}", {})
        assert "get" in issue_path, "GET should be allowed"
        assert "delete" not in issue_path, "DELETE should be filtered out"

        # /user has GET, POST, DELETE in mock but we only want GET
        user_path = result["paths"].get("/user", {})
        assert "get" in user_path, "GET should be allowed"
        assert "post" not in user_path, "POST /user (createUser) should be filtered out"

    def test_curate_preserves_components(self):
        """components/schemas and components/securitySchemes should be kept."""
        mod = _load_jira_curate_spec()

        spec = json.loads(json.dumps(MOCK_JIRA_SPEC))
        result = mod.curate(spec, raw_bytes=MOCK_RAW_BYTES, http_status=200, etag=None)

        assert "components" in result
        assert "schemas" in result["components"]
        assert "securitySchemes" in result["components"]


# ---------------------------------------------------------------------------
# Tests for --check mode
# ---------------------------------------------------------------------------


class TestCheckMode:
    """Test that --check flag is recognized by argparse."""

    def test_check_flag_accepted(self):
        """curate_spec.py --check should appear in help."""
        if not CURATE_SCRIPT.exists():
            pytest.skip("Jira curate_spec.py not created yet")

        result = subprocess.run(
            [sys.executable, str(CURATE_SCRIPT), "--check", "--help"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "--check" in result.stdout
