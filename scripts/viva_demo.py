#!/usr/bin/env python3
"""
Viva Demonstration Script
=========================
M.Tech Dissertation: AI-Driven Agent for IT Infrastructure Monitoring
Student ID : 2024MT03056
Institution: BITS Pilani WILP

Demonstrates the complete OADA pipeline on both datasets:
  1. Synthetic  — 6 named failure scenarios, controlled ground truth
  2. GAIA       — real-world CloudWise Companion Data

Usage:
  python3 scripts/viva_demo.py                  # both datasets
  python3 scripts/viva_demo.py --dataset synthetic
  python3 scripts/viva_demo.py --dataset gaia
  python3 scripts/viva_demo.py --cycles 100
"""

import sys
import os
import argparse
import subprocess
import json
from datetime import datetime

# Ensure repo root is working directory
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(REPO_ROOT)
sys.path.insert(0, REPO_ROOT)

AGENT = "services/agent/agent.py"
METRICS = "evaluation/metrics.py"
BOOTSTRAP = "evaluation/bootstrap_ci.py"
LOG_PATH = "data/logs/action_log.jsonl"
DIVIDER = "=" * 65


def banner():
    print(DIVIDER)
    print("  VIVA DEMONSTRATION — AI-Driven AIOps Agent")
    print("  Student ID : 2024MT03056 | BITS Pilani WILP")
    print(f"  Date       : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(DIVIDER)
    print()


def run(cmd: list, label: str) -> int:
    print(f"[{label}] Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=REPO_ROOT)
    return result.returncode


def show_sample_log(dataset: str, n: int = 3):
    """Show n sample provenance log entries for the dataset."""
    if not os.path.exists(LOG_PATH):
        print("  No action log found.")
        return

    print(f"\n  Sample Provenance Logs ({dataset.upper()} — first {n} events):")
    print("  " + "-" * 60)

    count = 0
    with open(LOG_PATH) as f:
        for line in f:
            try:
                e = json.loads(line)
                if e["anomaly_event"]["source_dataset"] != dataset:
                    continue
                ae = e["anomaly_event"]
                rec = e["recommendations"][0] if e["recommendations"] else {}
                print(
                    f"  Anomaly    : {ae['severity_band']} "
                    f"(score={ae['severity_score']:.3f})"
                )
                print(f"  Metrics    : {ae['contributing_metrics']}")
                print(f"  Duration   : {ae['anomaly_duration_windows']} windows")
                print(f"  GT label   : {ae['ground_truth_label']}")
                print(
                    f"  Playbook   : {rec.get('playbook_id','—')} — "
                    f"{rec.get('playbook_name','—')}"
                )
                print(f"  Action     : {rec.get('action','—')[:80]}")
                print(f"  Timestamp  : {ae.get('detection_timestamp','—')}")
                print("  " + "-" * 60)
                count += 1
                if count >= n:
                    break
            except (json.JSONDecodeError, KeyError):
                continue

    if count == 0:
        print(f"  No events found for dataset: {dataset}")


def run_dataset(dataset: str, cycles: int):
    print(f"\n{DIVIDER}")
    print(f"  PHASE: {dataset.upper()} DATASET")
    print(DIVIDER)

    # Clear log only before first dataset run
    # (handled by caller)
    pass

    # Run pipeline
    rc = run(
        ["python3", AGENT, "--adapter", dataset, "--cycles", str(cycles)],
        "OBSERVE→ANALYZE→DECIDE→ACT",
    )
    if rc != 0:
        print(f"  Pipeline failed (exit code {rc})")
        return

    # Show sample provenance logs
    show_sample_log(dataset)

    # Evaluation metrics
    print(f"\n[EVALUATION] Metrics for {dataset.upper()}:")
    run(["python3", METRICS, "--dataset", dataset], "METRICS")

    # Bootstrap CI
    print(f"\n[BOOTSTRAP] 95% Confidence Intervals for {dataset.upper()}:")
    run(["python3", BOOTSTRAP, "--dataset", dataset, "--n", "500"], "BOOTSTRAP CI")


def main():
    parser = argparse.ArgumentParser(
        description="Viva demonstration script for AIOps agent"
    )
    parser.add_argument(
        "--dataset",
        choices=["synthetic", "gaia", "both"],
        default="both",
        help="Dataset to demonstrate (default: both)",
    )
    parser.add_argument(
        "--cycles",
        type=int,
        default=500,
        help="Pipeline cycles per dataset (default: 200)",
    )
    args = parser.parse_args()

    banner()

    # Clear log once before all runs
    if os.path.exists(LOG_PATH):
        os.remove(LOG_PATH)

    datasets = ["synthetic", "gaia"] if args.dataset == "both" else [args.dataset]

    for dataset in datasets:
        run_dataset(dataset, args.cycles)

    print(f"\n{DIVIDER}")
    print("  VIVA DEMO COMPLETE")
    print(f"  Provenance log: {LOG_PATH}")
    print(DIVIDER)


if __name__ == "__main__":
    main()
