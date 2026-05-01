"""
Analyze Layer — Flatness Detector
==================================
Detects lock-in anomalies — metrics that are suspiciously
stable within a window. Complements Z-score spike detection.

Design rationale (Section 4.3.2):
    Z-score detects deviation ABOVE the mean (spikes).
    Flatness detector detects suspiciously LOW variance (lock-in).
    Both gates run in parallel — either passing sends the window
    to Isolation Forest. This reflects production SRE practice
    where both spike and flatline patterns indicate infrastructure
    distress.

Method: Coefficient of Variation (CV = std / mean) per metric.
    A metric is flagged as flat if:
      1. CV < cv_threshold (suspiciously low variance)
      2. mean > min_signal (metric is active, not zero/off)
      3. At least min_flat_samples of window_size samples
         fall within a tight band (mean ± band_pct)

References:
    Liu et al. (2008) — Isolation Forest
    GAIA low_signal-to-noise_ratio_data characteristics
"""

import logging
import numpy as np

logger = logging.getLogger(__name__)

METRICS = ["cpu_percent", "mem_percent", "disk_io_mbps", "net_mbps"]


class FlatnessDetector:
    """
    Detects lock-in anomalies via Coefficient of Variation (CV).

    Mirrors ZScoreFilter output format for drop-in compatibility
    with the existing pipeline gate logic.
    """

    def __init__(self, config: dict):
        self.cv_threshold = (
            config.get("analyze", {}).get("flatness", {}).get("cv_threshold", 0.005)
        )

        self.min_signal = (
            config.get("analyze", {}).get("flatness", {}).get("min_signal", 1.0)
        )

        self.min_flat_ratio = (
            config.get("analyze", {}).get("flatness", {}).get("min_flat_ratio", 0.7)
        )

        self.band_pct = (
            config.get("analyze", {}).get("flatness", {}).get("band_pct", 0.01)
        )

        logger.info(
            f"FlatnessDetector initialised — "
            f"cv_threshold={self.cv_threshold}, "
            f"min_signal={self.min_signal}, "
            f"min_flat_ratio={self.min_flat_ratio}"
        )

    def _is_metric_flat(self, values: list) -> tuple[bool, float]:
        """
        Check if a single metric stream is flat within the window.

        Returns:
            (is_flat, cv) — boolean flag and computed CV value
        """
        if len(values) < 3:
            return False, 0.0

        arr = np.array(values, dtype=float)
        mean = np.mean(arr)

        # Guard: ignore metrics near zero (service down, no traffic)
        if mean < self.min_signal:
            return False, 0.0

        std = np.std(arr)
        cv = float(std / (mean + 1e-8))

        # Primary check: CV below threshold
        if cv >= self.cv_threshold:
            return False, cv

        # Secondary check: minimum flat samples within tight band
        band = mean * self.band_pct
        flat_samples = np.sum(np.abs(arr - mean) <= band)
        flat_ratio = flat_samples / len(arr)

        is_flat = flat_ratio >= self.min_flat_ratio
        return is_flat, cv

    def detect(self, window: list) -> dict:
        """
        Main entry point. Checks all metric streams for flatness.
        Returns result dict compatible with ZScoreFilter output.

        Args:
            window: list of dicts, each containing metric values

        Returns:
            dict with keys:
                passed_gate     — True if any metric is flat
                flagged_metrics — list of flat metric names
                cv_scores       — CV value per metric
                threshold       — configured cv_threshold
        """
        cv_scores = {}
        flagged = {}

        for metric in METRICS:
            values = [s.get(metric, 0.0) for s in window]
            is_flat, cv = self._is_metric_flat(values)
            cv_scores[metric] = round(cv, 6)
            if is_flat:
                flagged[metric] = cv

        passed_gate = len(flagged) > 0

        result = {
            "passed_gate": passed_gate,
            "flagged_metrics": list(flagged.keys()),
            "cv_scores": cv_scores,
            "threshold": self.cv_threshold,
        }

        if passed_gate:
            logger.info(f"Flatness gate PASSED — " f"flat metrics: {flagged}")
        else:
            logger.debug("Flatness gate blocked — no flat metrics detected")

        return result
