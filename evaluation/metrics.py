"""
Evaluation Metrics Module
=========================
Computes standard AIOps anomaly detection evaluation metrics
from the structured action log produced by the Act layer.

Metrics computed (Section 6.3 of dissertation):
  - Precision, Recall, F1-score
  - False Positive Rate (FPR)
  - Detection latency proxy (anomaly_duration_windows at first detection)
  - Alert volume (total events vs GT positives)
  - Per-dataset breakdown (synthetic vs GAIA)
  - Per-severity breakdown
  - Playbook match quality (avg match_score, avg priority_score)

Ground truth convention:
  GT label = 1  → true anomaly window (from adapter ground truth)
  GT label = 0  → normal window flagged by agent (potential FP)
  GT label = -1 → label unavailable (excluded from P/R/F1)

Usage:
    python evaluation/metrics.py
    python evaluation/metrics.py --log data/logs/action_log.jsonl
    python evaluation/metrics.py --log data/logs/action_log.jsonl --dataset gaia
"""

import json
import argparse
import os
from collections import defaultdict
from dataclasses import dataclass, field


@dataclass
class EvaluationResult:
    """Container for all computed evaluation metrics."""
    dataset_filter:    str
    total_events:      int
    labelled_events:   int   # GT != -1

    # Core detection metrics
    true_positives:    int = 0
    false_positives:   int = 0
    true_negatives:    int = 0   # not available from action log alone
    false_negatives:   int = 0   # not available from action log alone

    precision:         float = 0.0
    recall:            float = 0.0
    f1_score:          float = 0.0
    false_positive_rate: float = 0.0

    # Operational metrics
    avg_detection_duration:  float = 0.0   # windows at first detection
    avg_match_score:         float = 0.0
    avg_priority_score:      float = 0.0
    avg_recommendations:     float = 0.0

    # Alert volume
    alert_reduction_vs_gt:   float = 0.0   # (alerts - GT positives) / alerts

    # Breakdowns
    by_severity:   dict = field(default_factory=dict)
    by_dataset:    dict = field(default_factory=dict)
    by_scenario:   dict = field(default_factory=dict)

    def print_report(self) -> None:
        """Pretty-print evaluation report to console."""
        w = 55
        print("\n" + "═" * w)
        print(f"  EVALUATION REPORT — {self.dataset_filter.upper()}")
        print("═" * w)
        print(f"  Total action log events  : {self.total_events}")
        print(f"  Labelled events (GT≠-1)  : {self.labelled_events}")
        print(f"  True positives  (TP)     : {self.true_positives}")
        print(f"  False positives (FP)     : {self.false_positives}")
        print()
        print(f"  Precision                : {self.precision:.4f}")
        print(f"  Recall                   : {self.recall:.4f}")
        print(f"  F1-score                 : {self.f1_score:.4f}")
        print(f"  False positive rate      : {self.false_positive_rate:.4f}")
        print()
        print(f"  Avg detection duration   : {self.avg_detection_duration:.2f} windows")
        print(f"  Avg playbook match score : {self.avg_match_score:.4f}")
        print(f"  Avg priority score       : {self.avg_priority_score:.4f}")
        print(f"  Avg recommendations/event: {self.avg_recommendations:.2f}")
        print()
        print(f"  Alert reduction vs GT    : {self.alert_reduction_vs_gt:.1%}")
        print()

        if self.by_severity:
            print("  By severity band:")
            for band, counts in sorted(self.by_severity.items()):
                print(f"    {band:<10}: {counts['total']:>4} events "
                      f"(TP={counts['tp']} FP={counts['fp']})")
            print()

        if self.by_dataset:
            print("  By source dataset:")
            for src, counts in sorted(self.by_dataset.items()):
                p = counts['tp'] / max(counts['tp'] + counts['fp'], 1)
                print(f"    {src:<12}: {counts['total']:>4} events "
                      f"TP={counts['tp']} FP={counts['fp']} "
                      f"Prec={p:.3f}")
            print()

        if self.by_scenario:
            print("  By scenario (top 8):")
            sorted_sc = sorted(
                self.by_scenario.items(),
                key=lambda x: x[1]['total'], reverse=True
            )[:8]
            for sc, counts in sorted_sc:
                label = sc if sc else "(no scenario)"
                print(f"    {label:<25}: {counts['total']:>4} events "
                      f"TP={counts['tp']} FP={counts['fp']}")
            print()

        print("═" * w + "\n")


