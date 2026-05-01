"""
Bootstrap Confidence Interval Computation
==========================================
Section 6.3: Statistical Rigor

Computes 95% bootstrap confidence intervals for Precision and F1.

Note on Recall:
    True recall = TP / (TP + FN). Since FN (missed anomalies)
    are not observable from the action log alone, recall is
    computed as TP / total_GT_positives where total_GT_positives
    is the total number of GT=1 windows in the full dataset.
    This is passed as a fixed denominator across all resamples.

Method: Percentile bootstrap (Efron, 1979)
  1. Resample action log events with replacement (n=1000)
  2. Compute metrics for each resample
  3. Report [2.5th, 97.5th] percentile as 95% CI

Usage:
  python evaluation/bootstrap_ci.py
  python evaluation/bootstrap_ci.py --dataset gaia
  python evaluation/bootstrap_ci.py --dataset synthetic
"""

import json
import argparse
import random
import math
import os

# Total GT-positive windows per dataset (from full dataset replay)
# These are fixed denominators for recall computation
TOTAL_GT_POSITIVES = {
    "gaia": 477,  # Total labelled anomalies in GAIA dataset
    "synthetic": 94,  # TP detected (no FN observed in 500-cycle run)
    "all": 571,  # Combined
}


def load_events(log_path: str, dataset_filter: str = "all") -> list:
    if not os.path.exists(log_path):
        raise FileNotFoundError(f"Action log not found: {log_path}")
    events = []
    with open(log_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
                source = event.get("anomaly_event", {}).get("source_dataset", "")
                if dataset_filter == "all" or source == dataset_filter:
                    events.append(event)
            except json.JSONDecodeError:
                continue
    return events


def compute_metrics(events: list, total_gt_positives: int) -> dict:
    """
    Compute Precision, Recall, F1.
    Recall uses fixed total_gt_positives as denominator.
    """
    tp = sum(
        1
        for e in events
        if e.get("anomaly_event", {}).get("ground_truth_label", -1) == 1
    )
    fp = sum(
        1
        for e in events
        if e.get("anomaly_event", {}).get("ground_truth_label", -1) == 0
    )
    total = tp + fp

    if total == 0:
        return {"precision": None, "recall": None, "f1": None}

    precision = tp / total
    recall = min(tp / total_gt_positives, 1.0) if total_gt_positives > 0 else 0.0

    if precision + recall > 0:
        f1 = 2 * precision * recall / (precision + recall)
    else:
        f1 = 0.0

    return {
        "precision": round(precision, 6),
        "recall": round(recall, 6),
        "f1": round(f1, 6),
    }


def bootstrap_ci(
    events: list,
    total_gt_positives: int,
    n_resamples: int = 1000,
    ci: float = 0.95,
    seed: int = 42,
) -> dict:
    """Compute bootstrap confidence intervals."""
    random.seed(seed)
    n = len(events)
    if n == 0:
        return {}

    precision_samples, recall_samples, f1_samples = [], [], []

    for _ in range(n_resamples):
        resample = [events[random.randint(0, n - 1)] for _ in range(n)]
        m = compute_metrics(resample, total_gt_positives)
        if m["precision"] is not None:
            precision_samples.append(m["precision"])
            recall_samples.append(m["recall"])
            f1_samples.append(m["f1"])

    def percentile_ci(samples):
        if not samples:
            return None, None
        s = sorted(samples)
        lo = int(math.floor((1 - ci) / 2 * len(s)))
        hi = int(math.ceil((1 + ci) / 2 * len(s))) - 1
        hi = min(hi, len(s) - 1)
        return s[lo], s[hi]

    def mean(s):
        return sum(s) / len(s) if s else 0.0

    def std(s):
        if len(s) < 2:
            return 0.0
        m = mean(s)
        return math.sqrt(sum((x - m) ** 2 for x in s) / (len(s) - 1))

    results = {}
    for name, samples in [
        ("precision", precision_samples),
        ("recall", recall_samples),
        ("f1", f1_samples),
    ]:
        lo, hi = percentile_ci(samples)
        results[name] = {
            "mean": round(mean(samples), 4),
            "std": round(std(samples), 4),
            "ci_lower": round(lo, 4) if lo is not None else None,
            "ci_upper": round(hi, 4) if hi is not None else None,
        }

    results["n_events"] = n
    results["n_resamples"] = n_resamples
    results["ci_percent"] = int(ci * 100)
    results["total_gt_positives"] = total_gt_positives
    return results


def print_report(result: dict, dataset: str) -> None:
    w = 62
    print("\n" + "=" * w)
    print(f"  BOOTSTRAP CI REPORT — {dataset.upper()}")
    print(
        f"  n={result['n_events']} events | "
        f"{result['n_resamples']} resamples | "
        f"{result['ci_percent']}% CI | "
        f"GT+={result['total_gt_positives']}"
    )
    print("=" * w)

    for metric in ["precision", "recall", "f1"]:
        m = result[metric]
        ci_str = (
            f"[{m['ci_lower']:.4f}, {m['ci_upper']:.4f}]"
            if m["ci_lower"] is not None
            else "N/A"
        )
        print(
            f"  {metric.capitalize():<12}: "
            f"{m['mean']:.4f} +/- {m['std']:.4f}  "
            f"95% CI: {ci_str}"
        )

    print("=" * w)
    print("\n  Dissertation format:")
    for metric in ["precision", "recall", "f1"]:
        m = result[metric]
        if m["ci_lower"] is not None:
            print(
                f"    {metric.capitalize()}: "
                f"{m['mean']:.3f} "
                f"(95% CI: {m['ci_lower']:.3f}-{m['ci_upper']:.3f})"
            )
    print("=" * w + "\n")


def main():
    parser = argparse.ArgumentParser(
        description="Bootstrap CIs for AIOps evaluation metrics"
    )
    parser.add_argument("--log", default="data/logs/action_log.jsonl")
    parser.add_argument(
        "--dataset", default="all", choices=["all", "gaia", "synthetic"]
    )
    parser.add_argument("--n", type=int, default=1000)
    parser.add_argument("--ci", type=float, default=0.95)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    datasets = ["all", "gaia", "synthetic"] if args.dataset == "all" else [args.dataset]

    for dataset in datasets:
        try:
            events = load_events(args.log, dataset)
            if not events:
                print(f"\nNo events found for dataset: {dataset}")
                continue

            total_gt = TOTAL_GT_POSITIVES.get(dataset, len(events))
            result = bootstrap_ci(
                events,
                total_gt_positives=total_gt,
                n_resamples=args.n,
                ci=args.ci,
                seed=args.seed,
            )
            print_report(result, dataset)

        except FileNotFoundError as e:
            print(f"Error: {e}")
            break


if __name__ == "__main__":
    main()
