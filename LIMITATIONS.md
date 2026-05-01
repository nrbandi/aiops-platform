# Known Limitations and Future Work

**AI-Driven Agent for IT Infrastructure Monitoring and Management**
**Student ID:** 2024MT03056 | BITS Pilani WILP | May 2026

---

## Phase 2 Known Limitations

### 1. GAIA Temporal Mismatch (Log Signal)
**Issue:** `error.csv` timestamps are from 2021 while metric timestamps
are from 2019. The ±30s log scoring window finds no matching entries.
**Impact:** `log_anomaly_score` always defaults to 0.0. The log signal
dimension of the pipeline is non-functional on this dataset.
**Workaround:** Metrics-only evaluation. Severity labels derived from
metric ground truth labels.
**Future Work:** Align timestamps via synthetic log injection or use a
dataset with co-located metric and log timestamps.

### 2. Carry-Forward False Positives (Sliding Window Artefact)
**Issue:** When a point anomaly is injected at cycle t, the anomalous
sample persists within the rolling window of size w for w−1 subsequent
cycles, producing a tail of false positives.
**Impact:** Lower Precision on synthetic dataset (0.204) vs GAIA (0.348).
On synthetic data, all 96 FPs are carry-forward artefacts — every named
scenario was detected with zero FPs.
**Mitigation:** Configurable per-severity cooldown window implemented
(Section 7.2). Residual carry-forward suppressed for subsequent anomaly
events.
**Future Work:** Implement temporal deconvolution to attribute window-level
detections to individual point anomalies.

### 3. Action Layer is Simulated
**Current State:** The Act layer logs intent and provenance but does not
call live orchestration APIs.
**Out of Scope:** Production integration (Kubernetes API, Ansible, etc.)
is explicitly out of scope for this dissertation.
**Why:** Preventing unintended infrastructure modification in lab environment.
**Future Work (Phase 3):**
- REST API wrapper for Kubernetes scaling
- Ansible playbook execution engine
- Rollback mechanism with outcome monitoring

### 4. Incomplete GAIA Ground Truth Labelling
**Issue:** Manual inspection of false positive events reveals genuine metric
deviations (CPU drops from 99% to 62–74%) in regions labelled GT=0.
**Impact:** Reported precision (0.348) is a conservative lower bound.
True precision is likely higher.
**Evidence:** December 5, 2019 02:00–04:00 UTC — CPU drops to 62.5%
labelled GT=0, yet flagged by Isolation Forest as anomalous.
**Implication:** Our pipeline detects anomalies not captured in ground
truth, consistent with literature observations on incomplete AIOps labels.

### 5. No Production Deployment
**Current Scope:** Lab environment, offline dataset replay.
**Not Evaluated:**
- Live metric ingestion (Prometheus, Datadog, etc.)
- Real-time SLO validation
- Production SRE team interaction
- MTTR impact measurement
**Future Work:** Deploy to production cluster (e.g., Colruyt Group
infrastructure), monitor impact on mean time to resolution.

### 6. GAIA File Selection is Index-Based
**Issue:** Four metric files are selected from 50 by alphabetical sort
index (0, 2, 3, 4). This selection is reproducible but implicit.
**Impact:** A different sort order (e.g., locale change) could select
different files.
**Mitigation:** Selection is deterministic given fixed filesystem and
Python version. Documented in GaiaAdapter docstring.
**Future Work:** Make file selection explicit via config (filename mapping)
for full reproducibility transparency.

### 7. Learning Feedback Loop Deferred
**Current Implementation:** Rule confidence scores are static.
**Missing:**
- Outcome feedback (did the action resolve the anomaly?)
- Reinforcement learning for rule confidence tuning
- Automatic playbook discovery from historical incidents
**Design:** Transform 5 in RecommendationEngine is a placeholder for
this functionality (Phase 3).

### 8. Single-Node Monitoring Only
**Current Scope:** Four metrics from a single logical entity.
**Missing:** Multi-node correlation, service dependency graphs.
**Future Work:** EventCorrelator extension for cross-node causality.

---

## Research Boundaries

### In Scope
- Context-aware decision-making (Decide layer)
- Two-pass sequential anomaly detection
- Proto-BDI agent framework (reactive implementation)
- Dataset-agnostic observation pattern
- Simulated autonomous action with full provenance
- Statistical evaluation with bootstrap confidence intervals

### Explicitly Out of Scope
- Large-scale production deployment (>1,000 metrics)
- Full automation of complex remediation workflows
- Real-time SLA enforcement
- Multi-agent coordination
- Adversarial robustness testing
- Comparison with commercial AIOps tools (TCS ignio, Dynatrace)

---

## Performance Caveats

### Evaluation Methodology
- Recall computed as TP / total_GT_positives (fixed denominator)
- FN not directly observable from action log alone
- Bootstrap CIs assume IID resampling (may not hold for temporal data)
- Synthetic recall uses estimated GT+ (anomaly every 5th cycle)

### Generalisation
- Results specific to GAIA low_signal-to-noise_ratio_data subfolder
- Performance on spike-based anomalies (linear_data subfolder) not evaluated
- No cross-dataset validation (SMD, NAB) completed within dissertation scope

### Determinism
- Synthetic scenarios use seeded RNG (seed per cycle, reproducible)
- Isolation Forest uses fixed random_state=42
- Bootstrap CI uses fixed seed=42
- GAIA replay deterministic given start_offset=0

---

## Reproducing Results

```bash
# Setup
git clone https://github.com/nrbandi/aiops-platform.git
cd aiops-platform
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Download GAIA (see README.md for full instructions)

# Run full GAIA evaluation
rm -f data/logs/action_log.jsonl
python3 services/agent/agent.py --adapter gaia --cycles 9000
python3 evaluation/metrics.py --dataset gaia
python3 evaluation/bootstrap_ci.py --dataset gaia

# Run synthetic evaluation
python3 services/agent/agent.py --adapter synthetic --cycles 500
python3 evaluation/metrics.py --dataset synthetic
python3 evaluation/bootstrap_ci.py --dataset synthetic
```

Expected results:
- GAIA F1: 0.514 (95% CI: 0.480–0.544)
- Synthetic F1: 0.229 (95% CI: 0.149–0.316)