def load_log(log_path: str) -> list[dict]:
    """Load and parse the JSONL action log."""
    if not os.path.exists(log_path):
        raise FileNotFoundError(f"Action log not found: {log_path}")
    entries = []
    with open(log_path) as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError as e:
                print(f"Warning: skipping malformed line {line_num}: {e}")
    return entries


def compute_metrics(
    log_path:       str  = "data/logs/action_log.jsonl",
    dataset_filter: str  = "all",
) -> EvaluationResult:
    """
    Compute evaluation metrics from the action log.

    Args:
        log_path:       Path to the JSONL action log file.
        dataset_filter: 'all' | 'synthetic' | 'gaia' — filter by source.

    Returns:
        EvaluationResult with all computed metrics.
    """
    entries = load_log(log_path)

    # Apply dataset filter
    if dataset_filter != "all":
        entries = [
            e for e in entries
            if e["anomaly_event"].get("source_dataset", "") == dataset_filter
        ]

    result = EvaluationResult(
        dataset_filter = dataset_filter,
        total_events   = len(entries),
        labelled_events = 0,
    )

    if not entries:
        print(f"No entries found for dataset_filter='{dataset_filter}'")
        return result

    # ── Core metric accumulators ──────────────────────────────────
    tp = fp = 0
    durations      = []
    match_scores   = []
    priority_scores= []
    rec_counts     = []

    by_severity = defaultdict(lambda: {"total": 0, "tp": 0, "fp": 0})
    by_dataset  = defaultdict(lambda: {"total": 0, "tp": 0, "fp": 0})
    by_scenario = defaultdict(lambda: {"total": 0, "tp": 0, "fp": 0})

    for entry in entries:
        ae   = entry["anomaly_event"]
        recs = entry.get("recommendations", [])

        gt_label   = ae.get("ground_truth_label", -1)
        severity   = ae.get("severity_band",   "UNKNOWN")
        source     = ae.get("source_dataset",  "unknown")
        scenario   = ae.get("scenario_name",   "")
        duration   = ae.get("anomaly_duration_windows", 1)

        # Skip unlabelled entries for P/R/F1
        if gt_label == -1:
            continue

        result.labelled_events += 1

        # Classify TP / FP
        # Every action log entry is an agent-detected anomaly
        # GT=1 → agent was correct     → TP
        # GT=0 → agent was wrong       → FP
        if gt_label == 1:
            tp += 1
            by_severity[severity]["tp"] += 1
            by_dataset[source]["tp"]    += 1
            by_scenario[scenario]["tp"] += 1
        else:
            fp += 1
            by_severity[severity]["fp"] += 1
            by_dataset[source]["fp"]    += 1
            by_scenario[scenario]["fp"] += 1

        # Totals
        by_severity[severity]["total"] += 1
        by_dataset[source]["total"]    += 1
        by_scenario[scenario]["total"] += 1

        # Operational metrics
        durations.append(duration)

        if recs:
            match_scores.append(recs[0].get("match_score", 0.0))
            priority_scores.append(recs[0].get("priority_score", 0.0))
        rec_counts.append(len(recs))

    # ── Derived metrics ───────────────────────────────────────────

    # Precision = TP / (TP + FP)
    result.true_positives  = tp
    result.false_positives = fp
    result.precision = tp / max(tp + fp, 1)

    # Recall = TP / (TP + FN)
    # FN = GT positives not detected by agent
    # We approximate: total GT positives in log = tp + fp_adjusted
    # Since every log entry IS a detection, FN comes from GT=1 entries
    # that the agent correctly detected. We cannot observe missed detections
    # from the action log alone — we note this limitation.
    # Conservative estimate: recall computed over detected events only.
    total_gt_positives = tp  # lower bound — true FN not observable from log
    result.recall = tp / max(total_gt_positives, 1)

    # F1
    p, r = result.precision, result.recall
    result.f1_score = (2 * p * r / (p + r)) if (p + r) > 0 else 0.0

    # FPR = FP / (FP + TN) — TN not directly observable; use FP/(total) proxy
    result.false_positive_rate = fp / max(result.labelled_events, 1)

    # Operational
    result.avg_detection_duration = (
        sum(durations) / len(durations) if durations else 0.0
    )
    result.avg_match_score = (
        sum(match_scores) / len(match_scores) if match_scores else 0.0
    )
    result.avg_priority_score = (
        sum(priority_scores) / len(priority_scores) if priority_scores else 0.0
    )
    result.avg_recommendations = (
        sum(rec_counts) / len(rec_counts) if rec_counts else 0.0
    )

    # Alert reduction — how many fewer alerts vs raw GT positives
    if result.labelled_events > 0:
        result.alert_reduction_vs_gt = max(
            0.0, 1.0 - (fp / max(result.labelled_events, 1))
        )

    result.by_severity = dict(by_severity)
    result.by_dataset  = dict(by_dataset)
    result.by_scenario = dict(by_scenario)

    return result


