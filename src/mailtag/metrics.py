"""
Performance metrics collection for the Mailtag application.

This module provides utilities for collecting, tracking, and reporting performance
metrics such as timing, success/failure rates, memory usage, and classification quality.
"""

import functools
import json
import statistics
import time
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TypeVar, cast

import psutil
from loguru import logger

T = TypeVar("T")


@dataclass
class OperationMetrics:
    """Metrics for a specific operation type."""

    name: str
    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    total_time_ms: float = 0
    min_time_ms: float = float("inf")
    max_time_ms: float = 0
    avg_time_ms: float = 0
    last_call_time: datetime | None = None

    def record_success(self, duration_ms: float) -> None:
        """Record a successful operation."""
        self.total_calls += 1
        self.successful_calls += 1
        self._update_timing(duration_ms)

    def record_failure(self, duration_ms: float) -> None:
        """Record a failed operation."""
        self.total_calls += 1
        self.failed_calls += 1
        self._update_timing(duration_ms)

    def _update_timing(self, duration_ms: float) -> None:
        """Update timing statistics."""
        self.total_time_ms += duration_ms
        self.min_time_ms = min(self.min_time_ms, duration_ms)
        self.max_time_ms = max(self.max_time_ms, duration_ms)
        self.avg_time_ms = self.total_time_ms / self.total_calls
        self.last_call_time = datetime.now()

    @property
    def success_rate(self) -> float:
        """Calculate the success rate as a percentage."""
        if self.total_calls == 0:
            return 0
        return (self.successful_calls / self.total_calls) * 100

    def __str__(self) -> str:
        return (
            f"{self.name}: {self.total_calls} calls "
            f"({self.successful_calls} success, {self.failed_calls} failed), "
            f"avg: {self.avg_time_ms:.2f}ms, min: {self.min_time_ms:.2f}ms, "
            f"max: {self.max_time_ms:.2f}ms, success rate: {self.success_rate:.1f}%"
        )


@dataclass
class MemoryMetrics:
    """Memory usage metrics."""

    initial_rss_mb: float
    peak_rss_mb: float = 0
    current_rss_mb: float = 0
    last_updated: datetime | None = None

    def update(self) -> None:
        """Update memory metrics with current process memory usage."""
        process = psutil.Process()
        current_rss = process.memory_info().rss / (1024 * 1024)  # Convert to MB
        self.current_rss_mb = current_rss
        self.peak_rss_mb = max(self.peak_rss_mb, current_rss)
        self.last_updated = datetime.now()

    def __str__(self) -> str:
        return (
            f"Memory usage: current: {self.current_rss_mb:.2f}MB, "
            f"peak: {self.peak_rss_mb:.2f}MB, "
            f"increase: {(self.peak_rss_mb - self.initial_rss_mb):.2f}MB"
        )


