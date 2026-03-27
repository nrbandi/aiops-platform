"""
Analyze Layer — Stage 1: Z-score Pre-filter
Section 4.3.2: First pass of the two-stage sequential detection pipeline.
Flags individual metric streams that deviate beyond the configured threshold.
Reduces false positives before the computationally heavier Isolation Forest.
"""

import logging
import numpy as np
from collections import deque

logger = logging.getLogger(__name__)

METRICS = ["cpu_percent", "mem_percent", "disk_io_mbps", "net_mbps"]


class ZScoreFilter:
    """
    Computes a rolling Z-score for each metric stream independently.
    A metric is flagged if |Z| exceeds the configured threshold.

    Design note (Section 4.3.2): This acts as a gate — only windows
    containing at least one flagged metric proceed to Isolation Forest.
    This eliminates compounded false positives from the earlier parallel
    hybrid design identified during Phase 1 testing.
    """

    def __init__(self, config: dict):
        demo_mode = config["act"]["demo_mode"]
        self.threshold = (
            config["analyze"]["zscore_threshold_demo"]
            if demo_mode
            else config["analyze"]["zscore_threshold"]
        )
        self.window_size = config["observe"]["window_size"]
        self._history = {m: deque(maxlen=200) for m in METRICS}
        logger.info(
            f"ZScoreFilter initialised — "
            f"threshold=±{self.threshold} "
            f"({'DEMO' if demo_mode else 'PRODUCTION'})"
        )

    def update_history(self, window: list) -> None:
        """Feed latest window samples into rolling history."""
        for sample in window:
            for m in METRICS:
                self._history[m].append(sample.get(m, 0.0))

    def compute_zscores(self, window: list) -> dict:
        """
        Compute Z-score for each metric using the window mean
        against the rolling historical distribution.
        Returns dict: metric -> z_score of window mean.
        """
        zscores = {}
        for m in METRICS:
            history = list(self._history[m])
            if len(history) < 3:
                # Insufficient history — skip flagging (warm-up)
                zscores[m] = 0.0
                continue
            mu = np.mean(history)
            sigma = np.std(history) + 1e-8  # epsilon avoids div-by-zero
            window_mean = np.mean([s.get(m, 0.0) for s in window])
            zscores[m] = float((window_mean - mu) / sigma)
        return zscores

    def filter(self, window: list) -> dict:
        """
        Main entry point. Updates history, computes Z-scores,
        returns a result dict with flagged metrics and pass/fail decision.
        """
        self.update_history(window)
        zscores = self.compute_zscores(window)
        flagged = {m: z for m, z in zscores.items() if abs(z) > self.threshold}
        passed_gate = len(flagged) > 0

        result = {
            "passed_gate": passed_gate,  # True = send to Isolation Forest
            "zscores": zscores,
            "flagged_metrics": list(flagged.keys()),
            "threshold": self.threshold,
        }

        if passed_gate:
            logger.info(f"Z-score gate PASSED — flagged: {flagged}")
        else:
            logger.debug("Z-score gate blocked — no anomalous metrics")

        return result
