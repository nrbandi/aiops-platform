"""
Decide Layer — Rule Engine
Section 4.4.1 and Section 5.5.1.

Phase 1: Binary condition matching against 12 playbooks.
Phase 2: Weighted match scoring across all 15 playbooks.
         Match score = sum(weight_i * condition_met_i) / sum(weight_i)
         Only playbooks with match_score >= 0.5 are returned.
"""

import yaml
import logging

logger = logging.getLogger(__name__)

METRIC_MAP = {
    "cpu_percent": "cpu_percent",
    "mem_percent": "mem_percent",
    "disk_io_mbps": "disk_io_mbps",
    "net_mbps": "net_mbps",
}


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
        logger.info(
            f"RuleEngine loaded {len(self.playbooks)} playbooks from {playbook_path}"
        )

    def _compute_match_score(
        self,
        playbook: dict,
        anomaly_event: dict,
        window: list,
    ) -> float:
        """
        Phase 2 weighted match scoring — Section 7.3.
        For each condition in the playbook:
          - Check if the metric's window mean exceeds the threshold
          - Multiply by the condition weight
        Final score normalised to [0, 1].
        """
        conditions = playbook.get("conditions", {})
        total_weight = 0.0
        match_weight = 0.0

        # Compute per-metric window means from raw window
        window_means = {}
        if window:
            for m in METRIC_MAP:
                vals = [s.get(m, 0.0) for s in window]
                window_means[m] = sum(vals) / len(vals) if vals else 0.0

        for metric, spec in conditions.items():
            threshold = spec.get("threshold", 0.0)
            weight = spec.get("weight", 1.0)
            total_weight += weight
            if window_means.get(metric, 0.0) >= threshold:
                match_weight += weight

        if total_weight == 0:
            return 0.0
        return round(match_weight / total_weight, 4)

    def _severity_matches(self, playbook: dict, severity_band: str) -> bool:
        return severity_band in playbook.get("severity_band", [])

    def match(
        self,
        anomaly_event: dict,
        window: list,
    ) -> list:
        """
        Match event against all playbooks.
        Returns list of (playbook, match_score) sorted by score descending.
        Only returns matches with score >= 0.5.
        """
        severity_band = anomaly_event.get("severity_band", "MEDIUM")
        matches = []

        for pb in self.playbooks:
            score = self._compute_match_score(pb, anomaly_event, window)
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
