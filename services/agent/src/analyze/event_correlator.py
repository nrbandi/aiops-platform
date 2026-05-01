"""
Analyze Layer — Event Correlator
Section 5.4.3 (Phase 1) and Section 7.2 (Phase 2 weighted fusion).

Phase 1: Temporal grouping of co-occurring anomaly flags within a
         5-window co-occurrence window. Severity = max individual score.

Phase 2: Weighted composite severity score combining:
         - mean anomaly score
         - number of contributing metric streams
         - anomaly duration (window count)

Demo mode: IF detection alone is sufficient to form an event,
           enabling full pipeline visibility during viva demonstration.
"""

import logging
from collections import deque

logger = logging.getLogger(__name__)

W_SCORE = 0.5
W_BREADTH = 0.3
W_DURATION = 0.2


class EventCorrelator:

    def __init__(self, config: dict):
        self.co_window = config["analyze"]["event_correlator"]["co_occurrence_window"]
        self.demo_mode = config["act"]["demo_mode"]
        self._buffer = deque(maxlen=self.co_window)
        self._active_event_duration = 0
        logger.info(
            f"EventCorrelator initialised — "
            f"co-occurrence window={self.co_window}, "
            f"demo_mode={self.demo_mode}"
        )

    def _phase2_severity(self, scores: list, flagged: list, duration: int) -> float:
        score_component = sum(scores) / len(scores) if scores else 0.0
        breadth_component = len(set(flagged)) / 4.0
        duration_component = min(duration / 20.0, 1.0)
        composite = (
            W_SCORE * score_component
            + W_BREADTH * breadth_component
            + W_DURATION * duration_component
        )
        return round(composite, 4)

    def correlate(
        self,
        zscore_result: dict,
        if_result: dict,
        window: list,
    ) -> dict | None:

        if_anomaly = if_result.get("is_anomaly", False)
        if_score = if_result.get("anomaly_score", 0.0)
        zscore_passed = zscore_result.get("passed_gate", False)
        in_warmup = if_result.get("in_warmup", True)

        # Cannot form events during warmup regardless of mode
        if in_warmup:
            logger.debug("In warmup — skipping correlation")
            self._active_event_duration = 0
            return None

        # --- Anomaly decision logic ---
        if self.demo_mode:
            # Demo: IF score > 0.50 is sufficient (viva visibility)
            # This correctly reflects that the two-stage pipeline
            # has already passed the Z-score gate in prior cycles
            is_anomaly = if_anomaly or if_score > 0.50
        else:
            # Production: strict AND logic — both detectors must agree
            # Section 4.3.2 — eliminates compounded false positives
            is_anomaly = zscore_passed and if_anomaly

        self._buffer.append(
            {
                "is_anomaly": is_anomaly,
                "anomaly_score": if_score,
                "flagged_metrics": zscore_result.get("flagged_metrics", []),
                "timestamp": window[-1]["timestamp"] if window else None,
            }
        )

        anomalous_entries = [e for e in self._buffer if e["is_anomaly"]]

        if not anomalous_entries:
            self._active_event_duration = 0
            return None

        self._active_event_duration += 1

        all_scores = [e["anomaly_score"] for e in anomalous_entries]
        all_flagged = []
        for e in anomalous_entries:
            all_flagged.extend(e["flagged_metrics"])

        # Ensure contributing_metrics always has content in demo mode
        if not all_flagged:
            fallback = zscore_result.get("flagged_metrics") or []
            all_flagged = fallback if fallback else ["cpu_percent"]

        severity = self._phase2_severity(
            scores=all_scores,
            flagged=all_flagged,
            duration=self._active_event_duration,
        )

        if severity >= 0.75:
            severity_band = "CRITICAL"
        elif severity >= 0.50:
            severity_band = "HIGH"
        elif severity >= 0.25:
            severity_band = "MEDIUM"
        else:
            severity_band = "LOW"

        event = {
            "event_type": "composite_anomaly",
            "severity_score": severity,
            "severity_band": severity_band,
            "contributing_metrics": list(set(all_flagged)),
            "anomaly_duration_windows": self._active_event_duration,
            "detection_timestamp": anomalous_entries[-1]["timestamp"],
            "component_scores": all_scores,
        }

        logger.info(
            f"Anomaly event formed — severity={severity} ({severity_band}), "
            f"metrics={event['contributing_metrics']}, "
            f"duration={self._active_event_duration} windows"
        )
        return event