@dataclass
class ClassificationMetrics:
    """Metrics specific to email classification quality."""

    signal_hits: Counter = field(default_factory=Counter)
    category_distribution: Counter = field(default_factory=Counter)
    confidence_scores: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))
    errors: Counter = field(default_factory=Counter)
    processing_times: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))

    def record_classification(
        self,
        email_id: str,
        signal: str,
        category: str,
        confidence: float | None = None,
        processing_time_ms: float = 0.0,
    ) -> None:
        """Record a successful classification.

        Args:
            email_id: Unique email identifier
            signal: Classification signal used (validated_db, server_labels, historical, domain, ai)
            category: Category assigned to email
            confidence: Confidence score (0.0-1.0), if available
            processing_time_ms: Time taken to classify in milliseconds
        """
        self.signal_hits[signal] += 1
        self.category_distribution[category] += 1

        if confidence is not None:
            self.confidence_scores[signal].append(confidence)

        if processing_time_ms > 0:
            self.processing_times[signal].append(processing_time_ms)

    def record_error(self, error_type: str, context: str = "") -> None:
        """Record a classification error.

        Args:
            error_type: Type of error encountered
            context: Additional context (e.g., sender address)
        """
        error_key = f"{error_type}:{context}" if context else error_type
        self.errors[error_key] += 1

    def get_signal_hit_rates(self) -> dict[str, float]:
        """Calculate percentage of emails classified by each signal.

        Returns:
            Dictionary mapping signal name to percentage
        """
        total = sum(self.signal_hits.values())
        if total == 0:
            return {}
        return {signal: (count / total) * 100 for signal, count in self.signal_hits.items()}

    def get_summary(self) -> dict:
        """Get comprehensive metrics summary.

        Returns:
            Dictionary with all classification metrics
        """
        total_classified = sum(self.signal_hits.values())

        return {
            "total_classified": total_classified,
            "signal_hit_rates": self.get_signal_hit_rates(),
            "signal_counts": dict(self.signal_hits),
            "top_categories": dict(self.category_distribution.most_common(10)),
            "avg_confidence_by_signal": {
                signal: statistics.mean(scores) if scores else 0.0
                for signal, scores in self.confidence_scores.items()
            },
            "min_confidence_by_signal": {
                signal: min(scores) if scores else 0.0 for signal, scores in self.confidence_scores.items()
            },
            "max_confidence_by_signal": {
                signal: max(scores) if scores else 0.0 for signal, scores in self.confidence_scores.items()
            },
            "avg_processing_time_ms": {
                signal: statistics.mean(times) if times else 0.0
                for signal, times in self.processing_times.items()
            },
            "errors": dict(self.errors.most_common()),
            "timestamp": datetime.now().isoformat(),
        }

    def export_to_json(self, filepath: Path) -> None:
        """Export metrics to JSON file.

        Args:
            filepath: Path to output JSON file
        """
        filepath.parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, "w") as f:
            json.dump(self.get_summary(), f, indent=2)
        logger.debug(f"Exported classification metrics to {filepath}")

    def log_summary(self, log_level: str = "INFO") -> None:
        """Log a formatted summary of classification metrics.

        Args:
            log_level: Log level to use for output
        """
        summary = self.get_summary()

        logger.log(log_level, "=" * 80)
        logger.log(log_level, "CLASSIFICATION METRICS SUMMARY")
        logger.log(log_level, "=" * 80)
        logger.log(log_level, f"Total emails classified: {summary['total_classified']}")
        logger.log(log_level, "")

        if summary["signal_hit_rates"]:
            logger.log(log_level, "Signal Hit Rates:")
            for signal, rate in sorted(summary["signal_hit_rates"].items(), key=lambda x: x[1], reverse=True):
                count = summary["signal_counts"].get(signal, 0)
                logger.log(log_level, f"  {signal:20s}: {rate:6.2f}% ({count:4d} emails)")
            logger.log(log_level, "")

        if summary["top_categories"]:
            logger.log(log_level, "Top 10 Categories:")
            for category, count in list(summary["top_categories"].items())[:10]:
                logger.log(log_level, f"  {category:50s}: {count:4d} emails")
            logger.log(log_level, "")

        if summary["avg_confidence_by_signal"]:
            logger.log(log_level, "Average Confidence by Signal:")
            for signal, conf in summary["avg_confidence_by_signal"].items():
                if conf > 0:
                    min_conf = summary["min_confidence_by_signal"].get(signal, 0)
                    max_conf = summary["max_confidence_by_signal"].get(signal, 0)
                    logger.log(
                        log_level,
                        f"  {signal:20s}: avg={conf:.3f}, min={min_conf:.3f}, max={max_conf:.3f}",
                    )
            logger.log(log_level, "")

        if summary["avg_processing_time_ms"]:
            logger.log(log_level, "Average Processing Time by Signal:")
            for signal, time_ms in sorted(
                summary["avg_processing_time_ms"].items(), key=lambda x: x[1], reverse=True
            ):
                if time_ms > 0:
                    logger.log(log_level, f"  {signal:20s}: {time_ms:8.2f} ms")
            logger.log(log_level, "")

        if summary["errors"]:
            logger.log(log_level, "Classification Errors:")
            for error, count in summary["errors"].items():
                logger.log(log_level, f"  {error}: {count}")
            logger.log(log_level, "")

        logger.log(log_level, "=" * 80)

    def reset(self) -> None:
        """Reset all classification metrics."""
        self.signal_hits.clear()
        self.category_distribution.clear()
        self.confidence_scores.clear()
        self.errors.clear()
        self.processing_times.clear()


