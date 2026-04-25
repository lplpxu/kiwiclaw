"""Circuit Breaker Module

Provides fault tolerance through circuit breaker pattern.
Prevents cascading failures by failing fast when a service is unhealthy.
[PHASE11] 核心运行时 - CircuitBreaker
"""

import time
import threading
from typing import Callable, Any, Optional
from dataclasses import dataclass
from enum import Enum
import functools

# Debug print helper
def _debug(msg: str):
    print(f"[PHASE11] [CircuitBreaker] {msg}")


class CircuitState(Enum):
    """Circuit breaker states"""
    CLOSED = "closed"      # Normal operation, requests pass through
    OPEN = "open"          # Circuit is tripped, requests fail fast
    HALF_OPEN = "half_open"  # Testing if service has recovered


@dataclass
class CircuitStats:
    """Statistics for a circuit breaker"""
    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    rejected_calls: int = 0
    consecutive_failures: int = 0
    consecutive_successes: int = 0
    last_failure_time: float = 0
    last_success_time: float = 0
    state_changed_at: float = 0

    def failure_rate(self) -> float:
        """Calculate failure rate"""
        if self.total_calls == 0:
            return 0.0
        return self.failed_calls / self.total_calls

    def to_dict(self) -> dict:
        return {
            "total_calls": self.total_calls,
            "successful_calls": self.successful_calls,
            "failed_calls": self.failed_calls,
            "rejected_calls": self.rejected_calls,
            "consecutive_failures": self.consecutive_failures,
            "consecutive_successes": self.consecutive_successes,
            "failure_rate": self.failure_rate(),
            "state": None,  # Set by CircuitBreaker
        }


