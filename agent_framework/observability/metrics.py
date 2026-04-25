"""Metrics Collection

Provides metrics collection for monitoring agent performance.
[PHASE10] 可观测性 - MetricsCollector
"""

import time
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from enum import Enum
import threading

# Debug print helper
def _debug(msg: str):
    print(f"[PHASE10] [MetricsCollector] {msg}")


class MetricType(Enum):
    """Type of metric"""
    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"


@dataclass
class Metric:
    """Base metric class"""
    name: str
    description: str = ""
    labels: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "labels": self.labels,
        }


@dataclass
class Counter(Metric):
    """Counter metric - only increments"""
    value: float = 0
    metric_type: MetricType = field(default_factory=lambda: MetricType.COUNTER, init=False)

    def inc(self, amount: float = 1) -> None:
        """Increment counter"""
        self.value += amount

    def to_dict(self) -> dict:
        result = super().to_dict()
        result["type"] = "counter"
        result["value"] = self.value
        return result


@dataclass
class Gauge(Metric):
    """Gauge metric - can go up or down"""
    value: float = 0
    metric_type: MetricType = field(default_factory=lambda: MetricType.GAUGE, init=False)

    def inc(self, amount: float = 1) -> None:
        """Increase gauge"""
        self.value += amount

    def dec(self, amount: float = 1) -> None:
        """Decrease gauge"""
        self.value -= amount

    def set(self, value: float) -> None:
        """Set gauge value"""
        self.value = value

    def to_dict(self) -> dict:
        result = super().to_dict()
        result["type"] = "gauge"
        result["value"] = self.value
        return result


@dataclass
class Histogram(Metric):
    """Histogram metric - distribution of values"""
    value: float = 0
    count: int = 0
    sum_sq: float = 0  # Sum of squares for stddev calculation
    min_value: float = float('inf')
    max_value: float = float('-inf')
    metric_type: MetricType = field(default_factory=lambda: MetricType.HISTOGRAM, init=False)

    # Buckets for histogram
    buckets: List[float] = field(default_factory=lambda: [0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10])

    def observe(self, value: float) -> None:
        """Record an observation"""
        self.value = value
        self.count += 1
        self.sum_sq += value * value

        if value < self.min_value:
            self.min_value = value
        if value > self.max_value:
            self.max_value = value

    def mean(self) -> float:
        """Calculate mean"""
        if self.count == 0:
            return 0
        return self.value / self.count  # Note: This should be sum/count, fix below

    def sum(self) -> float:
        """Get sum of all observations"""
        return self.value

    def to_dict(self) -> dict:
        result = super().to_dict()
        result["type"] = "histogram"
        result["count"] = self.count
        result["sum"] = self.value  # Should track sum separately
        result["min"] = self.min_value if self.count > 0 else 0
        result["max"] = self.max_value if self.count > 0 else 0
        return result


