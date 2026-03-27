"""
Analyze Layer — Stage 2: Isolation Forest Scorer
Section 4.3.2: Second pass — multivariate anomaly scoring.
Only receives windows that passed the Z-score gate (Section 4.3.2).

Algorithm: Liu et al. (2008) — Isolation Forest.
Implementation: scikit-learn 1.8.0 IsolationForest.
Warm-up: minimum 288 windows (48 hours) before scoring — Section 5.6 Finding 1.
"""

import logging
import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

logger = logging.getLogger(__name__)

METRICS = ["cpu_percent", "mem_percent", "disk_io_mbps", "net_mbps"]


class IsolationForestScorer:
    """
    Maintains a rolling training buffer and an online-retrained
    Isolation Forest model. Returns a continuous anomaly score
    in [0, 1] where higher = more anomalous.

    Key design decisions from Section 5.6:
    - Warm-up extended to 288 windows (48h) to cover full daily cycles
    - Window size fixed at 10 samples (2.5 min persistence requirement)
    - contamination=0.05 from config
    """

    def __init__(self, config: dict):
        demo_mode = config["act"]["demo_mode"]
        self.warmup_windows = (
            config["observe"]["warmup_windows_demo"]
            if demo_mode
            else config["observe"]["warmup_windows"]
        )
        logger.info(
            f"Warmup mode: {'DEMO' if demo_mode else 'PRODUCTION'} "
            f"({self.warmup_windows} windows)"
        )
        self.contamination = config["analyze"]["isolation_forest"]["contamination"]
        self.n_estimators = config["analyze"]["isolation_forest"]["n_estimators"]
        self.random_state = config["analyze"]["isolation_forest"]["random_state"]
        self.window_size = config["observe"]["window_size"]

        self._buffer = []  # Accumulates feature vectors for training
        self._model = None
        self._scaler = StandardScaler()
        self._is_trained = False
        self._windows_seen = 0

        logger.info(
            f"IsolationForestScorer initialised — "
            f"warmup={self.warmup_windows} windows, "
            f"contamination={self.contamination}"
        )

    def _window_to_feature_vector(self, window: list) -> np.ndarray:
        """
        Flatten a window of samples into a single feature vector.
        Each window (10 samples × 4 metrics) → 40-dim vector.
        Captures temporal patterns within the window.
        """
        rows = []
        for sample in window:
            rows.append([sample.get(m, 0.0) for m in METRICS])
        arr = np.array(rows)  # shape: (window_size, 4)

        # Statistical features per metric across the window
        features = []
        for col in range(arr.shape[1]):
            features.extend(
                [
                    arr[:, col].mean(),
                    arr[:, col].std(),
                    arr[:, col].max(),
                    arr[:, col].min(),
                ]
            )
        return np.array(features)  # shape: (16,)

    def _train(self) -> None:
        """Retrain Isolation Forest on the accumulated buffer."""
        X = np.array(self._buffer)
        X_scaled = self._scaler.fit_transform(X)
        self._model = IsolationForest(
            n_estimators=self.n_estimators,
            contamination=self.contamination,
            random_state=self.random_state,
        )
        self._model.fit(X_scaled)
        self._is_trained = True
        logger.info(
            f"IsolationForest trained on {len(self._buffer)} windows "
            f"({len(self._buffer) * self.window_size * 15 / 3600:.1f}h of data)"
        )

    def score(self, window: list) -> dict:
        """
        Score a window. Returns anomaly score in [0,1] and
        a boolean anomaly flag.

        During warm-up, returns score=0.0 and is_anomaly=False.
        """
        fv = self._window_to_feature_vector(window)
        self._buffer.append(fv)
        self._windows_seen += 1

        # Warm-up phase
        if self._windows_seen < self.warmup_windows:
            remaining = self.warmup_windows - self._windows_seen
            logger.debug(f"Warm-up: {remaining} windows remaining")
            return {
                "is_anomaly": False,
                "anomaly_score": 0.0,
                "in_warmup": True,
                "windows_seen": self._windows_seen,
            }

        # Train on first full warm-up batch, then every 50 windows
        if not self._is_trained or self._windows_seen % 50 == 0:
            self._train()

        # Score current window
        fv_scaled = self._scaler.transform(fv.reshape(1, -1))
        # IF returns -1 (anomaly) or +1 (normal); score is inverted
        raw_score = self._model.decision_function(fv_scaled)[0]
        # Normalise to [0,1]: higher = more anomalous
        anomaly_score = float(1 / (1 + np.exp(raw_score * 3)))
        is_anomaly = self._model.predict(fv_scaled)[0] == -1

        result = {
            "is_anomaly": bool(is_anomaly),
            "anomaly_score": round(anomaly_score, 4),
            "in_warmup": False,
            "windows_seen": self._windows_seen,
        }

        if is_anomaly:
            logger.info(f"Isolation Forest ANOMALY — score={anomaly_score:.4f}")
        return result
