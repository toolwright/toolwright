"""Tests for curate_spec.py --check mode (upstream spec drift detection).

Tests the --check flag that compares a freshly curated spec against the
committed spec and reports drift via one-line stdout + file artifacts.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

# The module under test
CURATE_SCRIPT = Path(__file__).parent.parent / "dogfood" / "github" / "curate_spec.py"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

MINIMAL_SPEC = {
    "openapi": "3.0.0",
    "info": {"title": "Test API", "version": "1.0.0"},
    "paths": {
        "/repos/{owner}/{repo}": {
            "get": {"operationId": "repos/get", "responses": {"200": {"description": "OK"}}}
        },
        "/user": {
            "get": {"operationId": "users/get-authenticated", "responses": {"200": {"description": "OK"}}}
        },
    },
}


def _make_committed_spec(spec: dict, output_dir: Path) -> Path:
    """Write a YAML spec file that acts as the 'committed' baseline."""
    p = output_dir / "github-api-scoped.yaml"
    with open(p, "w") as f:
        yaml.dump(spec, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
    return p


def _make_curated_spec_with_drift(base: dict) -> dict:
    """Return a spec with an extra path (simulating upstream drift)."""
    drifted = json.loads(json.dumps(base))  # deep copy
    drifted["paths"]["/repos/{owner}/{repo}/issues"] = {
        "get": {"operationId": "issues/list", "responses": {"200": {"description": "OK"}}},
        "post": {"operationId": "issues/create", "responses": {"201": {"description": "Created"}}},
    }
    return drifted


# ---------------------------------------------------------------------------
# Tests for check_for_drift() function
# ---------------------------------------------------------------------------


class TestCheckForDrift:
    """Test the check_for_drift() function directly."""

    def test_no_drift_returns_zero(self, tmp_path: Path):
        """When committed and fresh specs match, exit 0 + 'No changes detected.' stdout."""
        # We import the function; it doesn't exist yet (TDD RED)
        sys.path.insert(0, str(CURATE_SCRIPT.parent))
        try:
            from curate_spec import check_for_drift
        except ImportError:
            pytest.skip("check_for_drift not implemented yet")

        committed = _make_committed_spec(MINIMAL_SPEC, tmp_path)
        # "Fresh" spec is identical to committed
        result = check_for_drift(
            committed_spec_path=committed,
            fresh_spec=MINIMAL_SPEC,
            output_dir=tmp_path,
        )
        assert result == 0

    def test_drift_returns_one_and_writes_files(self, tmp_path: Path):
        """When drift exists, exit 1 + diff file + summary JSON written."""
        sys.path.insert(0, str(CURATE_SCRIPT.parent))
        try:
            from curate_spec import check_for_drift
        except ImportError:
            pytest.skip("check_for_drift not implemented yet")

        committed = _make_committed_spec(MINIMAL_SPEC, tmp_path)
        drifted = _make_curated_spec_with_drift(MINIMAL_SPEC)

        result = check_for_drift(
            committed_spec_path=committed,
            fresh_spec=drifted,
            output_dir=tmp_path,
        )

        assert result == 1

        # Diff file should exist
        diff_file = tmp_path / "spec-drift.diff"
        assert diff_file.exists(), "spec-drift.diff not written"
        diff_content = diff_file.read_text()
        assert len(diff_content) > 0, "diff file is empty"

        # Summary JSON should exist
        summary_file = tmp_path / "spec-drift-summary.json"
        assert summary_file.exists(), "spec-drift-summary.json not written"
        summary = json.loads(summary_file.read_text())

        assert "new_operations" in summary
        assert "removed_operations" in summary
        assert "changed_paths" in summary
        # We added /repos/{owner}/{repo}/issues with GET + POST = 2 new ops
        assert summary["new_operations"] >= 1
        assert isinstance(summary["changed_paths"], list)

    def test_drift_summary_counts_removed_operations(self, tmp_path: Path):
        """Removed paths should be counted in removed_operations."""
        sys.path.insert(0, str(CURATE_SCRIPT.parent))
        try:
            from curate_spec import check_for_drift
        except ImportError:
            pytest.skip("check_for_drift not implemented yet")

        # Committed has both paths, fresh has only /user
        committed = _make_committed_spec(MINIMAL_SPEC, tmp_path)
        reduced = json.loads(json.dumps(MINIMAL_SPEC))
        del reduced["paths"]["/repos/{owner}/{repo}"]

        result = check_for_drift(
            committed_spec_path=committed,
            fresh_spec=reduced,
            output_dir=tmp_path,
        )
        assert result == 1

        summary = json.loads((tmp_path / "spec-drift-summary.json").read_text())
        assert summary["removed_operations"] >= 1


# ---------------------------------------------------------------------------
# Tests for --check CLI flag
# ---------------------------------------------------------------------------


class TestCheckCLIFlag:
    """Test that --check flag is recognized by argparse and routes correctly."""

    def test_check_flag_accepted(self):
        """curate_spec.py --check should not error on unknown argument."""
        # This tests that the argparse parser accepts --check
        result = subprocess.run(
            [sys.executable, str(CURATE_SCRIPT), "--check", "--help"],
            capture_output=True,
            text=True,
        )
        # --help exits 0 and should mention --check
        assert result.returncode == 0
        assert "--check" in result.stdout


# ---------------------------------------------------------------------------
# Tests for stdout format
# ---------------------------------------------------------------------------


class TestStdoutFormat:
    """Verify stdout is one-line summary only (no full diff on stdout)."""

    def test_no_drift_stdout_is_one_line(self, tmp_path: Path):
        """No drift = single line 'No changes detected.'"""
        sys.path.insert(0, str(CURATE_SCRIPT.parent))
        try:
            from curate_spec import check_for_drift
        except ImportError:
            pytest.skip("check_for_drift not implemented yet")

        committed = _make_committed_spec(MINIMAL_SPEC, tmp_path)
        # Capture stdout
        import io
        from contextlib import redirect_stdout

        f = io.StringIO()
        with redirect_stdout(f):
            check_for_drift(
                committed_spec_path=committed,
                fresh_spec=MINIMAL_SPEC,
                output_dir=tmp_path,
            )
        output = f.getvalue().strip()
        assert output == "No changes detected."

    def test_drift_stdout_is_one_line_summary(self, tmp_path: Path):
        """Drift = single summary line mentioning counts and path."""
        sys.path.insert(0, str(CURATE_SCRIPT.parent))
        try:
            from curate_spec import check_for_drift
        except ImportError:
            pytest.skip("check_for_drift not implemented yet")

        committed = _make_committed_spec(MINIMAL_SPEC, tmp_path)
        drifted = _make_curated_spec_with_drift(MINIMAL_SPEC)

        import io
        from contextlib import redirect_stdout

        f = io.StringIO()
        with redirect_stdout(f):
            check_for_drift(
                committed_spec_path=committed,
                fresh_spec=drifted,
                output_dir=tmp_path,
            )
        output = f.getvalue().strip()
        # Should be exactly one line
        assert output.count("\n") == 0, f"Expected one line, got: {output!r}"
        # Should mention "Drift detected"
        assert "Drift detected" in output
        # Should reference the diff file path
        assert "spec-drift.diff" in output
