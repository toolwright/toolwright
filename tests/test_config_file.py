"""Tests for .toolwright/config.yaml and the 'use' command."""

from __future__ import annotations

from pathlib import Path

import yaml
from click.testing import CliRunner

from toolwright.utils.config_file import load_config, save_config


class TestLoadConfig:
    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        root = tmp_path / ".toolwright"
        root.mkdir()
        cfg = load_config(root)
        assert cfg == {}

    def test_loads_existing_config(self, tmp_path: Path) -> None:
        root = tmp_path / ".toolwright"
        root.mkdir()
        (root / "config.yaml").write_text(yaml.dump({"default_toolpack": "stripe"}))
        cfg = load_config(root)
        assert cfg["default_toolpack"] == "stripe"


class TestSaveConfig:
    def test_writes_config(self, tmp_path: Path) -> None:
        root = tmp_path / ".toolwright"
        root.mkdir()
        save_config(root, {"default_toolpack": "github"})
        content = yaml.safe_load((root / "config.yaml").read_text())
        assert content["default_toolpack"] == "github"

    def test_overwrites_existing(self, tmp_path: Path) -> None:
        root = tmp_path / ".toolwright"
        root.mkdir()
        save_config(root, {"default_toolpack": "stripe"})
        save_config(root, {"default_toolpack": "github"})
        content = yaml.safe_load((root / "config.yaml").read_text())
        assert content["default_toolpack"] == "github"


class TestUseCommand:
    def test_use_sets_default(self, tmp_path: Path) -> None:
        root = tmp_path / ".toolwright"
        root.mkdir()
        tp_dir = root / "toolpacks" / "stripe"
        tp_dir.mkdir(parents=True)
        (tp_dir / "toolpack.yaml").write_text(yaml.dump({"toolpack_id": "stripe"}))

        from toolwright.cli.main import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["--root", str(root), "use", "stripe"])
        assert result.exit_code == 0, result.output
        cfg = yaml.safe_load((root / "config.yaml").read_text())
        assert cfg["default_toolpack"] == "stripe"

    def test_use_validates_exists(self, tmp_path: Path) -> None:
        root = tmp_path / ".toolwright"
        root.mkdir()
        (root / "toolpacks").mkdir()

        from toolwright.cli.main import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["--root", str(root), "use", "nonexistent"])
        assert result.exit_code != 0
        assert "not found" in result.output.lower() or "not found" in (result.output + (result.stderr_bytes or b"").decode()).lower()

    def test_use_clear_removes_default(self, tmp_path: Path) -> None:
        root = tmp_path / ".toolwright"
        root.mkdir()
        (root / "config.yaml").write_text(yaml.dump({"default_toolpack": "stripe"}))

        from toolwright.cli.main import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["--root", str(root), "use", "--clear"])
        assert result.exit_code == 0, result.output
        cfg = yaml.safe_load((root / "config.yaml").read_text()) or {}
        assert "default_toolpack" not in cfg
