"""
Retry utility for handling transient failures in network operations.

This module provides a decorator for retrying operations that may fail due to
transient network issues, with configurable retry attempts, delays, and
exponential backoff.
"""

import functools
import random
import time
from collections.abc import Callable
from typing import TypeVar, cast

from loguru import logger

T = TypeVar("T")


def retry(
    exceptions: type[Exception] | tuple[type[Exception], ...] = Exception,
    max_retries: int | None = None,
    retry_delay: float | None = None,
    retry_backoff: float | None = None,
    retry_jitter: float | None = None,
    on_retry: Callable[[Exception, int], None] | None = None,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """
    Decorator for retrying operations that may fail due to transient issues.

    Args:
        exceptions: Exception type(s) to catch and retry on
        max_retries: Maximum number of retry attempts (None = use config value)
        retry_delay: Initial delay between retries in seconds (None = use config value)
        retry_backoff: Multiplier for exponential backoff (None = use config value)
        retry_jitter: Random jitter factor to add to delay (None = use config value)
        on_retry: Optional callback function to execute on each retry

    Returns:
        Decorated function that will retry on specified exceptions
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> T:
            # Get retry configuration from the first argument (self) if it has fast_parse_config
            # This assumes the decorated method belongs to a class with self.fast_parse_config
            config_max_retries = 3
            config_retry_delay = 1.0
            config_retry_backoff = 2.0
            config_retry_jitter = 0.1

            if args and hasattr(args[0], "fast_parse_config"):
                config = args[0].fast_parse_config
                config_max_retries = getattr(config, "max_retries", 3)
                config_retry_delay = getattr(config, "retry_delay", 1.0)
                config_retry_backoff = getattr(config, "retry_backoff", 2.0)
                config_retry_jitter = getattr(config, "retry_jitter", 0.1)

            # Use provided values or fall back to config values
            _max_retries = max_retries if max_retries is not None else config_max_retries
            _retry_delay = retry_delay if retry_delay is not None else config_retry_delay
            _retry_backoff = retry_backoff if retry_backoff is not None else config_retry_backoff
            _retry_jitter = retry_jitter if retry_jitter is not None else config_retry_jitter

            retries = 0
            while True:
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    retries += 1
                    if retries > _max_retries:
                        logger.error(f"Max retries ({_max_retries}) exceeded for {func.__name__}: {e}")
                        raise

                    # Calculate delay with exponential backoff and jitter
                    delay = _retry_delay * (_retry_backoff ** (retries - 1))
                    if _retry_jitter > 0:
                        delay += delay * random.uniform(0, _retry_jitter)

                    # Log retry attempt
                    logger.warning(
                        f"Retry {retries}/{_max_retries} for {func.__name__} after {delay:.2f}s: {e}"
                    )

                    # Execute callback if provided
                    if on_retry:
                        on_retry(e, retries)

                    # Wait before retrying
                    time.sleep(delay)

        return cast(Callable[..., T], wrapper)

    return decorator
