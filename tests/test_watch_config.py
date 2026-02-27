"""Tests for WatchConfig model — YAML loading, defaults, and coercion."""

from __future__ import annotations

from toolwright.models.reconcile import AutoHealPolicy, WatchConfig


class TestWatchConfigFromYaml:
    """WatchConfig.from_yaml loading and edge cases."""

    def test_defaults_when_no_file(self, tmp_path):
        """from_yaml on a nonexistent path returns WatchConfig with defaults."""
        cfg = WatchConfig.from_yaml(str(tmp_path / "does_not_exist.yaml"))
        assert cfg.auto_heal == AutoHealPolicy.SAFE
        assert cfg.max_concurrent_probes == 5
        assert cfg.snapshot_before_repair is True

    def test_loads_auto_heal_from_yaml(self, tmp_path):
        """Write a YAML with auto_heal: all, verify parsed correctly."""
        p = tmp_path / "watch.yaml"
        p.write_text("auto_heal: all\n")
        cfg = WatchConfig.from_yaml(str(p))
        assert cfg.auto_heal == AutoHealPolicy.ALL

    def test_loads_probe_intervals(self, tmp_path):
        """Write custom intervals, verify they are loaded."""
        p = tmp_path / "watch.yaml"
        p.write_text(
            "probe_intervals:\n"
            "  critical: 60\n"
            "  high: 150\n"
            "  medium: 300\n"
            "  low: 900\n"
        )
        cfg = WatchConfig.from_yaml(str(p))
        assert cfg.probe_intervals == {
            "critical": 60,
            "high": 150,
            "medium": 300,
            "low": 900,
        }

    def test_loads_max_concurrent_probes(self, tmp_path):
        """Write max_concurrent_probes: 10, verify."""
        p = tmp_path / "watch.yaml"
        p.write_text("max_concurrent_probes: 10\n")
        cfg = WatchConfig.from_yaml(str(p))
        assert cfg.max_concurrent_probes == 10

    def test_yaml_off_coercion(self, tmp_path):
        """YAML bare ``off`` is parsed as False; verify coerced to 'off'."""
        p = tmp_path / "watch.yaml"
        p.write_text("auto_heal: off\n")
        cfg = WatchConfig.from_yaml(str(p))
        assert cfg.auto_heal == AutoHealPolicy.OFF

    def test_yaml_on_coercion(self, tmp_path):
        """YAML bare ``on`` is parsed as True; verify coerced to 'all'."""
        p = tmp_path / "watch.yaml"
        p.write_text("auto_heal: on\n")
        cfg = WatchConfig.from_yaml(str(p))
        assert cfg.auto_heal == AutoHealPolicy.ALL

    def test_invalid_yaml_returns_defaults(self, tmp_path):
        """Write garbage to file, verify defaults returned."""
        p = tmp_path / "watch.yaml"
        p.write_text(":::not valid yaml{{{")
        cfg = WatchConfig.from_yaml(str(p))
        assert cfg.auto_heal == AutoHealPolicy.SAFE
        assert cfg.max_concurrent_probes == 5

    def test_empty_yaml_returns_defaults(self, tmp_path):
        """Empty file returns defaults."""
        p = tmp_path / "watch.yaml"
        p.write_text("")
        cfg = WatchConfig.from_yaml(str(p))
        assert cfg.auto_heal == AutoHealPolicy.SAFE
        assert cfg.max_concurrent_probes == 5
        assert cfg.probe_intervals["critical"] == 120


class TestProbeIntervalForRisk:
    """WatchConfig.probe_interval_for_risk method."""

    def test_probe_interval_for_risk(self):
        """Test the method with various risk tiers including unknown."""
        cfg = WatchConfig()
        assert cfg.probe_interval_for_risk("critical") == 120
        assert cfg.probe_interval_for_risk("high") == 300
        assert cfg.probe_interval_for_risk("medium") == 600
        assert cfg.probe_interval_for_risk("low") == 1800
        # Unknown tier falls back to medium default
        assert cfg.probe_interval_for_risk("exotic") == 600

    def test_default_probe_intervals(self):
        """Verify the defaults: critical=120, high=300, medium=600, low=1800."""
        cfg = WatchConfig()
        assert cfg.probe_intervals == {
            "critical": 120,
            "high": 300,
            "medium": 600,
            "low": 1800,
        }
