"""
GAIA Dataset Adapter
====================
Reads the CloudWise GAIA dataset (Apache 2.0) and produces
MetricEvent objects for the agent pipeline.

GAIA structure used:
  Companion Data / metric_detection/
      *.csv  — labeled time series, one per KPI
      Fields: timestamp (13-digit ms epoch), value, label

  MicroSS / log / log_semantics_anomaly_detection/
      *.csv  — log entries with anomaly labels
      Fields: datetime (YYYY-MM-DD hh:mm:ss), level, message, label

Citation:
  CloudWise Open Source, "GAIA: Generic AIOps Atlas Dataset,"
  GitHub, 2021. Apache 2.0 License.
  https://github.com/CloudWise-OpenSource/GAIA-DataSet

Mapping strategy:
  GAIA has many KPI files. We select four that best approximate
  your four metric streams using these heuristics:
    cpu_percent  ← file containing 'cpu' in filename
    mem_percent  ← file containing 'mem' in filename
    disk_io_mbps ← file containing 'disk' or 'io' in filename
    net_mbps     ← file containing 'net' or 'byte' in filename
  If a KPI file is not found, the adapter falls back to
  a zero-noise baseline so the pipeline never crashes.
"""

import os
import logging
import datetime
import pandas as pd
import numpy as np
from collections import deque
from src.observe.schema import MetricEvent, MetricWindow

logger = logging.getLogger(__name__)

# Error keywords for log anomaly scoring
# Sourced from De la Cruz Cabello et al. (2026) Section 4.2.3
LOG_ANOMALY_KEYWORDS = {
    "error",
    "fail",
    "failed",
    "failure",
    "panic",
    "oom",
    "kill",
    "killed",
    "crash",
    "crashed",
    "exception",
    "fatal",
    "critical",
    "alert",
    "segfault",
    "timeout",
    "refused",
    "unavailable",
}


