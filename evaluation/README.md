# Evaluation Metrics

Computes anomaly detection performance against ground truth labels
from the action log.

## Usage
```bash
# Full evaluation — all datasets
python evaluation/metrics.py

# Single dataset
python evaluation/metrics.py --dataset gaia
python evaluation/metrics.py --dataset synthetic

# Custom log path
python evaluation/metrics.py --log data/logs/action_log.jsonl
```

## Key Results (current run)

| Dataset   | Events | TP | FP | Precision | F1     |
|-----------|--------|----|----|-----------|--------|
| GAIA      | 35     | 31 | 4  | 0.8857    | 0.9394 |
| Synthetic | 25     | 5  | 20 | 0.2000    | 0.3333 |
| ALL       | 60     | 36 | 24 | 0.6000    | 0.7500 |

## Note on Recall

Recall = 1.0000 is an artefact of the action-log-only evaluation —
False Negatives (missed anomalies) are not observable from the log.
Full recall computation requires replaying the complete dataset and
counting undetected GT=1 windows. See Section 7.4 of dissertation.

## Note on Synthetic FP

The 20 synthetic FPs are co-occurrence carry-forward windows
(GT=0 windows following a GT=1 injection, sustained by the
Event Correlator's temporal grouping mechanism). Named-scenario
events are 100% TP. See Section 5.6 of dissertation.
