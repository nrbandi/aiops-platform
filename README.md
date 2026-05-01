# AI-Driven Agent for IT Infrastructure Monitoring and Management

**M.Tech Dissertation — Cloud Computing (CCZG628T)**
**Student ID:** 2024MT03056 | **Institution:** BITS Pilani WILP
**Academic Year:** 2024–2026

---

## Overview

This repository implements a pre-production AI-driven AIOps agent that
monitors IT infrastructure metrics, detects anomalies, recommends remediation
actions, and logs all decisions with full provenance. The system is grounded
in the OADA (Observe–Analyze–Decide–Act) pipeline, inspired by the MAPE-K
autonomic computing reference architecture, and framed theoretically as a
proto-BDI agent.

### Research Contributions

1. **Two-pass sequential anomaly detection** — Z-score pre-filter gates
   windows to Isolation Forest, reducing compounded false positives from
   the earlier parallel hybrid design.

2. **CV-based flatness detector** — Complements spike detection with
   lock-in anomaly detection (Coefficient of Variation < 0.005), enabling
   detection of resource exhaustion patterns not captured by Z-score alone.

3. **Z-score relative rule matching** — Playbook conditions evaluated
   against rolling baseline Z-scores rather than absolute thresholds,
   making the Decide layer context-aware across heterogeneous infrastructure.

4. **Configurable per-severity cooldown** — SRE-tunable alert suppression
   window per severity band, reducing carry-forward false positives while
   preserving sustained anomaly alerting.

5. **Dataset-agnostic adapter pattern** — AdapterFactory enables plug-and-play
   dataset integration without modifying pipeline code.

---

## Architecture
### Layer Descriptions

| Layer | Component | Purpose |
|-------|-----------|---------|
| Observe | AdapterFactory, GaiaAdapter, SyntheticAdapter | Dataset-agnostic metric ingestion |
| Analyze | ZScoreFilter, FlatnessDetector, IsolationForestScorer, EventCorrelator | Two-pass anomaly detection |
| Decide | RuleEngine, RecommendationEngine | Context-aware playbook matching |
| Act | ActionLog | Provenance logging with simulated execution |

---

## Datasets

### GAIA Companion Data (Primary Evaluation)
- **Source:** CloudWise Open Source (Apache 2.0)
- **Repository:** https://github.com/CloudWise-OpenSource/GAIA-DataSet
- **Subfolder used:** `metric_detection/low_signal-to-noise_ratio_data/`
- **Files used (4 metric streams):**
  - Index 0 → cpu_percent
  - Index 2 → disk_io_mbps
  - Index 3 → net_mbps
  - Index 4 → mem_percent (temporally aligned, same date range)
- **Anomaly rate:** 5.52% (477 labelled anomalies across 8,640 timesteps)
- **Known limitation:** log/error.csv timestamps (2021) misalign with
  metric timestamps (2019); log_score defaults to 0.0

### Synthetic Dataset (Secondary Evaluation)
- **Source:** Deterministic generator (SyntheticAdapter)
- **Scenarios (6):** cpu_spike, memory_leak, disk_saturation,
  network_flood, cascading_failure, antivirus_scan
- **Anomaly injection:** Every 5th cycle after 30-window warm-up

---

## Setup

### Prerequisites
- Ubuntu 20.04+ or macOS
- Python 3.12.3+
- Git

### 1. Clone Repository
```bash
git clone https://github.com/nrbandi/aiops-platform.git
cd aiops-platform
```

### 2. Create Virtual Environment
```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Download GAIA Dataset
```bash
mkdir -p data/gaia/raw/Companion_Data
git clone https://github.com/CloudWise-OpenSource/GAIA-DataSet.git \
    data/gaia/raw/Companion_Data

# Extract metric files
cd data/gaia/raw/Companion_Data/Companion_Data
unzip metric_detection.zip
cd ../..

# Move to expected path
mv Companion_Data/metric_detection .
cd /path/to/aiops-platform
```

### 5. Verify Setup
```bash
ls data/gaia/raw/Companion_Data/metric_detection/low_signal-to-noise_ratio_data/*.csv | wc -l
# Expected output: 50
```

---

## Running the Pipeline

All commands must be run from the **repository root**.

### Synthetic Dataset (no download required)
```bash
python3 services/agent/agent.py --adapter synthetic --cycles 500
```

### GAIA Dataset (full run)
```bash
python3 services/agent/agent.py --adapter gaia --cycles 9000
```

### Available Arguments
---

## Evaluation

### Compute Metrics
```bash
# All datasets
python3 evaluation/metrics.py

# Specific dataset
python3 evaluation/metrics.py --dataset gaia
python3 evaluation/metrics.py --dataset synthetic
```

### Bootstrap Confidence Intervals
```bash
# All datasets
python3 evaluation/bootstrap_ci.py

# Specific dataset
python3 evaluation/bootstrap_ci.py --dataset gaia --n 1000
```

---

## Key Results

### GAIA Dataset (Full — 8,640 timesteps)

| Metric | Value | 95% CI |
|--------|-------|--------|
| Precision | 0.348 | [0.323, 0.373] |
| Recall | 0.988 | [0.933, 1.000] |
| F1-score | 0.514 | [0.480, 0.544] |
| CRITICAL events | 296 TP / 0 FP | — |
| Labelled anomalies | 429 TP / 0 FP | — |

### Synthetic Dataset (500 cycles)

| Metric | Value | 95% CI |
|--------|-------|--------|
| Precision | 0.204 | [0.132, 0.281] |
| Recall | 0.262 | [0.170, 0.362] |
| F1-score | 0.229 | [0.149, 0.316] |
| Named scenarios | 25 TP / 0 FP | — |

### Key Finding
All labelled anomalies (gaia_anomaly scenario) and all CRITICAL severity
events were detected with **zero false positives**. Reported FPs correspond
to unlabelled anomalies in the GAIA dataset — manual inspection confirmed
genuine CPU drops (62–74%) in GT=0 labelled regions.

---

## Configuration

Configuration is centralised in `services/agent/config/agent_config.yaml`.

Key parameters:

```yaml
observe:
  window_size: 10              # Samples per window
  warmup_windows_demo: 30      # Warm-up in demo mode

analyze:
  isolation_forest:
    contamination: 0.055       # Matches GAIA 5.52% anomaly rate
  flatness:
    cv_threshold: 0.005        # CV below this = flat metric

decide:
  z_threshold: 1.5             # Z-score threshold for rule matching

act:
  cooldown_windows:
    CRITICAL: 5                # SRE-tunable per severity band
    HIGH: 10
    MEDIUM: 15
    LOW: 20

data:
  adapter: "gaia"              # Options: synthetic | gaia
  start_offset: 0              # Start row in GAIA dataset
```

---

## Repository Structure
---

## Known Limitations

See `LIMITATIONS.md` for full details. Key limitations:

1. **GAIA temporal mismatch** — log scores always 0.0
2. **Carry-forward false positives** — sliding window artefact
3. **Action layer is simulated** — no live infrastructure modification
4. **Incomplete GAIA labelling** — some FPs are genuine unlabelled anomalies
5. **No production deployment** — lab environment only

---

## Environment

| Component | Version |
|-----------|---------|
| Python | 3.12.3 |
| scikit-learn | 1.8.0 |
| pandas | 3.0.2 |
| numpy | 2.4.4 |
| scipy | 1.17.1 |

---

## Citation

If you use this work, please cite:
---

## License

This project is for academic research purposes only.
GAIA dataset is licensed under Apache 2.0 by CloudWise Open Source.
