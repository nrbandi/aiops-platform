"""
AIOps Platform Agent — Main Pipeline Orchestrator
==================================================
Pre-production grade implementation.
Observe → Analyze → Decide → Act (closed-loop).

Dataset-agnostic: the adapter is selected via config.
B. Nageshwar Rao | 2024MT03056 | aiops-platform
"""

import sys
import os
import yaml
import logging
import argparse
import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.observe.adapters.adapter_factory import AdapterFactory
from src.observe.preprocessor import Preprocessor
from src.analyze.zscore_filter import ZScoreFilter
from src.analyze.isolation_forest import IsolationForestScorer
from src.analyze.event_correlator import EventCorrelator
from src.decide.rule_engine import RuleEngine
from src.decide.recommendation_engine import RecommendationEngine
from src.act.action_log import ActionLog

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("aiops.agent")


def load_config(path: str = "services/agent/config/agent_config.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def run_pipeline(
    config: dict,
    environment: str = "production",
    operator_role: str = "L2",
    max_cycles: int = None,
) -> None:

    adapter_name = config.get("data", {}).get("adapter", "synthetic")

    logger.info("=" * 60)
    logger.info("AIOps Platform Agent starting")
    logger.info(f"Adapter      : {adapter_name}")
    logger.info(f"Environment  : {environment}")
    logger.info(f"Operator     : {operator_role}")
    logger.info(f"Demo mode    : {config['act']['demo_mode']}")
    logger.info("=" * 60)

    # ── Instantiate all layers ────────────────────────────────────
    adapter = AdapterFactory.create(config)
    preproc = Preprocessor()
    zscore = ZScoreFilter(config)
    iforest = IsolationForestScorer(config)
    correlator = EventCorrelator(config)
    rule_eng = RuleEngine(config)
    rec_eng = RecommendationEngine(config)
    action_log = ActionLog(config)

    cycle = 0
    anomalies_detected = 0
    last_anomalous_window = []

    try:
        while True:
            cycle += 1
            if max_cycles and cycle > max_cycles:
                logger.info(f"Reached max_cycles={max_cycles}. Stopping.")
                break

            logger.info(f"--- Cycle {cycle} | adapter={adapter_name} ---")

            # ── OBSERVE ──────────────────────────────────────────
            metric_window = adapter.next_window()

            # Adapter exhausted (e.g. GAIA dataset fully replayed)
            if metric_window is None:
                if hasattr(adapter, "is_exhausted") and adapter.is_exhausted():
                    logger.info("Adapter exhausted — dataset replay complete.")
                    break
                logger.debug("Window not yet full — waiting")
                continue

            # Convert MetricWindow → list[dict] for existing layers
            window = metric_window.to_raw_samples()

            # Log signal — always compute, default 0.0
            avg_log_score = 0.0
            has_log_signal = metric_window.has_log_signal
            if has_log_signal:
                avg_log_score = sum(
                    e.log_anomaly_score for e in metric_window.events
                ) / len(metric_window.events)
                logger.info(f"Log signal detected — avg_score={avg_log_score:.3f}")

            gt_label = metric_window.ground_truth_label

            # ── PREPROCESS ───────────────────────────────────────
            preproc.process(window)

            # ── ANALYZE — Stage 1: Z-score ───────────────────────
            zscore_result = zscore.filter(window)

            # ── ANALYZE — Stage 2: Isolation Forest ──────────────
            if_result = iforest.score(window)

            # ── ANALYZE — Event Correlator ────────────────────────
            event = correlator.correlate(zscore_result, if_result, window)

            if event is None:
                logger.info(
                    f"No anomaly event — "
                    f"gt_label={gt_label} "
                    f"source={metric_window.source_dataset}"
                )
                continue

            # Cache anomalous window for rule matching
            if zscore_result.get("passed_gate") or if_result.get("is_anomaly"):
                last_anomalous_window = window

            anomalies_detected += 1

            # Enrich event with log signal and ground truth
            event["log_anomaly_score"] = avg_log_score if has_log_signal else 0.0
            event["ground_truth_label"] = gt_label
            event["source_dataset"] = metric_window.source_dataset
            event["scenario_name"] = metric_window.events[-1].scenario_name

            logger.info(
                f"Anomaly #{anomalies_detected} — "
                f"{event['severity_band']} "
                f"(score={event['severity_score']}) "
                f"gt={gt_label} "
                f"scenario={event['scenario_name']!r}"
            )

            # ── DECIDE — Rule Engine ──────────────────────────────
            matches = rule_eng.match(event, last_anomalous_window or window)

            # Log-signal playbook disambiguation
            if has_log_signal and avg_log_score > 0.6:
                logger.info(
                    "High log anomaly score — " "log-correlated playbooks prioritised"
                )

            # ── DECIDE — Recommendation Engine ───────────────────
            recommendations = rec_eng.generate(
                matches=matches,
                anomaly_event=event,
                environment=environment,
                operator_role=operator_role,
            )

            # ── ACT — Simulated Action Log ────────────────────────
            window_meta = {
                "windows_seen": if_result.get("windows_seen"),
                "in_warmup": if_result.get("in_warmup"),
                "zscore_flagged": zscore_result.get("flagged_metrics"),
                "if_score": if_result.get("anomaly_score"),
                "log_anomaly_score": event.get("log_anomaly_score", 0.0),
                "ground_truth_label": gt_label,
                "source_dataset": metric_window.source_dataset,
            }
            entry = action_log.write(event, recommendations, window_meta)
            _print_recommendation(entry, cycle)

    except KeyboardInterrupt:
        logger.info("Agent stopped by user (Ctrl+C)")

    finally:
        summary = action_log.summary()
        logger.info("=" * 60)
        logger.info("Session summary")
        logger.info(f"  Adapter            : {adapter_name}")
        logger.info(f"  Cycles run         : {cycle}")
        logger.info(f"  Anomalies detected : {anomalies_detected}")
        logger.info(f"  Log entries        : {summary.get('total_events', 0)}")
        logger.info(f"  CRITICAL           : {summary.get('critical', 0)}")
        logger.info(f"  HIGH               : {summary.get('high', 0)}")
        logger.info(f"  MEDIUM             : {summary.get('medium', 0)}")
        logger.info(f"  LOW                : {summary.get('low', 0)}")
        logger.info("=" * 60)


