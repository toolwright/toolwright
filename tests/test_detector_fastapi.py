"""Tests for FastAPI framework detection in project detector."""

from __future__ import annotations

from pathlib import Path

from toolwright.core.init.detector import detect_project


class TestFastAPIDetection:
    """Test that FastAPI projects are correctly detected."""

    def test_detects_fastapi_in_requirements_txt(self, tmp_path: Path) -> None:
        """FastAPI listed in requirements.txt should be detected."""
        (tmp_path / "requirements.txt").write_text("fastapi>=0.100\nuvicorn\n")
        result = detect_project(tmp_path)
        assert "fastapi" in result.frameworks

    def test_detects_fastapi_in_pyproject_toml(self, tmp_path: Path) -> None:
        """FastAPI listed in pyproject.toml dependencies should be detected."""
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "myapp"\ndependencies = ["fastapi", "uvicorn"]\n'
        )
        result = detect_project(tmp_path)
        assert "fastapi" in result.frameworks

    def test_does_not_detect_fastapi_when_absent(self, tmp_path: Path) -> None:
        """Projects without FastAPI should not have it in frameworks."""
        (tmp_path / "requirements.txt").write_text("flask>=2.0\ngunicorn\n")
        result = detect_project(tmp_path)
        assert "fastapi" not in result.frameworks

    def test_detects_fastapi_main_py_import(self, tmp_path: Path) -> None:
        """A main.py importing from fastapi should trigger detection."""
        (tmp_path / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n")
        result = detect_project(tmp_path)
        assert "fastapi" in result.frameworks

    def test_no_false_positive_for_fastapi_substring(self, tmp_path: Path) -> None:
        """'notfastapi' in requirements should not trigger FastAPI detection."""
        (tmp_path / "requirements.txt").write_text("notfastapi>=1.0\n")
        result = detect_project(tmp_path)
        assert "fastapi" not in result.frameworks