class CircuitBreaker:
    """Circuit breaker implementation

    Prevents cascading failures by tracking error rates and tripping
    the circuit when a threshold is exceeded.

    States:
    - CLOSED: Normal operation, errors are tracked
    - OPEN: Circuit is tripped, requests fail immediately
    - HALF_OPEN: Testing recovery, limited requests pass through
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,          # Failures before opening
        success_threshold: int = 3,           # Successes before closing
        timeout: float = 30.0,               # Seconds before trying half_open
        half_open_max_calls: int = 3,        # Max calls in half_open state
        rejection_threshold: float = 0.5,    # Reject if failure rate > 50%
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.success_threshold = success_threshold
        self.timeout = timeout
        self.half_open_max_calls = half_open_max_calls
        self.rejection_threshold = rejection_threshold

        self._state = CircuitState.CLOSED
        self._stats = CircuitStats()
        self._lock = threading.Lock()
        self._last_state_change = time.time()

        # For half-open state tracking
        self._half_open_calls = 0

    @property
    def state(self) -> CircuitState:
        """Get current circuit state"""
        with self._lock:
            if self._state == CircuitState.OPEN:
                # Check if timeout has elapsed to transition to half_open
                if time.time() - self._last_state_change >= self.timeout:
                    self._transition_to(CircuitState.HALF_OPEN)
            return self._state

    @property
    def stats(self) -> CircuitStats:
        """Get circuit statistics"""
        with self._lock:
            stats = CircuitStats(
                total_calls=self._stats.total_calls,
                successful_calls=self._stats.successful_calls,
                failed_calls=self._stats.failed_calls,
                rejected_calls=self._stats.rejected_calls,
                consecutive_failures=self._stats.consecutive_failures,
                consecutive_successes=self._stats.consecutive_successes,
                last_failure_time=self._stats.last_failure_time,
                last_success_time=self._stats.last_success_time,
                state_changed_at=self._last_state_change,
            )
            return stats

    def _transition_to(self, new_state: CircuitState) -> None:
        """Transition to a new state"""
        old_state = self._state
        self._state = new_state
        self._last_state_change = time.time()

        if new_state == CircuitState.HALF_OPEN:
            self._half_open_calls = 0

        print(f"[DEBUG circuit_breaker] {self.name}: {old_state.value} -> {new_state.value}")

    def is_request_allowed(self) -> tuple[bool, str]:
        """Check if a request is allowed

        Returns:
            (allowed, reason)
        """
        _debug(f"→ is_request_allowed() state={self.state.value}")
        with self._lock:
            current_state = self.state  # This may trigger state transition

            if current_state == CircuitState.CLOSED:
                _debug(f"← is_request_allowed → ALLOWED (circuit closed)")
                return True, "Circuit closed, request allowed"

            elif current_state == CircuitState.OPEN:
                wait_time = self.timeout - (time.time() - self._last_state_change)
                return False, f"Circuit open, retry in {wait_time:.1f}s"

            elif current_state == CircuitState.HALF_OPEN:
                if self._half_open_calls >= self.half_open_max_calls:
                    return False, f"Half-open max calls ({self.half_open_max_calls}) reached"
                self._half_open_calls += 1
                return True, "Circuit half-open, testing recovery"

            return False, "Unknown state"

    def record_success(self) -> None:
        """Record a successful call"""
        with self._lock:
            self._stats.total_calls += 1
            self._stats.successful_calls += 1
            self._stats.consecutive_successes += 1
            self._stats.consecutive_failures = 0
            self._stats.last_success_time = time.time()

            # In half-open state, check if we should close
            if self._state == CircuitState.HALF_OPEN:
                if self._stats.consecutive_successes >= self.success_threshold:
                    self._transition_to(CircuitState.CLOSED)
                    self._stats.consecutive_successes = 0

    def record_failure(self) -> None:
        """Record a failed call"""
        with self._lock:
            self._stats.total_calls += 1
            self._stats.failed_calls += 1
            self._stats.consecutive_failures += 1
            self._stats.consecutive_successes = 0
            self._stats.last_failure_time = time.time()

            # Check if we should open
            if self._state == CircuitState.CLOSED:
                if self._stats.consecutive_failures >= self.failure_threshold:
                    self._transition_to(CircuitState.OPEN)

            # In half-open state, any failure re-opens
            elif self._state == CircuitState.HALF_OPEN:
                self._transition_to(CircuitState.OPEN)

    def record_rejection(self) -> None:
        """Record a rejected call (circuit open)"""
        with self._lock:
            self._stats.rejected_calls += 1

    def reset(self) -> None:
        """Reset the circuit breaker to initial state"""
        with self._lock:
            self._state = CircuitState.CLOSED
            self._stats = CircuitStats()
            self._half_open_calls = 0
            self._last_state_change = time.time()

    def execute(self, func: Callable, *args, **kwargs) -> Any:
        """Execute a function through the circuit breaker

        Args:
            func: Function to execute
            *args, **kwargs: Arguments to pass to function

        Returns:
            Result of function call

        Raises:
            CircuitBreakerError: If circuit is open or call fails
        """
        allowed, reason = self.is_request_allowed()
        if not allowed:
            self.record_rejection()
            raise CircuitBreakerError(f"Circuit breaker open: {reason}")

        try:
            result = func(*args, **kwargs)
            self.record_success()
            return result
        except Exception as e:
            self.record_failure()
            raise CircuitBreakerError(f"Circuit breaker recorded failure: {e}") from e

    async def execute_async(self, func: Callable, *args, **kwargs) -> Any:
        """Execute an async function through the circuit breaker"""
        allowed, reason = self.is_request_allowed()
        if not allowed:
            self.record_rejection()
            raise CircuitBreakerError(f"Circuit breaker open: {reason}")

        try:
            result = await func(*args, **kwargs)
            self.record_success()
            return result
        except Exception as e:
            self.record_failure()
            raise CircuitBreakerError(f"Circuit breaker recorded failure: {e}") from e

    def get_health_status(self) -> dict:
        """Get health status of the circuit breaker"""
        with self._lock:
            return {
                "name": self.name,
                "state": self.state.value,
                "stats": self.stats.to_dict(),
                "config": {
                    "failure_threshold": self.failure_threshold,
                    "success_threshold": self.success_threshold,
                    "timeout": self.timeout,
                },
                "time_in_current_state": time.time() - self._last_state_change,
            }


class CircuitBreakerError(Exception):
    """Exception raised when circuit breaker is open or call fails"""
    pass


class CircuitBreakerRegistry:
    """Registry for managing multiple circuit breakers"""

    def __init__(self):
        self._breakers: dict[str, CircuitBreaker] = {}
        self._lock = threading.Lock()

    def get_or_create(
        self,
        name: str,
        **kwargs
    ) -> CircuitBreaker:
        """Get an existing circuit breaker or create a new one"""
        with self._lock:
            if name not in self._breakers:
                self._breakers[name] = CircuitBreaker(name, **kwargs)
            return self._breakers[name]

    def get(self, name: str) -> Optional[CircuitBreaker]:
        """Get a circuit breaker by name"""
        with self._lock:
            return self._breakers.get(name)

    def get_all_health(self) -> dict:
        """Get health status of all circuit breakers"""
        with self._lock:
            return {
                name: breaker.get_health_status()
                for name, breaker in self._breakers.items()
            }

    def reset_all(self) -> None:
        """Reset all circuit breakers"""
        with self._lock:
            for breaker in self._breakers.values():
                breaker.reset()


# Global registry
_registry: Optional[CircuitBreakerRegistry] = None


def get_registry() -> CircuitBreakerRegistry:
    """Get the global circuit breaker registry"""
    global _registry
    if _registry is None:
        _registry = CircuitBreakerRegistry()
    return _registry


def circuit_breaker(
    name: str = None,
    failure_threshold: int = 5,
    success_threshold: int = 3,
    timeout: float = 30.0,
):
    """Decorator to add circuit breaker to a function

    Usage:
        @circuit_breaker(name="my_service", failure_threshold=3)
        async def my_function():
            ...
    """
    def decorator(func):
        _name = name or func.__name__

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            breaker = get_registry().get_or_create(
                _name,
                failure_threshold=failure_threshold,
                success_threshold=success_threshold,
                timeout=timeout,
            )
            return breaker.execute(func, *args, **kwargs)

        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            breaker = get_registry().get_or_create(
                _name,
                failure_threshold=failure_threshold,
                success_threshold=success_threshold,
                timeout=timeout,
            )
            return await breaker.execute_async(func, *args, **kwargs)

        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator
