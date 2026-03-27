"""
AIOps Agent — Main Pipeline Orchestrator
Section 4.1: Observe → Analyze → Decide → Act closed-loop pipeline.
Grounded in MAPE-K reference architecture (IBM autonomic computing).

B. Nageshwar Rao | 2024MT03056 | BITS WILP M.Tech Cloud Computing
"""

import time
import yaml
import logging
import argparse
import datetime
import sys
import os

# Ensure src/ is on path when running from project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.observe.collector import MetricCollector
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


def load_config(path: str = "config/agent_config.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def run_pipeline(
    config: dict,
    environment: str = "production",
    operator_role: str = "L2",
    max_cycles: int = None,
) -> None:
    """
    Main agent loop.
    Each cycle: collect → preprocess → z-score → isolation forest
                → correlate → match → recommend → log.

    Args:
        config:        Loaded agent config dict.
        environment:   Target environment (production/staging/development).
        operator_role: Operator tier for role-adapted recommendations (L1/L2/L3).
        max_cycles:    Stop after N cycles (None = run forever).
                       Set to small number for demo/testing.
    """
    logger.info("=" * 60)
    logger.info("AIOps Agent starting — BITS WILP Dissertation 2024MT03056")
    logger.info(f"Environment : {environment}")
    logger.info(f"Operator    : {operator_role}")
    logger.info(f"Demo mode   : {config['act']['demo_mode']}")
    logger.info("=" * 60)

    # --- Instantiate all layers ---
    collector = MetricCollector(config)
    preproc = Preprocessor()
    zscore = ZScoreFilter(config)
    iforest = IsolationForestScorer(config)
    correlator = EventCorrelator(config)
    rule_eng = RuleEngine(config)
    rec_eng = RecommendationEngine(config)
    action_log = ActionLog(config)

    poll_interval = config["observe"]["poll_interval_seconds"]
    demo_mode = config["act"]["demo_mode"]
    cycle = 0
    anomalies_detected = 0

    try:
        _last_anomalous_window = []
        while True:
            cycle += 1
            if max_cycles and cycle > max_cycles:
                logger.info(f"Reached max_cycles={max_cycles}. Stopping.")
                break

            logger.info(f"--- Cycle {cycle} ---")

            # ── OBSERVE ──────────────────────────────────────────────
            if demo_mode:
                window = _synthetic_window(config, cycle)
            else:
                window = collector.run_once()
                if window is None:
                    logger.debug("Window not yet full — waiting")
                    time.sleep(poll_interval)
                    continue

            # ── PREPROCESS ───────────────────────────────────────────
            matrix = preproc.process(window)

            # ── ANALYZE — Stage 1: Z-score ───────────────────────────
            zscore_result = zscore.filter(window)

            # ── ANALYZE — Stage 2: Isolation Forest ──────────────────
            if_result = iforest.score(window)

            # ── ANALYZE — Event Correlator ────────────────────────────
            event = correlator.correlate(zscore_result, if_result, window)

            if event is None:
                logger.info("No anomaly event formed — pipeline cycle complete")
                if not demo_mode:
                    time.sleep(poll_interval)
                continue

            anomalies_detected += 1
            logger.info(
                f"Anomaly #{anomalies_detected} detected — "
                f"{event['severity_band']} "
                f"(score={event['severity_score']})"
            )

            # ── DECIDE — Rule Engine ──────────────────────────────────
            # Cache the window that triggered the anomaly
            # so sustained events use the correct metric values
            if zscore_result.get("passed_gate") or if_result.get("is_anomaly"):
                _last_anomalous_window = window

            # ── DECIDE — Rule Engine ──────────────────────────────────
            matches = rule_eng.match(event, _last_anomalous_window or window)

            # ── DECIDE — Recommendation Engine ───────────────────────
            recommendations = rec_eng.generate(
                matches=matches,
                anomaly_event=event,
                environment=environment,
                operator_role=operator_role,
            )

            # ── ACT — Simulated Action Log ────────────────────────────
            window_meta = {
                "windows_seen": if_result.get("windows_seen"),
                "in_warmup": if_result.get("in_warmup"),
                "zscore_flagged": zscore_result.get("flagged_metrics"),
                "if_score": if_result.get("anomaly_score"),
            }
            entry = action_log.write(event, recommendations, window_meta)

            # ── PRINT RECOMMENDATION TO CONSOLE ──────────────────────
            _print_recommendation(entry, cycle)

            if not demo_mode:
                time.sleep(poll_interval)

    except KeyboardInterrupt:
        logger.info("Agent stopped by user (Ctrl+C)")

    finally:
        summary = action_log.summary()
        logger.info("=" * 60)
        logger.info("Session summary")
        logger.info(f"  Cycles run         : {cycle}")
        logger.info(f"  Anomalies detected : {anomalies_detected}")
        logger.info(f"  Log entries        : {summary.get('total_events', 0)}")
        logger.info(f"  CRITICAL           : {summary.get('critical', 0)}")
        logger.info(f"  HIGH               : {summary.get('high', 0)}")
        logger.info(f"  MEDIUM             : {summary.get('medium', 0)}")
        logger.info(f"  LOW                : {summary.get('low', 0)}")
        logger.info("=" * 60)


