"""
Decide Layer — Recommendation Engine
Section 4.4.2 and Section 5.5.2.

Applies four transformations to matched playbooks:
  1. Environment-based filtering  — suppress production-disruptive actions
  2. Time-window filtering        — defer disruptive actions in business hours
  3. Dynamic prioritisation       — rank by SLA impact, blast radius, confidence
  4. Operator role adaptation     — tailor recommendation text to L1/L2/L3
"""

import logging
import datetime

logger = logging.getLogger(__name__)

# Severity → SLA impact weight (Section 4.4.2)
SLA_WEIGHTS = {
    "CRITICAL": 1.0,
    "HIGH": 0.75,
    "MEDIUM": 0.5,
    "LOW": 0.25,
}

# Metrics contributing to blast radius (broader = higher radius)
BLAST_RADIUS_WEIGHTS = {
    1: 0.25,
    2: 0.50,
    3: 0.75,
    4: 1.00,
}


class RecommendationEngine:
    """
    Transforms matched playbooks into prioritised, context-aware,
    operator-role-adapted recommendations.
    """

    def __init__(self, config: dict):
        self.environments = config["decide"]["environments"]
        self.biz_start = config["decide"]["business_hours"]["start"]
        self.biz_end = config["decide"]["business_hours"]["end"]
        self.operator_roles = config["decide"]["operator_roles"]
        logger.info(
            f"RecommendationEngine initialised — "
            f"roles={self.operator_roles}, "
            f"biz_hours={self.biz_start}:00–{self.biz_end}:00"
        )

    def _is_business_hours(self) -> bool:
        hour = datetime.datetime.now().hour
        return self.biz_start <= hour < self.biz_end

    def _is_disruptive(self, action_text: str) -> bool:
        """Flag actions that could disrupt production."""
        disruptive_keywords = [
            "restart",
            "kill",
            "shutdown",
            "reboot",
            "failover",
            "rollback",
            "terminate",
        ]
        return any(kw in action_text.lower() for kw in disruptive_keywords)

    def _environment_filter(self, action: str, environment: str) -> str:
        """
        Production environment: wrap disruptive actions with a warning.
        Staging/dev: allow all actions.
        """
        if environment == "production" and self._is_disruptive(action):
            return f"[PRODUCTION GUARD] Requires L3 approval before execution. {action}"
        return action

    def _time_filter(self, action: str) -> str:
        """Defer disruptive actions during business hours."""
        if self._is_business_hours() and self._is_disruptive(action):
            return (
                f"[DEFERRED — business hours] Schedule for maintenance window. {action}"
            )
        return action

    def _compute_priority_score(
        self,
        match: dict,
        anomaly_event: dict,
    ) -> float:
        """
        Dynamic priority score — Section 4.4.2.
        priority = w_sla * sla_impact + w_blast * blast_radius + w_conf * match_score
        """
        severity = anomaly_event.get("severity_band", "MEDIUM")
        n_metrics = len(anomaly_event.get("contributing_metrics", []))
        sla_impact = SLA_WEIGHTS.get(severity, 0.5)
        blast_radius = BLAST_RADIUS_WEIGHTS.get(min(n_metrics, 4), 0.25)
        match_score = match.get("match_score", 0.5)

        priority = (0.4 * sla_impact) + (0.35 * blast_radius) + (0.25 * match_score)
        return round(priority, 4)

    def _adapt_for_role(self, actions: dict, role: str) -> str:
        """
        Return role-specific action text.
        Falls back to L2 if role not found in playbook.
        """
        return actions.get(role, actions.get("L2", "Investigate and escalate."))

    def generate(
        self,
        matches: list,
        anomaly_event: dict,
        environment: str = "production",
        operator_role: str = "L2",
    ) -> list:
        """
        Main entry point.
        Returns a ranked list of recommendation dicts ready for the Act layer.
        """
        if not matches:
            logger.warning("RecommendationEngine — no matches to process")
            return []

        recommendations = []

        for match in matches:
            actions = match.get("actions", {})
            raw_action = self._adapt_for_role(actions, operator_role)

            # Apply filters
            action = self._environment_filter(raw_action, environment)
            action = self._time_filter(action)

            priority = self._compute_priority_score(match, anomaly_event)

            rec = {
                "playbook_id": match["playbook_id"],
                "playbook_name": match["playbook_name"],
                "match_score": match["match_score"],
                "priority_score": priority,
                "operator_role": operator_role,
                "environment": environment,
                "action": action,
                "tags": match.get("tags", []),
                "severity_band": anomaly_event.get("severity_band", "MEDIUM"),
                "in_business_hours": self._is_business_hours(),
            }
            recommendations.append(rec)

        # Sort by priority score descending
        recommendations.sort(key=lambda x: x["priority_score"], reverse=True)

        logger.info(
            f"RecommendationEngine generated {len(recommendations)} recommendation(s) "
            f"for role={operator_role}, env={environment}"
        )
        return recommendations
