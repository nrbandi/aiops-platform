"""
Act Layer — Simulated Action Log
Section 4.5 and Section 5.5.3.

Every anomaly event processed through the complete pipeline produces
a structured JSON log entry. The log is the primary output artefact
reviewed during evaluation — Section 6.1.

Scope note (Section 2.4): The Act layer records what actions WOULD be
taken. It does not modify live infrastructure. This enables safe
evaluation and progressive operator trust-building.
"""

import json
import logging
import datetime
import os

logger = logging.getLogger(__name__)


class ActionLog:
    """
    Persists simulated action recommendations as structured JSONL
    (one JSON object per line) for programmatic analysis and
    human-readable review during evaluation.
    """

    def __init__(self, config: dict):
        self.log_path = config["act"]["log_path"]
        self.demo_mode = config["act"]["demo_mode"]
        # Ensure log directory exists
        os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
        logger.info(
            f"ActionLog initialised — path={self.log_path}, "
            f"demo_mode={self.demo_mode}"
        )

    def _build_entry(
        self,
        anomaly_event: dict,
        recommendations: list,
        window_meta: dict,
    ) -> dict:
        """
        Build a complete structured log entry.
        Format matches Section 4.5.1 of the dissertation.
        """
        return {
            "log_timestamp": datetime.datetime.utcnow().isoformat() + "Z",
            "demo_mode": self.demo_mode,
            "anomaly_event": {
                "severity_band": anomaly_event.get("severity_band"),
                "severity_score": anomaly_event.get("severity_score"),
                "contributing_metrics": anomaly_event.get("contributing_metrics"),
                "anomaly_duration_windows": anomaly_event.get(
                    "anomaly_duration_windows"
                ),
                "detection_timestamp": anomaly_event.get("detection_timestamp"),
            },
            "pipeline_meta": {
                "windows_seen": window_meta.get("windows_seen"),
                "in_warmup": window_meta.get("in_warmup"),
                "zscore_flagged": window_meta.get("zscore_flagged"),
                "if_score": window_meta.get("if_score"),
            },
            "recommendations": [
                {
                    "rank": i + 1,
                    "playbook_id": r["playbook_id"],
                    "playbook_name": r["playbook_name"],
                    "match_score": r["match_score"],
                    "priority_score": r["priority_score"],
                    "operator_role": r["operator_role"],
                    "environment": r["environment"],
                    "severity_band": r["severity_band"],
                    "action": r["action"],
                    "tags": r["tags"],
                    "in_business_hours": r["in_business_hours"],
                }
                for i, r in enumerate(recommendations)
            ],
            "simulated_action": {
                "status": "LOGGED",
                "note": "Simulated — no live infrastructure modified (Section 2.4)",
                "top_action": (
                    recommendations[0]["action"] if recommendations else "None"
                ),
            },
        }

    def write(
        self,
        anomaly_event: dict,
        recommendations: list,
        window_meta: dict,
    ) -> dict:
        """
        Write one log entry to the JSONL file.
        Returns the entry for immediate display/testing.
        """
        entry = self._build_entry(anomaly_event, recommendations, window_meta)
        with open(self.log_path, "a") as f:
            f.write(json.dumps(entry) + "\n")
        logger.info(
            f"ActionLog entry written — "
            f"severity={entry['anomaly_event']['severity_band']}, "
            f"recommendations={len(recommendations)}"
        )
        return entry

    def read_all(self) -> list:
        """Read and return all log entries for evaluation."""
        if not os.path.exists(self.log_path):
            return []
        entries = []
        with open(self.log_path) as f:
            for line in f:
                line = line.strip()
                if line:
                    entries.append(json.loads(line))
        return entries

    def summary(self) -> dict:
        """Quick summary stats for evaluation — Section 6.3."""
        entries = self.read_all()
        if not entries:
            return {"total_events": 0}
        bands = [e["anomaly_event"]["severity_band"] for e in entries]
        return {
            "total_events": len(entries),
            "critical": bands.count("CRITICAL"),
            "high": bands.count("HIGH"),
            "medium": bands.count("MEDIUM"),
            "low": bands.count("LOW"),
            "avg_recommendations": round(
                sum(len(e["recommendations"]) for e in entries) / len(entries), 2
            ),
        }
