"""Opt-in stage instrumentation for interactive performance dogfooding.

Set ``MANIML_PERF_PATH`` to a JSON destination to enable recording.  The
normal viewer pays only the cost of entering a no-op context manager; it does
not retain samples, inspect memory, or write files unless explicitly enabled.

The recorder is intentionally process-local.  Browser presentation timestamps
use a different clock and belong in the browser harness rather than being
silently mixed with Python's monotonic clock here.
"""
from __future__ import annotations

import atexit
from collections import defaultdict, deque
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import resource
import subprocess
import threading
import time


PERF_PATH_ENV = "MANIML_PERF_PATH"
SAMPLE_LIMIT = 20_000
PROCESS_SAMPLE_LIMIT = 2_000


class PerformanceRecorder:
    """Bounded timer/counter recorder, enabled only when it has a path."""

    def __init__(self, path: str | os.PathLike | None = None):
        raw_path = str(path) if path else ""
        self.path = Path(raw_path.format(pid=os.getpid())) if raw_path else None
        self.enabled = self.path is not None
        self.started_monotonic = time.monotonic()
        self.started_cpu = time.process_time()
        self.started_wall = datetime.now(timezone.utc).isoformat()
        self._lock = threading.RLock()
        self._durations: dict[str, deque[float]] = defaultdict(
            lambda: deque(maxlen=SAMPLE_LIMIT))
        self._duration_counts: dict[str, int] = defaultdict(int)
        self._duration_totals: dict[str, float] = defaultdict(float)
        self._duration_max: dict[str, float] = defaultdict(float)
        self._counters: dict[str, float] = defaultdict(float)
        self._gauges: dict[str, object] = {}
        self._metadata: dict[str, object] = {}
        self._process_samples: deque[dict] = deque(
            maxlen=PROCESS_SAMPLE_LIMIT)

    @classmethod
    def from_environment(cls) -> PerformanceRecorder:
        return cls(os.environ.get(PERF_PATH_ENV))

    @contextmanager
    def stage(self, name: str):
        if not self.enabled:
            yield
            return
        started = time.monotonic()
        try:
            yield
        finally:
            self.observe_ms(name, (time.monotonic() - started) * 1000)

    def observe_ms(self, name: str, duration_ms: float) -> None:
        if not self.enabled:
            return
        duration_ms = float(duration_ms)
        with self._lock:
            self._durations[name].append(duration_ms)
            self._duration_counts[name] += 1
            self._duration_totals[name] += duration_ms
            self._duration_max[name] = max(
                self._duration_max[name], duration_ms)

    def increment(self, name: str, amount: float = 1) -> None:
        if not self.enabled:
            return
        with self._lock:
            self._counters[name] += amount

    def gauge(self, name: str, value) -> None:
        if not self.enabled:
            return
        if hasattr(value, "item"):
            value = value.item()
        with self._lock:
            self._gauges[name] = value

    def metadata(self, **values) -> None:
        if not self.enabled:
            return
        with self._lock:
            self._metadata.update(values)

    def sample_process(self, label: str, **values) -> None:
        """Record current/peak RSS outside measured stage durations."""
        if not self.enabled:
            return
        sample = {
            "label": label,
            "elapsed_ms": (time.monotonic() - self.started_monotonic) * 1000,
            "rss_bytes": _current_rss_bytes(),
            "peak_rss_bytes": _peak_rss_bytes(),
            **values,
        }
        with self._lock:
            self._process_samples.append(sample)

    def snapshot(self) -> dict:
        with self._lock:
            stages = {
                name: _duration_summary(
                    self._durations[name],
                    self._duration_counts[name],
                    self._duration_totals[name],
                    self._duration_max[name],
                )
                for name in sorted(self._duration_counts)
            }
            return {
                "format": 1,
                "process": {
                    "pid": os.getpid(),
                    "python": platform.python_version(),
                    "platform": platform.platform(),
                    "started": self.started_wall,
                    "elapsed_ms": (
                        time.monotonic() - self.started_monotonic) * 1000,
                    "cpu_ms": (
                        time.process_time() - self.started_cpu) * 1000,
                    "peak_rss_bytes": _peak_rss_bytes(),
                },
                "metadata": dict(self._metadata),
                "stages": stages,
                "counters": dict(sorted(self._counters.items())),
                "gauges": dict(sorted(self._gauges.items())),
                "process_samples": list(self._process_samples),
            }

    def flush(self) -> None:
        if not self.enabled or self.path is None:
            return
        payload = self.snapshot()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(
            f".{self.path.name}.{os.getpid()}.tmp")
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True))
        os.replace(temporary, self.path)


def _duration_summary(samples, count: int, total: float, maximum: float) -> dict:
    ordered = sorted(samples)

    def percentile(fraction: float) -> float:
        if not ordered:
            return 0.0
        return ordered[round((len(ordered) - 1) * fraction)]

    return {
        "count": count,
        "sample_count": len(ordered),
        "total_ms": total,
        "mean_ms": total / count if count else 0.0,
        "p50_ms": percentile(0.50),
        "p95_ms": percentile(0.95),
        "max_ms": maximum,
    }


def _peak_rss_bytes() -> int:
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # Darwin reports bytes; Linux and the BSDs exposed by Python report KiB.
    return int(rss if platform.system() == "Darwin" else rss * 1024)


def _current_rss_bytes() -> int | None:
    if platform.system() == "Linux":
        try:
            pages = int(Path("/proc/self/statm").read_text().split()[1])
            return pages * os.sysconf("SC_PAGE_SIZE")
        except (OSError, ValueError, IndexError):
            return None
    if platform.system() == "Darwin":
        try:
            output = subprocess.check_output(
                ["ps", "-o", "rss=", "-p", str(os.getpid())],
                text=True,
                stderr=subprocess.DEVNULL,
            )
            return int(output.strip()) * 1024
        except (OSError, ValueError, subprocess.SubprocessError):
            return None
    return None


performance = PerformanceRecorder.from_environment()
if performance.enabled:
    atexit.register(performance.flush)
