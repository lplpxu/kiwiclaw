"""Error Handling Module

Provides comprehensive error handling, recovery strategies, and circuit breakers.
[PHASE11] 核心运行时 - ErrorHandler
"""

import time
import logging
import asyncio
from typing import Dict, Any, Optional, Callable, List
from dataclasses import dataclass, field
from enum import Enum
import threading

# Debug print helper
def _debug(msg: str):
    print(f"[PHASE11] [ErrorHandler] {msg}")


class ErrorCategory(Enum):
    """Category of error"""
    TOOL_ERROR = "tool_error"
    API_ERROR = "api_error"
    TIMEOUT_ERROR = "timeout_error"
    PERMISSION_ERROR = "permission_error"
    VALIDATION_ERROR = "validation_error"
    NETWORK_ERROR = "network_error"
    UNKNOWN_ERROR = "unknown_error"


class RecoveryAction(Enum):
    """Action to take for recovery"""
    RETRY = "retry"
    FALLBACK = "fallback"
    ABORT = "abort"
    ESCALATE = "escalate"
    SKIP = "skip"


@dataclass
class ErrorInfo:
    """Information about an error"""
    category: ErrorCategory
    message: str
    recoverable: bool
    timestamp: float = field(default_factory=time.time)
    retry_count: int = 0
    original_exception: Optional[Exception] = None
    context: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RecoveryStrategy:
    """Strategy for recovering from errors"""
    action: RecoveryAction
    max_retries: int = 3
    backoff_multiplier: float = 2.0
    initial_delay_ms: float = 100.0
    max_delay_ms: float = 10000.0
    fallback_handler: Optional[Callable] = None


class ErrorClassifier:
    """Classifies errors into categories

    Determines the category of an error and whether it's recoverable.
    """

    def __init__(self):
        self._classifiers: Dict[ErrorCategory, Callable[[Exception], bool]] = {}

    def register_classifier(
        self,
        category: ErrorCategory,
        classifier: Callable[[Exception], bool]
    ) -> None:
        """Register a classifier function for a category

        Args:
            category: Error category
            classifier: Function that returns True if exception matches
        """
        self._classifiers[category] = classifier

    def classify(self, exception: Exception) -> ErrorInfo:
        """Classify an exception

        Args:
            exception: Exception to classify

        Returns:
            ErrorInfo with classification details
        """
        for category, classifier in self._classifiers.items():
            if classifier(exception):
                return ErrorInfo(
                    category=category,
                    message=str(exception),
                    recoverable=self._is_recoverable(category),
                    original_exception=exception,
                )

        # Default classification
        return ErrorInfo(
            category=ErrorCategory.UNKNOWN_ERROR,
            message=str(exception),
            recoverable=False,
            original_exception=exception,
        )

    def _is_recoverable(self, category: ErrorCategory) -> bool:
        """Determine if an error category is typically recoverable"""
        recoverable = {
            ErrorCategory.TIMEOUT_ERROR,
            ErrorCategory.NETWORK_ERROR,
            ErrorCategory.API_ERROR,
        }
        return category in recoverable


