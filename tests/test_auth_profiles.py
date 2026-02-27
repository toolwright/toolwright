"""Tests for auth profile management."""

from __future__ import annotations

import json
import os
import platform
from pathlib import Path

import pytest

from toolwright.core.auth.profiles import AuthProfileManager, _validate_name

# --- Profile creation ---

def test_create_profile(tmp_path: Path) -> None:
    manager = AuthProfileManager(tmp_path)
    state = {"cookies": [{"name": "session", "value": "abc123"}]}
    profile_dir = manager.create(name="myapp", storage_state=state, target_url="https://app.example.com")
    assert profile_dir.exists()
    assert (profile_dir / "storage_state.json").exists()
    assert (profile_dir / "meta.json").exists()


def test_create_profile_writes_state(tmp_path: Path) -> None:
    manager = AuthProfileManager(tmp_path)
    state = {"cookies": [{"name": "sid", "value": "xyz"}], "origins": []}
    manager.create(name="test", storage_state=state, target_url="https://x.com")
    loaded = json.loads((tmp_path / "auth" / "profiles" / "test" / "storage_state.json").read_text())
    assert loaded["cookies"][0]["name"] == "sid"


def test_create_profile_writes_meta(tmp_path: Path) -> None:
    manager = AuthProfileManager(tmp_path)
    manager.create(name="prod", storage_state={}, target_url="https://prod.example.com")
    meta = json.loads((tmp_path / "auth" / "profiles" / "prod" / "meta.json").read_text())
    assert meta["name"] == "prod"
    assert meta["target_url"] == "https://prod.example.com"
    assert meta["created_at"] is not None
    assert meta["last_used_at"] is None


@pytest.mark.skipif(platform.system() == "Windows", reason="POSIX permissions")
def test_create_profile_sets_permissions(tmp_path: Path) -> None:
    manager = AuthProfileManager(tmp_path)
    manager.create(name="sec", storage_state={}, target_url="https://x.com")
    state_path = tmp_path / "auth" / "profiles" / "sec" / "storage_state.json"
    mode = oct(os.stat(state_path).st_mode)[-3:]
    assert mode == "600"


# --- Profile loading ---

def test_load_profile(tmp_path: Path) -> None:
    manager = AuthProfileManager(tmp_path)
    state = {"cookies": [{"name": "a", "value": "b"}]}
    manager.create(name="load_test", storage_state=state, target_url="https://x.com")
    loaded = manager.load("load_test")
    assert loaded is not None
    assert loaded["cookies"][0]["value"] == "b"


def test_load_nonexistent_returns_none(tmp_path: Path) -> None:
    manager = AuthProfileManager(tmp_path)
    assert manager.load("nope") is None


def test_get_storage_state_path(tmp_path: Path) -> None:
    manager = AuthProfileManager(tmp_path)
    manager.create(name="path_test", storage_state={}, target_url="https://x.com")
    path = manager.get_storage_state_path("path_test")
    assert path is not None
    assert path.exists()
    assert path.name == "storage_state.json"


def test_get_storage_state_path_missing(tmp_path: Path) -> None:
    manager = AuthProfileManager(tmp_path)
    assert manager.get_storage_state_path("nope") is None


# --- Profile metadata ---

def test_get_meta(tmp_path: Path) -> None:
    manager = AuthProfileManager(tmp_path)
    manager.create(name="meta_test", storage_state={}, target_url="https://x.com")
    meta = manager.get_meta("meta_test")
    assert meta is not None
    assert meta["target_url"] == "https://x.com"


def test_update_last_used(tmp_path: Path) -> None:
    manager = AuthProfileManager(tmp_path)
    manager.create(name="used_test", storage_state={}, target_url="https://x.com")
    assert manager.get_meta("used_test")["last_used_at"] is None
    manager.update_last_used("used_test")
    meta = manager.get_meta("used_test")
    assert meta["last_used_at"] is not None


# --- Profile listing ---

def test_list_profiles_empty(tmp_path: Path) -> None:
    manager = AuthProfileManager(tmp_path)
    assert manager.list_profiles() == []


def test_list_profiles(tmp_path: Path) -> None:
    manager = AuthProfileManager(tmp_path)
    manager.create(name="alpha", storage_state={}, target_url="https://a.com")
    manager.create(name="beta", storage_state={}, target_url="https://b.com")
    profiles = manager.list_profiles()
    assert len(profiles) == 2
    names = {p["name"] for p in profiles}
    assert names == {"alpha", "beta"}


# --- Profile clearing ---

def test_clear_profile(tmp_path: Path) -> None:
    manager = AuthProfileManager(tmp_path)
    manager.create(name="doomed", storage_state={}, target_url="https://x.com")
    assert manager.exists("doomed")
    assert manager.clear("doomed") is True
    assert not manager.exists("doomed")


def test_clear_nonexistent(tmp_path: Path) -> None:
    manager = AuthProfileManager(tmp_path)
    assert manager.clear("nope") is False


# --- Profile existence ---

def test_exists(tmp_path: Path) -> None:
    manager = AuthProfileManager(tmp_path)
    assert not manager.exists("test")
    manager.create(name="test", storage_state={}, target_url="https://x.com")
    assert manager.exists("test")


# --- Name validation ---

def test_validate_name_rejects_empty() -> None:
    with pytest.raises(ValueError, match="empty"):
        _validate_name("")


def test_validate_name_rejects_path_separators() -> None:
    with pytest.raises(ValueError, match="path separators"):
        _validate_name("../evil")


def test_validate_name_rejects_dotfile() -> None:
    with pytest.raises(ValueError, match="start with"):
        _validate_name(".hidden")


def test_validate_name_accepts_normal() -> None:
    _validate_name("my-app_2")  # should not raise
