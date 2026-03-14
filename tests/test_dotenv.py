"""Tests for toolwright.utils.dotenv — minimal .env reader/writer."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from toolwright.utils.dotenv import DotenvFile


class TestDotenvParsing:
    """Test .env file parsing."""

    def test_parse_well_formed_file(self, tmp_path: Path) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("FOO=bar\nBAZ=qux\n")
        d = DotenvFile(env_file)
        result = d.load()
        assert result == {"FOO": "bar", "BAZ": "qux"}

    def test_equals_in_value(self, tmp_path: Path) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("TOKEN=abc=def=ghi\n")
        d = DotenvFile(env_file)
        result = d.load()
        assert result == {"TOKEN": "abc=def=ghi"}

    def test_comments_skipped(self, tmp_path: Path) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("# this is a comment\nKEY=value\n")
        d = DotenvFile(env_file)
        result = d.load()
        assert result == {"KEY": "value"}

    def test_blank_lines_skipped(self, tmp_path: Path) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("A=1\n\n\nB=2\n")
        d = DotenvFile(env_file)
        result = d.load()
        assert result == {"A": "1", "B": "2"}

    def test_crlf_line_endings(self, tmp_path: Path) -> None:
        env_file = tmp_path / ".env"
        env_file.write_bytes(b"KEY1=val1\r\nKEY2=val2\r\n")
        d = DotenvFile(env_file)
        result = d.load()
        assert result == {"KEY1": "val1", "KEY2": "val2"}

    def test_empty_file(self, tmp_path: Path) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("")
        d = DotenvFile(env_file)
        result = d.load()
        assert result == {}

    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        env_file = tmp_path / ".env"
        d = DotenvFile(env_file)
        result = d.load()
        assert result == {}

    def test_whitespace_stripped(self, tmp_path: Path) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("  KEY  =  value  \n")
        d = DotenvFile(env_file)
        result = d.load()
        assert result == {"KEY": "value"}


class TestDotenvGet:
    """Test get() accessor."""

    def test_get_existing(self, tmp_path: Path) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("KEY=value\n")
        d = DotenvFile(env_file)
        d.load()
        assert d.get("KEY") == "value"

    def test_get_missing(self, tmp_path: Path) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("KEY=value\n")
        d = DotenvFile(env_file)
        d.load()
        assert d.get("MISSING") is None


class TestDotenvSet:
    """Test set() mutation."""

    def test_set_new_key(self, tmp_path: Path) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("A=1\n")
        d = DotenvFile(env_file)
        d.load()
        d.set("B", "2")
        assert d.get("B") == "2"

    def test_update_existing_key(self, tmp_path: Path) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("KEY=old\n")
        d = DotenvFile(env_file)
        d.load()
        d.set("KEY", "new")
        assert d.get("KEY") == "new"


class TestDotenvRoundTrip:
    """Test that comments/blanks survive load -> set -> save."""

    def test_preserve_comments_on_round_trip(self, tmp_path: Path) -> None:
        env_file = tmp_path / ".env"
        original = "# Auth tokens\nTOKEN=abc\n\n# Another comment\nKEY=val\n"
        env_file.write_text(original)

        d = DotenvFile(env_file)
        d.load()
        d.set("NEW", "added")
        d.save()

        content = env_file.read_text()
        assert "# Auth tokens" in content
        assert "# Another comment" in content
        assert "TOKEN=abc" in content
        assert "KEY=val" in content
        assert "NEW=added" in content


class TestDotenvSave:
    """Test save() behavior."""

    def test_file_permissions_0600(self, tmp_path: Path) -> None:
        env_file = tmp_path / ".env"
        d = DotenvFile(env_file)
        d.load()
        d.set("SECRET", "s3cr3t")
        d.save()

        mode = stat.S_IMODE(env_file.stat().st_mode)
        assert mode == 0o600

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        env_file = tmp_path / "sub" / "dir" / ".env"
        d = DotenvFile(env_file)
        d.load()
        d.set("KEY", "val")
        d.save()

        assert env_file.exists()
        assert env_file.read_text().strip() == "KEY=val"


class TestEnsureGitignored:
    """Test ensure_gitignored() behavior."""

    def test_adds_pattern_to_gitignore(self, tmp_path: Path) -> None:
        env_file = tmp_path / ".toolwright" / ".env"
        env_file.parent.mkdir(parents=True)
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text("*.pyc\n")

        added = DotenvFile.ensure_gitignored(env_file)
        assert added is True
        assert ".toolwright/.env" in gitignore.read_text()

    def test_does_not_duplicate_pattern(self, tmp_path: Path) -> None:
        env_file = tmp_path / ".toolwright" / ".env"
        env_file.parent.mkdir(parents=True)
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text(".toolwright/.env\n")

        added = DotenvFile.ensure_gitignored(env_file)
        assert added is False

    def test_creates_gitignore_if_missing(self, tmp_path: Path) -> None:
        env_file = tmp_path / ".toolwright" / ".env"
        env_file.parent.mkdir(parents=True)

        added = DotenvFile.ensure_gitignored(env_file)
        assert added is True
        gitignore = tmp_path / ".gitignore"
        assert gitignore.exists()
        assert ".toolwright/.env" in gitignore.read_text()


class TestLoadDotenvAuth:
    """Test load_dotenv_auth() integration function."""

    def test_loads_from_dotwright_env(self, tmp_path: Path) -> None:
        from toolwright.mcp.runtime import load_dotenv_auth

        dotenv_dir = tmp_path / ".toolwright"
        dotenv_dir.mkdir()
        (dotenv_dir / ".env").write_text(
            'TOOLWRIGHT_AUTH_API_STRIPE_COM=Bearer sk_test_123\n'
        )

        result = load_dotenv_auth(tmp_path)
        assert result == {"TOOLWRIGHT_AUTH_API_STRIPE_COM": "Bearer sk_test_123"}

    def test_returns_empty_when_no_file(self, tmp_path: Path) -> None:
        from toolwright.mcp.runtime import load_dotenv_auth

        result = load_dotenv_auth(tmp_path)
        assert result == {}
