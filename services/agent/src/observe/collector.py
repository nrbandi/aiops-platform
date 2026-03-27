"""
Observe Layer — Metric Collector
Section 5.3 of dissertation: psutil-based polling agent.
Samples CPU, memory, disk I/O, network at configured interval.
"""

import time
import psutil
import logging
import datetime
from collections import deque

logger = logging.getLogger(__name__)


class MetricCollector:
    """
    Polls four infrastructure metric streams at a fixed interval.
    Maintains a sliding window of samples for the Analyze layer.
    """

    def __init__(self, config: dict):
        self.poll_interval = config["observe"]["poll_interval_seconds"]
        self.window_size = config["observe"]["window_size"]
        self.window = deque(maxlen=self.window_size)
        self._prev_disk = psutil.disk_io_counters()
        self._prev_net = psutil.net_io_counters()
        self._prev_time = time.time()
        logger.info(
            f"MetricCollector initialised — "
            f"window={self.window_size}, interval={self.poll_interval}s"
        )

    def collect_sample(self) -> dict:
        """Collect one raw sample from psutil."""
        now = time.time()
        elapsed = max(now - self._prev_time, 1e-6)

        curr_disk = psutil.disk_io_counters()
        curr_net = psutil.net_io_counters()

        disk_io_mbps = (
            (
                (curr_disk.read_bytes + curr_disk.write_bytes)
                - (self._prev_disk.read_bytes + self._prev_disk.write_bytes)
            )
            / elapsed
            / 1e6
        )

        net_mbps = (
            (
                (curr_net.bytes_sent + curr_net.bytes_recv)
                - (self._prev_net.bytes_sent + self._prev_net.bytes_recv)
            )
            / elapsed
            / 1e6
        )

        self._prev_disk = curr_disk
        self._prev_net = curr_net
        self._prev_time = now

        sample = {
            "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
            "cpu_percent": psutil.cpu_percent(interval=None),
            "mem_percent": psutil.virtual_memory().percent,
            "disk_io_mbps": round(max(disk_io_mbps, 0.0), 4),
            "net_mbps": round(max(net_mbps, 0.0), 4),
        }
        return sample

    def get_window(self) -> list:
        return list(self.window)

    def is_window_full(self) -> bool:
        return len(self.window) == self.window_size

    def run_once(self) -> list | None:
        """Collect one sample, add to window. Returns window if full."""
        sample = self.collect_sample()
        self.window.append(sample)
        logger.debug(
            f"Sample: cpu={sample['cpu_percent']}% "
            f"mem={sample['mem_percent']}% "
            f"disk={sample['disk_io_mbps']}MB/s "
            f"net={sample['net_mbps']}MB/s"
        )
        if self.is_window_full():
            return self.get_window()
        return None
