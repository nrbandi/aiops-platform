"""
Synthetic Adapter
=================
Produces MetricEvent objects from the deterministic named-failure
scenario generator. Backward-compatible replacement for the
_synthetic_window() function in the viva demo agent.py.

Six named scenarios (Section 6.2 semi-synthetic methodology):
  1. cpu_spike          — sudden step-function CPU saturation
  2. memory_leak        — slow linear memory ramp
  3. disk_saturation    — sustained disk I/O spike
  4. network_flood      — network throughput spike
  5. cascading_failure  — multi-metric degradation spreading
  6. antivirus_scan     — CPU + disk combined (PB014 pattern)
"""

import random
import datetime
import logging
from collections import deque
from src.observe.schema import MetricEvent, MetricWindow

logger = logging.getLogger(__name__)


SCENARIOS = [
    "cpu_spike",
    "memory_leak",
    "disk_saturation",
    "network_flood",
    "cascading_failure",
    "antivirus_scan",
]


class SyntheticAdapter:
    """
    Generates synthetic MetricEvent streams with named anomaly
    injection at configurable intervals.
    """

    def __init__(self, config: dict):
        self.window_size = config["observe"]["window_size"]
        self.demo_mode = config["act"]["demo_mode"]
        self._cycle = 0
        self._window_buffer = deque(maxlen=self.window_size)
        logger.info(
            "SyntheticAdapter initialised — "
            f"window_size={self.window_size}, "
            f"scenarios={len(SCENARIOS)}"
        )

    def _is_anomaly_cycle(self) -> bool:
        """Inject anomaly every 5th cycle after warmup."""
        return (self._cycle % 5 == 0) and (self._cycle >= 10)

    def _current_scenario(self) -> str:
        """Rotate through scenarios deterministically."""
        idx = (self._cycle // 5) % len(SCENARIOS)
        return SCENARIOS[idx]

    def _generate_sample(
        self,
        cycle: int,
        anomaly: bool,
        scenario: str,
        sample_idx: int,
    ) -> MetricEvent:
        """Generate one MetricEvent sample."""
        rng = random.Random(cycle * 42 + sample_idx)
        ts = datetime.datetime.now(datetime.timezone.utc).isoformat()

        if not anomaly:
            return MetricEvent(
                timestamp=ts,
                cpu_percent=rng.uniform(15.0, 40.0),
                mem_percent=rng.uniform(30.0, 50.0),
                disk_io_mbps=rng.uniform(5.0, 30.0),
                net_mbps=rng.uniform(10.0, 80.0),
                label=0,
                source_dataset="synthetic",
            )

        # --- Named anomaly patterns ---
        if scenario == "cpu_spike":
            return MetricEvent(
                timestamp=ts,
                cpu_percent=rng.uniform(88.0, 98.0),
                mem_percent=rng.uniform(35.0, 55.0),
                disk_io_mbps=rng.uniform(5.0, 25.0),
                net_mbps=rng.uniform(10.0, 60.0),
                label=1,
                scenario_name="cpu_spike",
                source_dataset="synthetic",
            )

        elif scenario == "memory_leak":
            # Gradual ramp — sample_idx drives progression
            leak = min(50.0 + sample_idx * 4.0, 95.0)
            return MetricEvent(
                timestamp=ts,
                cpu_percent=rng.uniform(20.0, 45.0),
                mem_percent=rng.uniform(leak, min(leak + 5.0, 97.0)),
                disk_io_mbps=rng.uniform(5.0, 20.0),
                net_mbps=rng.uniform(10.0, 50.0),
                label=1,
                scenario_name="memory_leak",
                source_dataset="synthetic",
            )

        elif scenario == "disk_saturation":
            return MetricEvent(
                timestamp=ts,
                cpu_percent=rng.uniform(25.0, 50.0),
                mem_percent=rng.uniform(40.0, 65.0),
                disk_io_mbps=rng.uniform(220.0, 400.0),
                net_mbps=rng.uniform(10.0, 60.0),
                label=1,
                scenario_name="disk_saturation",
                source_dataset="synthetic",
            )

        elif scenario == "network_flood":
            return MetricEvent(
                timestamp=ts,
                cpu_percent=rng.uniform(30.0, 60.0),
                mem_percent=rng.uniform(35.0, 55.0),
                disk_io_mbps=rng.uniform(5.0, 25.0),
                net_mbps=rng.uniform(850.0, 1200.0),
                label=1,
                scenario_name="network_flood",
                source_dataset="synthetic",
            )

        elif scenario == "cascading_failure":
            # Starts CPU, spreads to memory and disk
            spread = sample_idx / self.window_size
            return MetricEvent(
                timestamp=ts,
                cpu_percent=rng.uniform(80.0, 97.0),
                mem_percent=rng.uniform(50.0 + spread * 40, 95.0),
                disk_io_mbps=rng.uniform(50.0 + spread * 150, 300.0),
                net_mbps=rng.uniform(10.0, 80.0),
                label=1,
                scenario_name="cascading_failure",
                source_dataset="synthetic",
            )

        elif scenario == "antivirus_scan":
            # PB014 pattern — CPU + disk combined
            return MetricEvent(
                timestamp=ts,
                cpu_percent=rng.uniform(68.0, 82.0),
                mem_percent=rng.uniform(35.0, 55.0),
                disk_io_mbps=rng.uniform(130.0, 220.0),
                net_mbps=rng.uniform(10.0, 50.0),
                label=1,
                scenario_name="antivirus_scan",
                source_dataset="synthetic",
            )

        # Fallback — should never reach here
        return self._generate_sample(cycle, False, "", sample_idx)

    def next_window(self) -> MetricWindow | None:
        """
        Advance one cycle. Returns a MetricWindow when the
        sliding window is full, else None.
        """
        self._cycle += 1
        anomaly = self._is_anomaly_cycle()
        scenario = self._current_scenario() if anomaly else ""

        for i in range(self.window_size):
            event = self._generate_sample(self._cycle, anomaly, scenario, i)
            self._window_buffer.append(event)

        if len(self._window_buffer) < self.window_size:
            return None

        if anomaly:
            logger.info(
                f"SyntheticAdapter — cycle={self._cycle} "
                f"ANOMALY injected: {scenario}"
            )

        return MetricWindow(
            events=list(self._window_buffer),
            window_size=self.window_size,
            source_dataset="synthetic",
            has_log_signal=False,
        )
