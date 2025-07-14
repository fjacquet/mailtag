"""
Performance metrics collection for the Mailtag application.

This module provides utilities for collecting, tracking, and reporting performance
metrics such as timing, success/failure rates, and memory usage.
"""

import functools
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
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
class MetricsRegistry:
    """Central registry for all metrics."""

    operation_metrics: dict[str, OperationMetrics] = field(default_factory=dict)
    memory_metrics: MemoryMetrics | None = None
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