class RecoveryManager:
    """Manages error recovery strategies

    Executes recovery actions with proper backoff and fallback handling.
    """

    def __init__(self):
        self._strategies: Dict[ErrorCategory, RecoveryStrategy] = {}
        self._retry_state: Dict[str, int] = {}
        self._lock = threading.Lock()

    def register_strategy(
        self,
        category: ErrorCategory,
        strategy: RecoveryStrategy
    ) -> None:
        """Register a recovery strategy for an error category

        Args:
            category: Error category
            strategy: Recovery strategy to use
        """
        with self._lock:
            self._strategies[category] = strategy

    def get_strategy(self, category: ErrorCategory) -> RecoveryStrategy:
        """Get recovery strategy for an error category

        Args:
            category: Error category

        Returns:
            RecoveryStrategy (uses default if not registered)
        """
        with self._lock:
            return self._strategies.get(category, RecoveryStrategy(
                action=RecoveryAction.ABORT,
            ))

    async def execute_recovery(
        self,
        error_info: ErrorInfo,
        operation: Callable,
        *args,
        **kwargs
    ) -> Any:
        """Execute recovery for an operation

        Args:
            error_info: Information about the error
            operation: Operation to retry/recover
            *args: Positional arguments for operation
            **kwargs: Keyword arguments for operation

        Returns:
            Result of operation after recovery attempts
        """
        strategy = self.get_strategy(error_info.category)

        if strategy.action == RecoveryAction.RETRY:
            return await self._retry_with_backoff(
                error_info, operation, strategy, *args, **kwargs
            )
        elif strategy.action == RecoveryAction.FALLBACK:
            return await self._fallback(
                error_info, strategy, *args, **kwargs
            )
        elif strategy.action == RecoveryAction.ABORT:
            raise error_info.original_exception or Exception(error_info.message)
        elif strategy.action == RecoveryAction.ESCALATE:
            return await self._escalate(error_info, operation, *args, **kwargs)
        else:
            return await operation(*args, **kwargs)

    async def _retry_with_backoff(
        self,
        error_info: ErrorInfo,
        operation: Callable,
        strategy: RecoveryStrategy,
        *args,
        **kwargs
    ) -> Any:
        """Retry operation with exponential backoff"""
        delay_ms = strategy.initial_delay_ms
        last_exception = error_info.original_exception

        for attempt in range(strategy.max_retries):
            try:
                return await operation(*args, **kwargs)
            except Exception as e:
                last_exception = e
                error_info.retry_count = attempt + 1

                if attempt < strategy.max_retries - 1:
                    await asyncio.sleep(delay_ms / 1000)
                    delay_ms = min(
                        delay_ms * strategy.backoff_multiplier,
                        strategy.max_delay_ms
                    )

        raise last_exception

    async def _fallback(
        self,
        error_info: ErrorInfo,
        strategy: RecoveryStrategy,
        *args,
        **kwargs
    ) -> Any:
        """Execute fallback handler"""
        if strategy.fallback_handler:
            return strategy.fallback_handler(*args, **kwargs)
        raise error_info.original_exception

    async def _escalate(
        self,
        error_info: ErrorInfo,
        operation: Callable,
        *args,
        **kwargs
    ) -> Any:
        """Escalate error - log and re-raise"""
        logging.error(f"Escalated error: {error_info.message}")
        raise error_info.original_exception


class CircuitBreaker:
    """Circuit breaker pattern implementation

    Prevents cascading failures by temporarily blocking failing operations.
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        half_open_max_calls: int = 3,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls

        self._state: str = "closed"  # closed, open, half_open
        self._failure_count: int = 0
        self._last_failure_time: float = 0
        self._half_open_calls: int = 0
        self._lock = threading.Lock()

    @property
    def state(self) -> str:
        """Get current circuit state"""
        with self._lock:
            if self._state == "open":
                # Check if recovery timeout has passed
                if time.time() - self._last_failure_time >= self.recovery_timeout:
                    self._state = "half_open"
                    self._half_open_calls = 0
            return self._state

    def record_success(self) -> None:
        """Record a successful call"""
        with self._lock:
            self._failure_count = 0
            if self._state == "half_open":
                self._half_open_calls += 1
                if self._half_open_calls >= self.half_open_max_calls:
                    self._state = "closed"

    def record_failure(self) -> None:
        """Record a failed call"""
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()

            if self._failure_count >= self.failure_threshold:
                self._state = "open"

    def can_execute(self) -> bool:
        """Check if execution is allowed"""
        return self.state != "open"

    async def execute(self, operation: Callable, *args, **kwargs) -> Any:
        """Execute operation with circuit breaker protection

        Args:
            operation: Operation to execute
            *args: Positional arguments
            **kwargs: Keyword arguments

        Returns:
            Operation result

        Raises:
            Exception if circuit is open or operation fails
        """
        if not self.can_execute():
            raise Exception(f"Circuit breaker '{self.name}' is open")

        try:
            result = await operation(*args, **kwargs)
            self.record_success()
            return result
        except Exception as e:
            self.record_failure()
            raise


# Global error handling components
_classifier: Optional[ErrorClassifier] = None
_recovery_manager: Optional[RecoveryManager] = None


def get_error_classifier() -> ErrorClassifier:
    """Get the global error classifier"""
    global _classifier
    if _classifier is None:
        _classifier = ErrorClassifier()
        # Register default classifiers
        _classifier.register_classifier(
            ErrorCategory.TIMEOUT_ERROR,
            lambda e: isinstance(e, asyncio.TimeoutError)
        )
        _classifier.register_classifier(
            ErrorCategory.NETWORK_ERROR,
            lambda e: "connection" in str(e).lower() or "network" in str(e).lower()
        )
        _classifier.register_classifier(
            ErrorCategory.API_ERROR,
            lambda e: "api" in str(e).lower() or "rate limit" in str(e).lower()
        )
    return _classifier


def get_recovery_manager() -> RecoveryManager:
    """Get the global recovery manager"""
    global _recovery_manager
    if _recovery_manager is None:
        _recovery_manager = RecoveryManager()
    return _recovery_manager