"""
Decide Layer — Rule Engine
Section 4.4.1 and Section 5.5.1.

Phase 1: Binary condition matching against 12 playbooks.
Phase 2: Weighted match scoring across all 15 playbooks.
         Match score = sum(weight_i * condition_met_i) / sum(weight_i)
         Only playbooks with match_score >= 0.5 are returned.

Phase 2 Enhancement (Section 7.3):
    Z-score relative matching replaces absolute threshold matching.
    A playbook condition is met when the metric's Z-score (computed
    by the ZScoreFilter against the rolling baseline) exceeds the
    configured z_threshold. This makes the Rule Engine context-aware:
    the same absolute metric value triggers different responses
    depending on what is normal for that specific infrastructure.

    Match weight is further scaled by Z-score magnitude, so strongly
    anomalous metrics contribute more to the final match score.
"""

import yaml
import logging

logger = logging.getLogger(__name__)

METRICS = ["cpu_percent", "mem_percent", "disk_io_mbps", "net_mbps"]


class RuleEngine:
    """
    Matches a composite anomaly event against the playbook library.
    Returns a ranked list of matching playbooks with match scores.
    """

    def __init__(self, config: dict):
        playbook_path = config["decide"]["playbook_file"]
        with open(playbook_path) as f:
            data = yaml.safe_load(f)
        self.playbooks = data["playbooks"]
        self.z_threshold = config["decide"].get("z_threshold", 1.5)
        logger.info(
            f"RuleEngine loaded {len(self.playbooks)} playbooks "
            f"from {playbook_path} | z_threshold={self.z_threshold}"
        )

    def _compute_match_score(
        self,
        playbook: dict,
        anomaly_event: dict,
        window: list,
        zscore_result: dict,
    ) -> float:
        """
        Phase 2 Z-score relative matching — Section 7.3.

        For each condition in the playbook:
          - Retrieve the metric's Z-score from zscore_result
          - Condition is met if |Z| >= z_threshold
          - Match weight scaled by Z-score magnitude (capped at 2x)
          - Final score normalised to [0, 1]

        Falls back to absolute threshold matching if zscore_result
        does not contain the metric (e.g. insufficient history).
        """
        conditions = playbook.get("conditions", {})
        total_weight = 0.0
        match_weight = 0.0

        zscores = zscore_result.get("zscores", {})

        # Compute per-metric window means as fallback
        window_means = {}
        if window:
            for m in METRICS:
                vals = [s.get(m, 0.0) for s in window]
                window_means[m] = sum(vals) / len(vals) if vals else 0.0

        for metric, spec in conditions.items():
            threshold = spec.get("threshold", 0.0)
            weight = spec.get("weight", 1.0)
            total_weight += weight

            z = zscores.get(metric, None)

            if z is not None:
                # Z-score relative matching
                if abs(z) >= self.z_threshold:
                    # Scale weight by z-score magnitude (capped at 2x)
                    magnitude = min(abs(z) / self.z_threshold, 2.0)
                    match_weight += weight * magnitude
            else:
                # Fallback: absolute threshold matching
                if window_means.get(metric, 0.0) >= threshold:
                    match_weight += weight

        if total_weight == 0:
            return 0.0

        # Normalise — cap at 1.0 (magnitude scaling can exceed 1.0)
        return round(min(match_weight / total_weight, 1.0), 4)

    def _severity_matches(self, playbook: dict, severity_band: str) -> bool:
        return severity_band in playbook.get("severity_band", [])

    def match(
        self,
        anomaly_event: dict,
        window: list,
        zscore_result: dict = None,
    ) -> list:
        """
        Match event against all playbooks using Z-score relative matching.

        Args:
            anomaly_event: composite anomaly event dict
            window:        raw metric window (list of dicts)
            zscore_result: output from ZScoreFilter.filter() containing
                           per-metric Z-scores against rolling baseline

        Returns:
            Ranked list of matching playbooks with match scores >= 0.5.
        """
        if zscore_result is None:
            zscore_result = {}

        severity_band = anomaly_event.get("severity_band", "MEDIUM")
        matches = []

        for pb in self.playbooks:
            score = self._compute_match_score(pb, anomaly_event, window, zscore_result)
            if score >= 0.5:
                matches.append(
                    {
                        "playbook_id": pb["id"],
                        "playbook_name": pb["name"],
                        "match_score": score,
                        "actions": pb["actions"],
                        "tags": pb.get("tags", []),
                        "severity_band_match": self._severity_matches(
                            pb, severity_band
                        ),
                    }
                )

        # Sort by match score descending
        matches.sort(key=lambda x: x["match_score"], reverse=True)

        if matches:
            logger.info(
                f"RuleEngine matched {len(matches)} playbook(s) — "
                f"top: {matches[0]['playbook_id']} ({matches[0]['match_score']})"
            )
        else:
            logger.warning("RuleEngine — no playbook matched anomaly event")

        return matches
