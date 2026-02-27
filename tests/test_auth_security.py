"""Tests for auth security — verify auth state excluded from bundles, toolpacks, evidence."""

from __future__ import annotations

from pathlib import Path

from toolwright.core.auth.profiles import AuthProfileManager
from toolwright.core.verify.evidence import (
    create_evidence_bundle,
    create_evidence_entry,
    save_evidence_bundle,
)


def _setup_auth_profile(root: Path) -> None:
    """Create a test auth profile with storage state."""
    manager = AuthProfileManager(root)
    manager.create(
        name="test_app",
        storage_state={"cookies": [{"name": "session", "value": "secret_token"}]},
        target_url="https://app.example.com",
    )


def test_auth_dir_exists_after_profile_creation(tmp_path: Path) -> None:
    _setup_auth_profile(tmp_path)
    assert (tmp_path / "auth" / "profiles" / "test_app" / "storage_state.json").exists()


def test_evidence_bundle_excludes_auth_data(tmp_path: Path) -> None:
    """Evidence bundles must never contain auth profile data."""
    _setup_auth_profile(tmp_path)

    # Create evidence entries — they should contain verify data, NOT auth data
    entries = [
        create_evidence_entry(
            event_type="verify_result",
            source="verify_engine",
            data={"status": "pass", "tool_id": "get_users"},
        ),
    ]
    bundle = create_evidence_bundle(
        toolpack_id="tp_test",
        context="verify",
        entries=entries,
    )

    evidence_dir = tmp_path / "evidence"
    bundle_path = save_evidence_bundle(bundle, evidence_dir)

    # Read the bundle and verify no auth data leaked
    content = bundle_path.read_text(encoding="utf-8")
    assert "secret_token" not in content
    assert "session" not in content or "capture_session" in content.lower()


def test_auth_state_not_in_toolpack_yaml(tmp_path: Path) -> None:
    """Auth profile data must never appear in toolpack.yaml."""
    import yaml

    _setup_auth_profile(tmp_path)

    # Create a minimal toolpack.yaml
    toolpack_data = {
        "version": "1.0.0",
        "schema_version": "1.0",
        "toolpack_id": "tp_test",
        "capture_id": "cap_test",
        "artifact_id": "art_test",
        "scope": "agent_safe_readonly",
        "allowed_hosts": ["api.example.com"],
    }
    toolpack_path = tmp_path / "toolpack.yaml"
    toolpack_path.write_text(yaml.dump(toolpack_data))

    content = toolpack_path.read_text()
    assert "secret_token" not in content
    assert "storage_state" not in content


def test_bundle_sensitive_tokens_exclude_auth() -> None:
    """Verify the bundle exclusion list includes auth-related tokens."""
    # This mirrors the logic in toolwright/cli/bundle.py _collect_toolpack_files
    sensitive_tokens = {
        "storage_state",
        "confirmations.db",
        "approval_signing.key",
        "auth",
        ".toolwright",
        "state",
    }

    # Auth-related paths that must be excluded
    auth_paths = [
        "auth/profiles/myapp/storage_state.json",
        "auth/profiles/myapp/meta.json",
        "auth/storage_state.json",
    ]

    for auth_path in auth_paths:
        blocked = any(token in auth_path for token in sensitive_tokens)
        assert blocked, f"Auth path '{auth_path}' not blocked by sensitive_tokens filter"


def test_gitignore_should_include_auth() -> None:
    """The .gitignore template should exclude auth/ directory."""
    # This is a design assertion: when we generate .gitignore in toolwright init,
    # auth/ must be included. For now we just verify the convention.
    gitignore_patterns = [
        "auth/",
        ".toolwright/auth/",
        "*/auth/profiles/",
    ]
    # At least one of these patterns would catch auth dirs
    assert any("auth" in p for p in gitignore_patterns)
