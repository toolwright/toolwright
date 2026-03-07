"""Configuration constants for shape-based drift detection."""

# Presence threshold for "effectively required" classification.
# At 0.95, a field needs to be present in 95% of observations.
EFFECTIVELY_REQUIRED_THRESHOLD: float = 0.95

# Minimum samples before presence stats are considered meaningful.
# With fewer samples, all fields are treated as optional.
MIN_SAMPLES_FOR_PRESENCE: int = 3

# Probe timeout in seconds.
DRIFT_PROBE_TIMEOUT: int = 30

# Max consecutive probe failures before suspension.
DRIFT_PROBE_SUSPENSION_THRESHOLD: int = 5
