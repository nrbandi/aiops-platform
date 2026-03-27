"""
GAIA Dataset Adapter
====================
Reads the CloudWise GAIA Companion Data dataset (Apache 2.0)
and produces MetricEvent objects for the agent pipeline.

Dataset: github.com/CloudWise-OpenSource/GAIA-DataSet
Citation: CloudWise Open Source, GAIA: Generic AIOps Atlas, 2021.

Metric CSV format (metric_detection subfolder):
    timestamp (13-digit epoch ms), value (float), label (0/1)

Log CSV format (log/log semantics anomaly detection/error.csv):
    file_id, line_id, timestamp, host, source, level,
    exception_type, description, raw_data

Mapping strategy (documented design decision):
    Four metric files are selected from metric_detection/linear_data/
    and assigned to the four canonical streams by index:
        index 0 → cpu_percent
        index 1 → mem_percent
        index 2 → disk_io_mbps
        index 3 → net_mbps
    This assignment is arbitrary but reproducible and documented.
    All files are rescaled to their respective realistic ranges.

Log anomaly score:
    Derived from error.csv — fraction of ERROR log entries
    within a ±30s window of each metric timestamp.
    Falls back to 0.0 when no log entries are in range.
"""

import os
import logging
import datetime
import pandas as pd
import numpy as np
from collections import deque
from src.observe.schema import MetricEvent, MetricWindow

logger = logging.getLogger(__name__)

# Canonical metric stream assignments (index → stream name)
METRIC_STREAM_MAP = {
    0: "cpu_percent",
    1: "mem_percent",
    2: "disk_io_mbps",
    3: "net_mbps",
}

# Realistic ranges for rescaling GAIA normalised values
METRIC_RANGES = {
    "cpu_percent": (0.0, 100.0),
    "mem_percent": (0.0, 100.0),
    "disk_io_mbps": (0.0, 500.0),
    "net_mbps": (0.0, 1000.0),
}

# Subfolder to use for metric files
METRIC_SUBFOLDER = "low_signal-to-noise_ratio_data"


