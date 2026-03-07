"""Drift detection engine."""

from toolwright.core.drift.baselines import (
    DriftResult,
    compile_shape_baselines,
    detect_drift_for_tool,
)
from toolwright.core.drift.drift_handler import DriftAction, handle_drift
from toolwright.core.drift.engine import DriftEngine
from toolwright.core.drift.probe_executor import ProbeResult, execute_probe
from toolwright.core.drift.shape_diff import (
    DriftChange,
    DriftChangeType,
    DriftSeverity,
    diff_shapes,
    overall_severity,
)
from toolwright.core.drift.shape_inference import (
    InferenceMetadata,
    infer_shape,
    merge_observation,
)
from toolwright.core.drift.shape_probe_loop import ShapeProbeLoop

__all__ = [
    "DriftEngine",
    # Shape baseline compilation and detection
    "compile_shape_baselines",
    "detect_drift_for_tool",
    "DriftResult",
    # Probe executor
    "execute_probe",
    "ProbeResult",
    # Drift handler
    "handle_drift",
    "DriftAction",
    # Shape probe loop
    "ShapeProbeLoop",
    # Shape-based drift detection
    "infer_shape",
    "merge_observation",
    "InferenceMetadata",
    "diff_shapes",
    "overall_severity",
    "DriftChange",
    "DriftChangeType",
    "DriftSeverity",
]