def _print_recommendation(entry: dict, cycle: int) -> None:
    ae = entry["anomaly_event"]
    recs = entry["recommendations"]
    meta = entry.get("pipeline_meta", {})
    print("\n" + "═" * 60)
    print(f"  ANOMALY DETECTED — Cycle {cycle}")
    print(f"  Severity     : {ae['severity_band']} (score={ae['severity_score']})")
    print(f"  Metrics      : {', '.join(ae['contributing_metrics'])}")
    print(f"  Duration     : {ae['anomaly_duration_windows']} window(s)")
    print(f"  Dataset      : {meta.get('source_dataset', 'unknown')}")
    print(f"  Scenario     : {ae.get('scenario_name', '—')}")
    print(f"  GT label     : {meta.get('ground_truth_label', '?')}")
    print(f"  Log score    : {meta.get('log_anomaly_score', 0.0):.3f}")
    if recs:
        top = recs[0]
        print(f"\n  TOP RECOMMENDATION [{top['playbook_id']}]")
        print(f"  {top['playbook_name']}")
        print(f"  Match={top['match_score']} | Priority={top['priority_score']}")
        print(f"\n  ACTION: {top['action']}")
    print("═" * 60 + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AIOps Platform Agent")
    parser.add_argument(
        "--adapter",
        default=None,
        choices=["synthetic", "gaia"],
        help="Override config adapter selection",
    )
    parser.add_argument(
        "--env",
        default="production",
        choices=["production", "staging", "development"],
    )
    parser.add_argument(
        "--role",
        default="L2",
        choices=["L1", "L2", "L3"],
    )
    parser.add_argument(
        "--cycles", type=int, default=30, help="Max pipeline cycles (default 30)"
    )
    parser.add_argument(
        "--config",
        default="services/agent/config/agent_config.yaml",
    )
    args = parser.parse_args()
    config = load_config(args.config)

    # CLI adapter override
    if args.adapter:
        config.setdefault("data", {})["adapter"] = args.adapter

    run_pipeline(config, args.env, args.role, args.cycles)
