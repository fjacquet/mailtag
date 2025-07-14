# IMAP Fast Parse Performance Metrics

This document provides a detailed technical overview of the performance metrics collection system implemented in the Fast Parse feature of the Mailtag project.

## Overview

The performance metrics system is designed to collect, track, and report key performance indicators for IMAP operations. This helps with monitoring, debugging, and optimizing the Fast Parse system by providing insights into:

1. Operation timing (average, min, max)
2. Success/failure rates
3. Memory usage
4. Operation frequency

## Problem Statement

Without metrics collection, it's difficult to:

1. Identify performance bottlenecks
2. Detect abnormal behavior
3. Understand resource usage patterns
4. Make data-driven optimization decisions
5. Monitor system health over time

## Solution: Comprehensive Metrics Collection

The solution is a flexible metrics collection system that:

1. Tracks timing for key operations
2. Records success and failure rates
3. Monitors memory usage
4. Provides periodic logging of metrics
5. Has minimal performance impact

## Implementation

### Configuration

The metrics system is configurable through the `FastParseConfig` class and the `config.toml` file:

```toml
[fast_parse]
# Performance metrics configuration
# Whether to enable metrics collection
metrics_enabled = true
# Log level for metrics reporting (DEBUG, INFO, WARNING, ERROR)
metrics_log_level = "INFO"
# How often to log metrics summary (in minutes)
metrics_log_interval_minutes = 10
```

These configuration options allow fine-tuning of the metrics behavior:

- `metrics_enabled`: Toggle metrics collection on/off
- `metrics_log_level`: Control the verbosity of metrics logging
- `metrics_log_interval_minutes`: Set how frequently metrics summaries are logged

### Metrics Module

The metrics system is implemented in `metrics.py` and provides:

#### 1. Operation Metrics

The `OperationMetrics` class tracks:

- Total calls
- Successful calls
- Failed calls
- Total execution time
- Minimum execution time
- Maximum execution time
- Average execution time
- Last call timestamp
- Success rate

#### 2. Memory Metrics

The `MemoryMetrics` class tracks:

- Initial memory usage (RSS)
- Peak memory usage
- Current memory usage
- Memory usage increase

#### 3. Metrics Registry

The `MetricsRegistry` class provides:

- Central storage for all metrics
- Methods to get or create operation metrics
- Memory metrics updating
- Metrics logging
- Registry reset capability

#### 4. Timing Decorator

The `@timed` decorator makes it easy to add timing metrics to any method:

```python
@timed(operation_name="imap_get_email_headers")
def get_email_headers(self, uids: list[str | int]) -> dict[str, dict[str, str]]:
    # Method implementation
```

The decorator handles:

1. Timing the operation
2. Recording success or failure
3. Updating memory metrics before and after the operation

### Integration with ImapService

The metrics system is integrated with `ImapService` in several ways:

1. **Initialization**: The metrics system is configured during ImapService initialization:

   ```python
   configure_metrics(
       enabled=self.fast_parse_config.metrics_enabled,
       log_level=self.fast_parse_config.metrics_log_level
   )
   ```

2. **Periodic Logging**: A background thread logs metrics at configurable intervals:

   ```python
   def _start_metrics_logging_thread(self):
       # Implementation for periodic logging
   ```

3. **Operation Timing**: Key methods are decorated with `@timed` to collect metrics:
   - `connect`
   - `_batch_fetch`
   - `get_email_headers`
   - `get_full_emails`
   - `batch_move_emails`
   - `select_folder`

## Usage Example

The metrics system works transparently to the caller. For example, when fetching email headers:

```python
with imap_service.connect() as imap:
    headers = imap.get_email_headers(uids)
```

During this operation, the metrics system will:

1. Record the start time
2. Track memory usage before the operation
3. Execute the operation
4. Record the end time and calculate duration
5. Track memory usage after the operation
6. Update success/failure statistics
7. Periodically log metrics summaries

## Example Metrics Output

```
INFO     Performance Metrics Summary:
INFO       imap_connect: 5 calls (5 success, 0 failed), avg: 235.67ms, min: 125.32ms, max: 345.89ms, success rate: 100.0%
INFO       imap_batch_fetch: 12 calls (11 success, 1 failed), avg: 456.78ms, min: 234.56ms, max: 789.01ms, success rate: 91.7%
INFO       imap_get_email_headers: 8 calls (8 success, 0 failed), avg: 123.45ms, min: 98.76ms, max: 234.56ms, success rate: 100.0%
INFO       Memory usage: current: 45.67MB, peak: 67.89MB, increase: 22.22MB
```

## Benefits

1. **Performance Visibility**: Clear insights into operation timing and success rates
2. **Resource Monitoring**: Track memory usage patterns
3. **Early Warning System**: Detect performance degradation early
4. **Optimization Guidance**: Identify bottlenecks for targeted optimization
5. **Operational Insights**: Understand usage patterns and load distribution

## Limitations

1. **Overhead**: Metrics collection adds a small performance overhead
2. **Limited Scope**: Currently only tracks IMAP operations, not database or other operations
3. **In-Memory Storage**: Metrics are not persisted between application restarts

## Future Improvements

1. **Persistent Storage**: Store metrics in a database for historical analysis
2. **Metrics Visualization**: Add a dashboard for visualizing metrics
3. **Alerting**: Add threshold-based alerting for abnormal metrics
4. **Distributed Metrics**: Support for aggregating metrics across multiple instances
5. **Custom Metrics**: Allow users to define custom metrics for specific use cases