@dataclass
class MetricsRegistry:
    """Central registry for all metrics."""

    operation_metrics: dict[str, OperationMetrics] = field(default_factory=dict)
    memory_metrics: MemoryMetrics | None = None
    classification_metrics: ClassificationMetrics = field(default_factory=ClassificationMetrics)
    enabled: bool = True
    log_level: str = "DEBUG"

    def __post_init__(self):
        """Initialize memory metrics if not already set."""
        if self.memory_metrics is None and self.enabled:
            process = psutil.Process()
            initial_rss = process.memory_info().rss / (1024 * 1024)  # Convert to MB
            self.memory_metrics = MemoryMetrics(initial_rss_mb=initial_rss)
            self.memory_metrics.update()

    def get_operation_metrics(self, operation_name: str) -> OperationMetrics:
        """Get or create metrics for the specified operation."""
        if operation_name not in self.operation_metrics:
            self.operation_metrics[operation_name] = OperationMetrics(name=operation_name)
        return self.operation_metrics[operation_name]

    def update_memory_metrics(self) -> None:
        """Update memory usage metrics."""
        if self.enabled and self.memory_metrics:
            self.memory_metrics.update()

    def log_metrics(self) -> None:
        """Log all collected metrics."""
        if not self.enabled:
            return

        logger.log(self.log_level, "Performance Metrics Summary:")
        for metrics in self.operation_metrics.values():
            logger.log(self.log_level, f"  {metrics}")

        if self.memory_metrics:
            logger.log(self.log_level, f"  {self.memory_metrics}")

    def reset(self) -> None:
        """Reset all metrics."""
        self.operation_metrics.clear()
        self.classification_metrics.reset()
        if self.enabled:
            process = psutil.Process()
            initial_rss = process.memory_info().rss / (1024 * 1024)
            self.memory_metrics = MemoryMetrics(initial_rss_mb=initial_rss)
            self.memory_metrics.update()


# Global metrics registry
METRICS = MetricsRegistry()


def timed(operation_name: str | None = None):
    """
    Decorator to time function execution and record metrics.

    Args:
        operation_name: Name of the operation for metrics. If None, uses function name.
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> T:
            if not METRICS.enabled:
                return func(*args, **kwargs)

            # Get operation name
            op_name = operation_name or func.__qualname__

            # Update memory metrics before operation
            METRICS.update_memory_metrics()

            # Time the operation
            start_time = time.time()
            try:
                result = func(*args, **kwargs)
                # Record successful operation
                duration_ms = (time.time() - start_time) * 1000
                METRICS.get_operation_metrics(op_name).record_success(duration_ms)
                return result
            except Exception:
                # Record failed operation
                duration_ms = (time.time() - start_time) * 1000
                METRICS.get_operation_metrics(op_name).record_failure(duration_ms)
                raise
            finally:
                # Update memory metrics after operation
                METRICS.update_memory_metrics()

        return cast(Callable[..., T], wrapper)

    return decorator


def configure_metrics(enabled: bool = True, log_level: str = "DEBUG") -> None:
    """
    Configure the metrics collection system.

    Args:
        enabled: Whether metrics collection is enabled
        log_level: Log level for metrics logging
    """
    METRICS.enabled = enabled
    METRICS.log_level = log_level
    if enabled:
        METRICS.__post_init__()  # Ensure memory metrics are initialized


def log_metrics() -> None:
    """Log all collected metrics."""
    METRICS.log_metrics()


def reset_metrics() -> None:
    """Reset all metrics."""
    METRICS.reset()
