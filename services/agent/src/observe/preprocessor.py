"""
Observe Layer — Preprocessor
Section 4.2.2: Range validation, normalisation, windowing.
Exponentially weighted min-max normalisation as described in Section 5.3.
"""

import logging
import numpy as np

logger = logging.getLogger(__name__)

METRIC_RANGES = {
    "cpu_percent": (0.0, 100.0),
    "mem_percent": (0.0, 100.0),
    "disk_io_mbps": (0.0, 10000.0),
    "net_mbps": (0.0, 10000.0),
}

METRICS = list(METRIC_RANGES.keys())


class Preprocessor:
    """
    Validates, normalises, and windows raw metric samples.
    Uses exponentially weighted bounds (alpha=0.01) so normalisation
    adapts gradually to long-term load shifts — Section 5.3.
    """

    def __init__(self, alpha: float = 0.01):
        self.alpha = alpha
        self._min = {m: METRIC_RANGES[m][0] for m in METRICS}
        self._max = {m: METRIC_RANGES[m][1] for m in METRICS}
        self._last = {m: 0.0 for m in METRICS}

    def validate(self, sample: dict) -> dict:
        """Range-clamp sample; replace OOB values with last valid."""
        clean = dict(sample)
        for m, (lo, hi) in METRIC_RANGES.items():
            v = clean.get(m, 0.0)
            if not (lo <= v <= hi):
                logger.warning(
                    f"OOB value {m}={v}, replacing with last valid {self._last[m]}"
                )
                clean[m] = self._last[m]
            else:
                self._last[m] = v
        return clean

    def normalise(self, sample: dict) -> dict:
        """Exponentially weighted min-max normalisation."""
        normed = {"timestamp": sample["timestamp"]}
        for m in METRICS:
            v = sample[m]
            self._min[m] = self.alpha * v + (1 - self.alpha) * self._min[m]
            self._max[m] = self.alpha * v + (1 - self.alpha) * self._max[m]
            denom = self._max[m] - self._min[m]
            normed[m] = (v - self._min[m]) / denom if denom > 1e-6 else 0.0
            normed[m] = float(np.clip(normed[m], 0.0, 1.0))
        return normed

    def window_to_matrix(self, window: list) -> np.ndarray:
        """Convert a list of normalised samples to an (N x 4) feature matrix."""
        return np.array([[s[m] for m in METRICS] for s in window])

    def process(self, window: list) -> np.ndarray:
        """Full pipeline: validate → normalise → matrix."""
        processed = [self.normalise(self.validate(s)) for s in window]
        return self.window_to_matrix(processed)
