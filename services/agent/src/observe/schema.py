"""
Canonical MetricEvent Schema
============================
The dataset-agnostic contract between the Observe layer and
the Analyze layer. Every adapter — regardless of source —
must produce MetricEvent objects. The agent core never knows
which adapter is active.

Mandatory fields: timestamp, four metric streams, label.
Optional fields:  log_anomaly_score, scenario_name,
                  source_dataset, raw_log_text.

Design rationale: Section 4.2 of dissertation.
"""

from dataclasses import dataclass, field
from typing import Optional
import datetime


@dataclass
class MetricEvent:
    """
    A single normalised observation window ready for the
    Analyze layer.

    Mandatory
    ---------
    timestamp     : ISO 8601 UTC string
    cpu_percent   : CPU utilisation  0–100 %
    mem_percent   : Memory pressure  0–100 %
    disk_io_mbps  : Disk I/O         0–∞  MB/s
    net_mbps      : Network I/O      0–∞  MB/s
    label         : Ground truth     0=normal, 1=anomaly

    Optional
    --------
    log_anomaly_score : float [0,1]  — 0.0 when logs unavailable
    scenario_name     : str          — failure type if known
    source_dataset    : str          — provenance tag
    raw_log_text      : str          — raw log line(s) if available
    """

    # Mandatory
    timestamp: str
    cpu_percent: float
    mem_percent: float
    disk_io_mbps: float
    net_mbps: float
    label: int  # 0 = normal, 1 = anomaly

    # Optional — safe defaults so adapters need not provide them
    log_anomaly_score: float = 0.0
    scenario_name: str = ""
    source_dataset: str = ""
    raw_log_text: str = ""

    def to_dict(self) -> dict:
        """Convert to dict for the Analyze layer and action log."""
        return {
            "timestamp": self.timestamp,
            "cpu_percent": self.cpu_percent,
            "mem_percent": self.mem_percent,
            "disk_io_mbps": self.disk_io_mbps,
            "net_mbps": self.net_mbps,
            "label": self.label,
            "log_anomaly_score": self.log_anomaly_score,
            "scenario_name": self.scenario_name,
            "source_dataset": self.source_dataset,
        }

    def validate(self) -> list[str]:
        """
        Returns a list of validation errors.
        Empty list means the event is valid.
        """
        errors = []
        if not (0.0 <= self.cpu_percent <= 100.0):
            errors.append(f"cpu_percent out of range: {self.cpu_percent}")
        if not (0.0 <= self.mem_percent <= 100.0):
            errors.append(f"mem_percent out of range: {self.mem_percent}")
        if self.disk_io_mbps < 0:
            errors.append(f"disk_io_mbps negative: {self.disk_io_mbps}")
        if self.net_mbps < 0:
            errors.append(f"net_mbps negative: {self.net_mbps}")
        if self.label not in (0, 1):
            errors.append(f"label must be 0 or 1, got: {self.label}")
        if not (0.0 <= self.log_anomaly_score <= 1.0):
            errors.append(f"log_anomaly_score out of range: {self.log_anomaly_score}")
        return errors


@dataclass
class MetricWindow:
    """
    A sliding window of MetricEvent objects passed to the Analyze layer.
    Contains metadata about the window itself alongside the events.
    """

    events: list[MetricEvent]
    window_size: int
    source_dataset: str
    has_log_signal: bool  # True if any event has log_anomaly_score > 0

    def to_raw_samples(self) -> list[dict]:
        """
        Convert to the list-of-dicts format expected by the
        existing Preprocessor and ZScoreFilter — backward compatible
        with the viva demo codebase.
        """
        return [e.to_dict() for e in self.events]

    @property
    def ground_truth_label(self) -> int:
        """
        Window is anomalous if ANY event in the window is anomalous.
        Matches the labelling convention from De la Cruz Cabello et al.
        (2026) Section 4.3.1.
        """
        return 1 if any(e.label == 1 for e in self.events) else 0