class GaiaAdapter:
    """
    Replays the GAIA Companion Data dataset as a stream of
    MetricEvent objects. Four metric KPI files are loaded and
    replayed in lock-step, producing one MetricEvent per row.
    """

    def __init__(self, config: dict):
        self.window_size = config["observe"]["window_size"]
        self.gaia_data_path = config.get("data", {}).get("gaia_path", "data/gaia")
        self.replay_speed = config.get("data", {}).get("replay_speed", 1.0)

        self.start_offset = config.get("data", {}).get("start_offset", 0)
        self._metric_dfs = {}  # stream_name -> DataFrame
        self._log_df = None
        self._cursor = self.start_offset
        self._total_rows = 0
        self._window_buffer = deque(maxlen=self.window_size)

        self._load_metrics()
        self._load_logs()

        logger.info(
            f"GaiaAdapter initialised — "
            f"rows={self._total_rows}, "
            f"streams={len(self._metric_dfs)}, "
            f"has_logs={self._log_df is not None}, "
            f"replay_speed={self.replay_speed}x"
        )

    # ── Loading ───────────────────────────────────────────────────

    def _metric_path(self) -> str:
        return os.path.join(
            self.gaia_data_path,
            "raw",
            "Companion_Data",
            "metric_detection",
            METRIC_SUBFOLDER,
        )

    def _log_path(self) -> str:
        return os.path.join(
            self.gaia_data_path,
            "raw",
            "Companion_Data",
            "log",
            "log semantics anomaly detection",
            "error.csv",
        )

    def _load_metrics(self) -> None:
        """
        Load four metric CSV files and assign them to canonical
        streams. Files are sorted alphabetically for reproducibility.
        """
        path = self._metric_path()
        if not os.path.exists(path):
            logger.warning(f"GAIA metric path not found: {path}")
            return

        csv_files = sorted([f for f in os.listdir(path) if f.endswith(".csv")])

        if len(csv_files) < 4:
            logger.warning(f"Need at least 4 metric files, found {len(csv_files)}")
            return

        for idx, stream_name in METRIC_STREAM_MAP.items():
            fpath = os.path.join(path, csv_files[idx])
            try:
                df = pd.read_csv(fpath)

                # Rename to standard columns
                df.columns = [c.strip() for c in df.columns]
                df = df.rename(
                    columns={
                        df.columns[0]: "timestamp",
                        df.columns[1]: "value",
                        df.columns[2]: "label",
                    }
                )

                # Convert 13-digit ms epoch → ISO string
                df["timestamp"] = pd.to_datetime(
                    df["timestamp"].astype(np.int64), unit="ms", utc=True
                ).dt.strftime("%Y-%m-%dT%H:%M:%SZ")

                # Rescale value to realistic range
                # GAIA values may already be in 0-100 range for percentage metrics
                # Only rescale if the value range suggests raw counts or bytes
                lo, hi = METRIC_RANGES[stream_name]
                v = df["value"].astype(float)
                v_min, v_max = v.min(), v.max()
                natural_range = v_max - v_min

                if natural_range < 1e-6:
                    df["value"] = lo
                elif v_max <= 100.0 and stream_name in ("cpu_percent", "mem_percent"):
                    # Already in percentage range — keep as-is, just clip
                    df["value"] = v.clip(0.0, 100.0)
                else:
                    # Rescale raw values to realistic range
                    df["value"] = lo + (v - v_min) / natural_range * (hi - lo)

                # Ensure label is integer
                df["label"] = df["label"].fillna(0).astype(int)

                self._metric_dfs[stream_name] = df.reset_index(drop=True)
                logger.info(
                    f"GAIA metric loaded: {csv_files[idx]} "
                    f"→ {stream_name} ({len(df)} rows)"
                )

            except Exception as e:
                logger.warning(f"Failed to load {csv_files[idx]}: {e}")

        if self._metric_dfs:
            self._total_rows = min(len(df) for df in self._metric_dfs.values())

    def _load_logs(self) -> None:
        """Load error.csv for log anomaly scoring."""
        path = self._log_path()
        if not os.path.exists(path):
            logger.info(f"GAIA log file not found: {path}")
            return

        try:
            # error.csv is large — load only needed columns
            df = pd.read_csv(
                path,
                usecols=["timestamp", "level", "exception_type"],
                on_bad_lines="skip",
            )
            df["timestamp_ms"] = pd.to_numeric(df["timestamp"], errors="coerce")
            df = df.dropna(subset=["timestamp_ms"])
            df["timestamp_ms"] = df["timestamp_ms"].astype(np.int64)
            self._log_df = df.reset_index(drop=True)
            logger.info(f"GAIA error log loaded: {len(self._log_df)} entries")
        except Exception as e:
            logger.warning(f"GAIA log loading failed: {e}")
            self._log_df = None

    # ── Scoring ───────────────────────────────────────────────────

    def _log_anomaly_score(self, timestamp_ms: int) -> tuple[float, str]:
        """
        Compute log anomaly score for a ±30s window around
        the current metric timestamp.
        Returns (score, raw_text).
        """
        if self._log_df is None:
            return 0.0, ""

        window_ms = 30_000  # ±30 seconds in milliseconds
        lo = timestamp_ms - window_ms
        hi = timestamp_ms + window_ms

        nearby = self._log_df[
            (self._log_df["timestamp_ms"] >= lo) & (self._log_df["timestamp_ms"] <= hi)
        ]

        if nearby.empty:
            return 0.0, ""

        # All entries in error.csv are ERROR level — score = density
        # normalised: cap at 1.0 for 10+ errors in window
        score = min(len(nearby) / 10.0, 1.0)
        raw_text = " | ".join(nearby["exception_type"].fillna("").head(3).tolist())
        return round(score, 4), raw_text

    # ── Streaming ─────────────────────────────────────────────────

    def next_window(self) -> MetricWindow | None:
        """Advance one replay step. Returns MetricWindow when full."""
        if not self._metric_dfs or self._cursor >= self._total_rows:
            return None

        # Get current row from each stream
        rows = {
            stream: df.iloc[self._cursor] for stream, df in self._metric_dfs.items()
        }

        # Use cpu_percent timestamp as the canonical timestamp
        ts = str(rows["cpu_percent"]["timestamp"])

        # Aggregate label — anomaly if ANY stream is labelled 1
        label = int(any(int(row["label"]) == 1 for row in rows.values()))

        # Get metric timestamp in ms for log scoring
        cpu_df = self._metric_dfs["cpu_percent"]
        # Reconstruct ms from ISO string for log alignment
        try:
            ts_ms = int(pd.Timestamp(ts).timestamp() * 1000)
        except Exception:
            ts_ms = 0

        log_score, raw_log = self._log_anomaly_score(ts_ms)

        event = MetricEvent(
            timestamp=ts,
            cpu_percent=float(rows["cpu_percent"]["value"]),
            mem_percent=float(rows["mem_percent"]["value"]),
            disk_io_mbps=float(rows["disk_io_mbps"]["value"]),
            net_mbps=float(rows["net_mbps"]["value"]),
            label=label,
            log_anomaly_score=log_score,
            scenario_name="gaia_anomaly" if label == 1 else "",
            source_dataset="gaia",
            raw_log_text=raw_log,
        )

        errors = event.validate()
        if errors:
            logger.debug(f"Validation warnings at row {self._cursor}: {errors}")

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
        if self._total_rows == 0:
            return 0.0
        return self._cursor / self._total_rows