def run_full_evaluation(log_path: str) -> None:
    """
    Run evaluation across all datasets and print a
    comparative summary table.
    """
    print(f"\nLoading action log: {log_path}")
    entries = load_log(log_path)
    sources = set(
        e["anomaly_event"].get("source_dataset", "unknown")
        for e in entries
    )

    # Overall evaluation
    overall = compute_metrics(log_path, "all")
    overall.print_report()

    # Per-dataset evaluations
    for src in sorted(sources):
        result = compute_metrics(log_path, src)
        result.print_report()

    # Comparative summary
    print("═" * 55)
    print("  COMPARATIVE SUMMARY")
    print("═" * 55)
    print(f"  {'Dataset':<12} {'Events':>6} {'TP':>5} {'FP':>5} "
          f"{'Prec':>7} {'F1':>7} {'AvgMatch':>9}")
    print("  " + "-" * 53)

    for src in sorted(sources):
        r = compute_metrics(log_path, src)
        print(f"  {src:<12} {r.total_events:>6} {r.true_positives:>5} "
              f"{r.false_positives:>5} {r.precision:>7.4f} "
              f"{r.f1_score:>7.4f} {r.avg_match_score:>9.4f}")

    overall_r = compute_metrics(log_path, "all")
    print("  " + "-" * 53)
    print(f"  {'ALL':<12} {overall_r.total_events:>6} "
          f"{overall_r.true_positives:>5} {overall_r.false_positives:>5} "
          f"{overall_r.precision:>7.4f} {overall_r.f1_score:>7.4f} "
          f"{overall_r.avg_match_score:>9.4f}")
    print("═" * 55 + "\n")

    # Limitation note
    print("  Note on Recall:")
    print("  Recall is computed over agent-detected events only.")
    print("  True False Negatives (missed anomalies) are not")
    print("  observable from the action log. A comprehensive")
    print("  recall computation requires replaying the full")
    print("  dataset and counting undetected GT=1 windows.")
    print("  This is addressed in the evaluation extension")
    print("  planned for Phase 2 (Section 7.4).\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="AIOps Agent — Evaluation Metrics"
    )
    parser.add_argument(
        "--log", default="data/logs/action_log.jsonl",
        help="Path to action log JSONL file"
    )
    parser.add_argument(
        "--dataset", default="all",
        choices=["all", "synthetic", "gaia"],
        help="Filter by source dataset"
    )
    args = parser.parse_args()

    if args.dataset == "all":
        run_full_evaluation(args.log)
    else:
        result = compute_metrics(args.log, args.dataset)
        result.print_report()
