"""Tests for verify mode expansion (H3).

--mode all without --playbook must skip provenance gracefully.
"""

from __future__ import annotations

from toolwright.cli.verify import _expand_modes


class TestExpandModes:
    """H3: _expand_modes must handle missing playbook for 'all' mode."""

    def test_all_mode_includes_provenance_with_playbook(self) -> None:
        """mode=all with playbook should include provenance."""
        modes = _expand_modes("all", has_playbook=True)
        assert "provenance" in modes
        assert "contracts" in modes
        assert "replay" in modes
        assert "outcomes" in modes

    def test_all_mode_excludes_provenance_without_playbook(self) -> None:
        """mode=all without playbook should exclude provenance."""
        modes = _expand_modes("all", has_playbook=False)
        assert "provenance" not in modes
        assert "contracts" in modes
        assert "replay" in modes
        assert "outcomes" in modes

    def test_explicit_provenance_mode_unaffected(self) -> None:
        """Explicit --mode provenance is unaffected by has_playbook."""
        modes = _expand_modes("provenance", has_playbook=False)
        assert "provenance" in modes

    def test_baseline_check_mode_unaffected(self) -> None:
        """baseline-check should still resolve to replay."""
        modes = _expand_modes("baseline-check", has_playbook=False)
        assert "replay" in modes
        assert "provenance" not in modes

    def test_contracts_mode_unaffected(self) -> None:
        """Single modes should work as before."""
        modes = _expand_modes("contracts")
        assert modes == {"contracts"}
