"""Tests for retry decorator logic.

This module tests the retry decorator's behavior including success cases,
failure cases, exponential backoff, and callback execution.
"""

import time

import pytest

from mailtag.retry import retry


def test_retry_success_first_attempt():
    """Test function succeeds without retry."""
    call_count = 0

    @retry(max_retries=3)
    def succeeds():
        nonlocal call_count
        call_count += 1
        return "success"

    result = succeeds()
    assert result == "success"
    assert call_count == 1  # No retries needed


def test_retry_success_after_failures():
    """Test function succeeds after 2 failures."""
    call_count = 0

    @retry(max_retries=3, retry_delay=0.01, retry_backoff=1.0)
    def fails_twice():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise ConnectionError("Failed")
        return "success"

    result = fails_twice()
    assert result == "success"
    assert call_count == 3  # Initial + 2 retries


def test_retry_exhaust_retries():
    """Test function fails after max retries."""
    call_count = 0

    @retry(max_retries=2, retry_delay=0.01)
    def always_fails():
        nonlocal call_count
        call_count += 1
        raise ConnectionError("Failed")

    with pytest.raises(ConnectionError, match="Failed"):
        always_fails()

    assert call_count == 3  # Initial + 2 retries


def test_retry_default_parameters():
    """Test retry uses correct default values."""
    call_count = 0

    @retry()  # No parameters - should use defaults
    def fails_once():
        nonlocal call_count
        call_count += 1
        if call_count < 2:
            raise Exception("Failed")
        return "success"

    result = fails_once()
    assert result == "success"
    assert call_count == 2


def test_retry_specific_exception_type():
    """Test retry only catches specified exception types."""
    call_count = 0

    @retry(exceptions=ConnectionError, max_retries=2, retry_delay=0.01)
    def raises_value_error():
        nonlocal call_count
        call_count += 1
        raise ValueError("Not a connection error")

    # ValueError should not be caught and retried
    with pytest.raises(ValueError, match="Not a connection error"):
        raises_value_error()

    assert call_count == 1  # No retries for unhandled exception


def test_retry_multiple_exception_types():
    """Test retry catches multiple exception types."""
    attempts = []

    @retry(
        exceptions=(ConnectionError, TimeoutError),
        max_retries=3,
        retry_delay=0.01,
    )
    def alternating_errors():
        attempt = len(attempts) + 1
        attempts.append(attempt)

        if attempt == 1:
            raise ConnectionError("Connection failed")
        elif attempt == 2:
            raise TimeoutError("Timeout")
        return "success"

    result = alternating_errors()
    assert result == "success"
    assert len(attempts) == 3


def test_retry_exponential_backoff():
    """Test retry delay increases exponentially."""
    delays = []

    @retry(max_retries=3, retry_delay=0.1, retry_backoff=2.0, retry_jitter=0.0)
    def track_delays():
        delays.append(time.time())
        # Always fail to track all retry delays
        raise ConnectionError(f"Failure {len(delays)}")

    with pytest.raises(ConnectionError):
        track_delays()

    # Check that delays roughly follow exponential backoff
    # Initial attempt + 3 retries = 4 timestamps
    # Delay 1: 0.1s, Delay 2: 0.2s, Delay 3: 0.4s
    assert len(delays) == 4
    first_delay = delays[1] - delays[0]
    second_delay = delays[2] - delays[1]
    third_delay = delays[3] - delays[2]

    # Allow 50ms tolerance for timing
    assert 0.05 < first_delay < 0.15  # ~0.1s
    assert 0.15 < second_delay < 0.25  # ~0.2s
    assert 0.35 < third_delay < 0.45  # ~0.4s


def test_retry_on_retry_callback():
    """Test on_retry callback is called correctly."""
    retry_log = []

    def log_retry(exception: Exception, attempt: int):
        retry_log.append((str(exception), attempt))

    @retry(max_retries=2, retry_delay=0.01, on_retry=log_retry)
    def fails_twice():
        if len(retry_log) < 2:
            raise ValueError(f"Attempt {len(retry_log)}")
        return "success"

    result = fails_twice()
    assert result == "success"
    assert len(retry_log) == 2
    assert retry_log[0] == ("Attempt 0", 1)
    assert retry_log[1] == ("Attempt 1", 2)


def test_retry_with_return_value():
    """Test retry preserves return values."""

    @retry(max_retries=2, retry_delay=0.01)
    def returns_dict():
        return {"key": "value", "number": 42}

    result = returns_dict()
    assert isinstance(result, dict)
    assert result["key"] == "value"
    assert result["number"] == 42


def test_retry_with_args_and_kwargs():
    """Test retry preserves function arguments."""
    call_history = []

    @retry(max_retries=2, retry_delay=0.01)
    def with_arguments(pos_arg, keyword_arg=None):
        call_history.append((pos_arg, keyword_arg))
        if len(call_history) < 2:
            raise ConnectionError("Failed")
        return f"{pos_arg}-{keyword_arg}"

    result = with_arguments("test", keyword_arg="value")
    assert result == "test-value"
    assert len(call_history) == 2
    assert all(args == ("test", "value") for args in call_history)


def test_retry_preserves_function_name():
    """Test retry decorator preserves function metadata."""

    @retry()
    def my_function():
        """This is my function."""
        return "result"

    assert my_function.__name__ == "my_function"
    assert "This is my function" in my_function.__doc__


def test_retry_with_zero_jitter():
    """Test retry with jitter disabled."""

    @retry(max_retries=1, retry_delay=0.1, retry_jitter=0.0)
    def fails_once():
        if not hasattr(fails_once, "called"):
            fails_once.called = True
            raise ConnectionError("Failed")
        return "success"

    result = fails_once()
    assert result == "success"


def test_retry_no_retries_on_success():
    """Test no retries occur when function succeeds immediately."""
    retry_callback_called = False

    def on_retry_callback(exception, attempt):
        nonlocal retry_callback_called
        retry_callback_called = True

    @retry(max_retries=3, on_retry=on_retry_callback)
    def succeeds_immediately():
        return "success"

    result = succeeds_immediately()
    assert result == "success"
    assert not retry_callback_called


def test_retry_respects_max_retries_parameter():
    """Test max_retries parameter is respected."""
    call_count = 0

    @retry(max_retries=5, retry_delay=0.01)
    def fails_multiple_times():
        nonlocal call_count
        call_count += 1
        if call_count <= 5:
            raise ConnectionError("Failed")
        return "success"

    result = fails_multiple_times()
    assert result == "success"
    assert call_count == 6  # Initial + 5 retries


def test_retry_with_none_parameters_uses_defaults():
    """Test None parameters fall back to defaults."""

    @retry(max_retries=None, retry_delay=None)
    def test_function():
        return "success"

    # Should use defaults (max_retries=3, retry_delay=1.0) without error
    result = test_function()
    assert result == "success"


def test_retry_exception_propagates_after_max_retries():
    """Test original exception propagates after exhausting retries."""

    @retry(max_retries=1, retry_delay=0.01)
    def custom_error():
        raise ValueError("Custom error message")

    with pytest.raises(ValueError, match="Custom error message"):
        custom_error()


def test_retry_with_method():
    """Test retry works on class methods."""

    class TestClass:
        def __init__(self):
            self.call_count = 0

        @retry(max_retries=2, retry_delay=0.01)
        def method_that_retries(self):
            self.call_count += 1
            if self.call_count < 2:
                raise ConnectionError("Failed")
            return "success"

    obj = TestClass()
    result = obj.method_that_retries()
    assert result == "success"
    assert obj.call_count == 2