class GaiaAdapter:
    """
    Replays the GAIA dataset as a stream of MetricEvent objects.
    Supports configurable replay speed for demo and evaluation modes.
    """

    def __init__(self, config: dict):
        self.window_size = config["observe"]["window_size"]
        self.gaia_data_path = config.get("data", {}).get("gaia_path", "data/gaia")
        self.replay_speed = config.get("data", {}).get(
            "replay_speed", 1.0
        )  # 1.0 = real-time, 10.0 = 10x fast

        self._metric_dfs = {}  # kpi_name -> DataFrame
        self._log_df = None
        self._cursor = 0  # current row position
        self._window_buffer = deque(maxlen=self.window_size)
        self._total_rows = 0

        self._load_data()
        logger.info(
            f"GaiaAdapter initialised — "
            f"rows={self._total_rows}, "
            f"replay_speed={self.replay_speed}x, "
            f"has_logs={self._log_df is not None}"
        )

    # ── Data loading ─────────────────────────────────────────────

    def _load_data(self) -> None:
        """Load and align GAIA metric and log CSVs."""
        metric_path = os.path.join(self.gaia_data_path, "metric")
        log_path = os.path.join(self.gaia_data_path, "log")

        if not os.path.exists(metric_path):
            logger.warning(
                f"GAIA metric path not found: {metric_path}. "
                "Adapter will produce zero-baseline data."
            )
            return

        self._load_metrics(metric_path)
        if os.path.exists(log_path):
            self._load_logs(log_path)

    def _load_metrics(self, metric_path: str) -> None:
        """
        Discover and load metric CSVs.
        Maps filenames to the four canonical metric streams.
        """
        mapping = {
            "cpu_percent": ["cpu", "processor"],
            "mem_percent": ["mem", "memory", "ram"],
            "disk_io_mbps": ["disk", "io", "read", "write"],
            "net_mbps": ["net", "network", "byte", "traffic"],
        }

        csv_files = [f for f in os.listdir(metric_path) if f.endswith(".csv")]

        for metric_key, keywords in mapping.items():
            matched = None
            for fname in csv_files:
                fname_lower = fname.lower()
                if any(kw in fname_lower for kw in keywords):
                    matched = fname
                    break

            if matched:
                fpath = os.path.join(metric_path, matched)
                try:
                    df = pd.read_csv(fpath)
                    df = self._normalise_metric_df(df, metric_key)
                    self._metric_dfs[metric_key] = df
                    logger.info(
                        f"GAIA metric loaded: {matched} → {metric_key} "
                        f"({len(df)} rows)"
                    )
                except Exception as e:
                    logger.warning(
                        f"Failed to load {matched}: {e}. " "Using zero baseline."
                    )
            else:
                logger.warning(
                    f"No GAIA file matched for {metric_key}. " "Using zero baseline."
                )

        # Determine total rows from the longest series
        if self._metric_dfs:
            self._total_rows = max(len(df) for df in self._metric_dfs.values())

    def _normalise_metric_df(self, df: pd.DataFrame, metric_key: str) -> pd.DataFrame:
        """
        Normalise GAIA metric CSV to standard columns:
        [timestamp, value, label]
        Handles both 13-digit epoch timestamps and
        YYYY-MM-DD hh:mm:ss strings.
        """
        # Standardise timestamp column
        ts_col = next(
            (c for c in df.columns if "time" in c.lower() or "date" in c.lower()),
            df.columns[0],
        )
        df = df.rename(columns={ts_col: "timestamp"})

        # Convert 13-digit epoch (ms) to ISO string
        if df["timestamp"].dtype in (np.int64, np.float64):
            df["timestamp"] = pd.to_datetime(
                df["timestamp"], unit="ms", utc=True
            ).dt.strftime("%Y-%m-%dT%H:%M:%SZ")

        # Standardise value column
        val_col = next(
            (c for c in df.columns if "value" in c.lower() or "val" in c.lower()), None
        )
        if val_col is None:
            # Pick the first numeric column that is not timestamp
            numeric_cols = df.select_dtypes(include=np.number).columns
            val_col = numeric_cols[0] if len(numeric_cols) > 0 else None

        if val_col:
            df = df.rename(columns={val_col: "value"})

        # Ensure label column exists
        if "label" not in df.columns:
            df["label"] = 0

        # Normalise value to appropriate range
        df["value"] = self._rescale(df["value"], metric_key)

        return df[["timestamp", "value", "label"]].reset_index(drop=True)

    def _rescale(self, series: pd.Series, metric_key: str) -> pd.Series:
        """
        Rescale raw GAIA values to the ranges expected by the agent.
        GAIA stores normalised or raw KPI values — we map them to
        realistic infrastructure metric ranges.
        """
        s = series.fillna(0.0)
        ranges = {
            "cpu_percent": (0.0, 100.0),
            "mem_percent": (0.0, 100.0),
            "disk_io_mbps": (0.0, 500.0),
            "net_mbps": (0.0, 1000.0),
        }
        lo, hi = ranges.get(metric_key, (0.0, 100.0))
        s_min, s_max = s.min(), s.max()
        if s_max - s_min < 1e-6:
            return pd.Series([lo] * len(s))
        return lo + (s - s_min) / (s_max - s_min) * (hi - lo)

    def _load_logs(self, log_path: str) -> None:
        """
        Load GAIA log semantics anomaly detection CSV.
        Computes a log_anomaly_score per timestamp window
        using keyword matching.
        """
        log_files = []
        for root, _, files in os.walk(log_path):
            for f in files:
                if f.endswith(".csv"):
                    log_files.append(os.path.join(root, f))

        if not log_files:
            logger.info("No GAIA log CSV found.")
            return

        try:
            dfs = []
            for fpath in log_files[:3]:  # Load up to 3 log files
                df = pd.read_csv(fpath)
                dfs.append(df)
            self._log_df = pd.concat(dfs, ignore_index=True)
            logger.info(
                f"GAIA logs loaded: {len(self._log_df)} entries "
                f"from {len(log_files)} file(s)"
            )
        except Exception as e:
            logger.warning(f"GAIA log loading failed: {e}")
            self._log_df = None

    # ── Scoring ───────────────────────────────────────────────────

    def _compute_log_anomaly_score(self, timestamp: str) -> tuple[float, str]:
        """
        Compute log_anomaly_score for a given timestamp window
        using keyword matching. Returns (score, raw_log_text).
        """
        if self._log_df is None:
            return 0.0, ""

        try:
            # Find log entries within ±30 seconds of the timestamp
            ts = pd.Timestamp(timestamp)
            time_col = next(
                (
                    c
                    for c in self._log_df.columns
                    if "time" in c.lower() or "date" in c.lower()
                ),
                None,
            )
            if time_col is None:
                return 0.0, ""

            log_times = pd.to_datetime(self._log_df[time_col], errors="coerce")
            mask = (log_times >= ts - pd.Timedelta(seconds=30)) & (
                log_times <= ts + pd.Timedelta(seconds=30)
            )
            nearby_logs = self._log_df[mask]

            if nearby_logs.empty:
                return 0.0, ""

            # Score = fraction of nearby log lines containing
            # anomaly keywords
            msg_col = next(
                (
                    c
                    for c in nearby_logs.columns
                    if "msg" in c.lower()
                    or "content" in c.lower()
                    or "value" in c.lower()
                ),
                None,
            )
            if msg_col is None:
                return 0.0, ""

            messages = nearby_logs[msg_col].fillna("").str.lower()
            anomaly_count = messages.apply(
                lambda m: any(kw in m for kw in LOG_ANOMALY_KEYWORDS)
            ).sum()
            score = float(anomaly_count / max(len(messages), 1))
            raw_text = " | ".join(messages.head(3).tolist())
            return round(min(score, 1.0), 4), raw_text

        except Exception as e:
            logger.debug(f"Log scoring error: {e}")
            return 0.0, ""

    # ── Streaming ─────────────────────────────────────────────────

    def _get_metric_value(self, metric_key: str, row_idx: int) -> tuple[float, int]:
        """Retrieve (value, label) at row_idx for a metric."""
        df = self._metric_dfs.get(metric_key)
        if df is None or row_idx >= len(df):
            return 0.0, 0
        row = df.iloc[row_idx % len(df)]
        return float(row["value"]), int(row.get("label", 0))

    def next_window(self) -> MetricWindow | None:
        """
        Advance one replay step. Returns MetricWindow when
        the sliding window is full, else None.

        Returns None also when the dataset is exhausted.
        """
        if self._total_rows == 0:
            return None

        if self._cursor >= self._total_rows:
            logger.info("GaiaAdapter — dataset replay complete")
            return None

        cpu_val, cpu_lbl = self._get_metric_value("cpu_percent", self._cursor)
        mem_val, mem_lbl = self._get_metric_value("mem_percent", self._cursor)
        disk_val, disk_lbl = self._get_metric_value("disk_io_mbps", self._cursor)
        net_val, net_lbl = self._get_metric_value("net_mbps", self._cursor)

        # Aggregate label — anomaly if any stream is anomalous
        label = 1 if any([cpu_lbl, mem_lbl, disk_lbl, net_lbl]) else 0

        # Determine scenario from GAIA ground truth
        scenario = "gaia_anomaly" if label == 1 else ""

        # Timestamps — use cpu metric timestamps if available
        cpu_df = self._metric_dfs.get("cpu_percent")
        if cpu_df is not None and self._cursor < len(cpu_df):
            ts = str(cpu_df.iloc[self._cursor]["timestamp"])
        else:
            ts = datetime.datetime.now(datetime.timezone.utc).isoformat()

        log_score, raw_log = self._compute_log_anomaly_score(ts)

        event = MetricEvent(
            timestamp=ts,
            cpu_percent=cpu_val,
            mem_percent=mem_val,
            disk_io_mbps=disk_val,
            net_mbps=net_val,
            label=label,
            log_anomaly_score=log_score,
            scenario_name=scenario,
            source_dataset="gaia",
            raw_log_text=raw_log,
        )

        errors = event.validate()
        if errors:
            logger.warning(f"GaiaAdapter validation errors: {errors}")

        self._window_buffer.append(event)
        self._cursor += 1

        if len(self._window_buffer) < self.window_size:
            return None

        has_logs = any(e.log_anomaly_score > 0.0 for e in self._window_buffer)

        return MetricWindow(
            events=list(self._window_buffer),
            window_size=self.window_size,
            source_dataset="gaia",
            has_log_signal=has_logs,
        )

    def is_exhausted(self) -> bool:
        return self._cursor >= self._total_rows

    @property
    def progress(self) -> float:
        """Replay progress 0.0 → 1.0"""
        if self._total_rows == 0:
            return 0.0
        return self._cursor / self._total_rows