def _print_recommendation(entry: dict, cycle: int) -> None:
    """Pretty-print top recommendation to console for demo visibility."""
    ae = entry["anomaly_event"]
    recs = entry["recommendations"]
    print("\n" + "═" * 60)
    print(f"  ANOMALY DETECTED — Cycle {cycle}")
    print(f"  Severity   : {ae['severity_band']} (score={ae['severity_score']})")
    print(f"  Metrics    : {', '.join(ae['contributing_metrics'])}")
    print(f"  Duration   : {ae['anomaly_duration_windows']} window(s)")
    if recs:
        top = recs[0]
        print(f"\n  TOP RECOMMENDATION [{top['playbook_id']}]")
        print(f"  {top['playbook_name']}")
        print(f"  Match={top['match_score']} | Priority={top['priority_score']}")
        print(f"  Role: {top['operator_role']} | Env: {top['environment']}")
        print(f"\n  ACTION: {top['action']}")
    print("═" * 60 + "\n")


def _synthetic_window(config: dict, cycle: int) -> list:
    """
    Generate synthetic metric windows for demo mode.
    Uses seeded random for deterministic, repeatable demo runs.
    Injects anomaly pattern every 5th cycle after warmup.
    Patterns match Section 6.2 semi-synthetic dataset methodology.
    """
    import random
    import datetime

    rng = random.Random(cycle * 42)  # deterministic per cycle
    window_size = config["observe"]["window_size"]
    window = []
    anomaly = (cycle % 5 == 0) and (cycle >= 10)  # after warmup only

    for i in range(window_size):
        ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
        if anomaly:
            sample = {
                "timestamp": ts,
                "cpu_percent": rng.uniform(85.0, 97.0),
                "mem_percent": rng.uniform(82.0, 94.0),
                "disk_io_mbps": rng.uniform(20.0, 60.0),
                "net_mbps": rng.uniform(50.0, 200.0),
            }
        else:
            sample = {
                "timestamp": ts,
                "cpu_percent": rng.uniform(15.0, 40.0),
                "mem_percent": rng.uniform(30.0, 50.0),
                "disk_io_mbps": rng.uniform(5.0, 30.0),
                "net_mbps": rng.uniform(10.0, 80.0),
            }
        window.append(sample)
    return window


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="AIOps Agent — BITS WILP Dissertation 2024MT03056"
    )
    parser.add_argument(
        "--env",
        default="production",
        choices=["production", "staging", "development"],
        help="Target environment",
    )
    parser.add_argument(
        "--role",
        default="L2",
        choices=["L1", "L2", "L3"],
        help="Operator role for recommendations",
    )
    parser.add_argument(
        "--cycles",
        type=int,
        default=20,
        help="Number of pipeline cycles to run (default 20 for demo)",
    )
    args = parser.parse_args()
    config = load_config()
    run_pipeline(config, args.env, args.role, args.cycles)