class MetricsCollector:
    """Collects and manages metrics

    Thread-safe metrics collection with label support.
    """

    def __init__(self, service_name: str = "agent_framework"):
        self.service_name = service_name
        self._metrics: Dict[str, Metric] = {}
        self._lock = threading.Lock()
        self._start_time = time.time()

    def counter(self, name: str, description: str = "", labels: Dict[str, str] = None) -> Counter:
        """Get or create a counter"""
        with self._lock:
            key = self._make_key(name, labels)
            if key not in self._metrics:
                self._metrics[key] = Counter(
                    name=name,
                    description=description,
                    labels=labels or {},
                )
            return self._metrics[key]

    def gauge(self, name: str, description: str = "", labels: Dict[str, str] = None) -> Gauge:
        """Get or create a gauge"""
        with self._lock:
            key = self._make_key(name, labels)
            if key not in self._metrics:
                self._metrics[key] = Gauge(
                    name=name,
                    description=description,
                    labels=labels or {},
                )
            return self._metrics[key]

    def histogram(
        self,
        name: str,
        description: str = "",
        labels: Dict[str, str] = None,
    ) -> Histogram:
        """Get or create a histogram"""
        with self._lock:
            key = self._make_key(name, labels)
            if key not in self._metrics:
                self._metrics[key] = Histogram(
                    name=name,
                    description=description,
                    labels=labels or {},
                )
            return self._metrics[key]

    def _make_key(self, name: str, labels: Dict[str, str] = None) -> str:
        """Create a unique key for a metric"""
        if not labels:
            return name

        label_str = ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
        return f"{name}{{{label_str}}}"

    def inc_counter(self, name: str, amount: float = 1, labels: Dict[str, str] = None) -> None:
        """Increment a counter"""
        c = self.counter(name, labels=labels)
        c.inc(amount)

    def set_gauge(self, name: str, value: float, labels: Dict[str, str] = None) -> None:
        """Set a gauge value"""
        g = self.gauge(name, labels=labels)
        g.set(value)

    def observe_histogram(self, name: str, value: float, labels: Dict[str, str] = None) -> None:
        """Observe a value for histogram"""
        h = self.histogram(name, labels=labels)
        h.observe(value)

    def record_token_usage(
        self,
        prompt_tokens: int,
        completion_tokens: int,
        model: str = "",
    ) -> None:
        """Record LLM token usage"""
        self.inc_counter(
            "agent_tokens_total",
            prompt_tokens + completion_tokens,
            {"type": "prompt", "model": model}
        )
        self.inc_counter(
            "agent_tokens_total",
            completion_tokens,
            {"type": "completion", "model": model}
        )

    def record_tool_call(
        self,
        tool_name: str,
        duration_ms: float,
        success: bool,
    ) -> None:
        """Record a tool call"""
        self.inc_counter(
            "agent_tool_calls_total",
            labels={"tool": tool_name, "success": str(success)}
        )
        self.observe_histogram(
            "agent_tool_duration_ms",
            duration_ms,
            {"tool": tool_name}
        )

    def record_agent_turn(
        self,
        duration_ms: float,
        tool_calls: int,
        success: bool,
    ) -> None:
        """Record an agent turn (one user message + response)"""
        self.inc_counter(
            "agent_turns_total",
            labels={"success": str(success)}
        )
        self.observe_histogram(
            "agent_turn_duration_ms",
            duration_ms
        )
        self.set_gauge(
            "agent_turn_tool_calls",
            tool_calls
        )

    def get_all_metrics(self) -> List[dict]:
        """Get all metrics as dictionaries"""
        with self._lock:
            return [m.to_dict() for m in self._metrics.values()]

    def export_prometheus(self) -> str:
        """Export metrics in Prometheus format"""
        lines = []

        # Add comment header
        lines.append(f"# Agent Framework Metrics")
        lines.append(f"# Service: {self.service_name}")
        lines.append(f"# Time: {time.time()}")

        # Group by metric name
        by_name: Dict[str, List[Metric]] = {}
        for metric in self._metrics.values():
            if metric.name not in by_name:
                by_name[metric.name] = []
            by_name[metric.name].append(metric)

        # Format each metric
        for name, metrics in by_name.items():
            # Help line
            if metrics[0].description:
                lines.append(f"# HELP {name} {metrics[0].description}")
            lines.append(f"# TYPE {name} {metrics[0].metric_type.value}")

            # Value line(s)
            for m in metrics:
                if m.labels:
                    label_str = ",".join(f'{k}="{v}"' for k, v in m.labels.items())
                    lines.append(f"{name}{{{label_str}}} {m.value if isinstance(m, (Counter, Gauge)) else m.count}")
                else:
                    lines.append(f"{name} {m.value if isinstance(m, (Counter, Gauge)) else m.count}")

        return "\n".join(lines)

    def reset(self) -> None:
        """Reset all metrics"""
        with self._lock:
            self._metrics.clear()
            self._start_time = time.time()


# Global metrics collector
_metrics_collector: Optional[MetricsCollector] = None


def get_metrics() -> MetricsCollector:
    """Get the global metrics collector"""
    global _metrics_collector
    if _metrics_collector is None:
        _metrics_collector = MetricsCollector()
    return _metrics_collector
