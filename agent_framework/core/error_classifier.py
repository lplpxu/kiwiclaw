"""API error classification for smart failover and recovery.

Provides a structured taxonomy of API errors and a priority-ordered
classification pipeline that determines the correct recovery action
(retry, rotate credential, fallback to another provider, compress
context, or abort).

参考 hermes-agent/agent/error_classifier.py 实现
"""

import enum
import logging
import time
import random
from dataclasses import dataclass, field
from typing import Any, Optional, Callable

logger = logging.getLogger(__name__)


class FailoverReason(enum.Enum):
    """Why an API call or tool execution failed — determines recovery strategy."""

    # Authentication / authorization
    auth = "auth"
    auth_permanent = "auth_permanent"

    # Billing / quota
    billing = "billing"
    rate_limit = "rate_limit"

    # Server-side
    overloaded = "overloaded"
    server_error = "server_error"

    # Transport
    timeout = "timeout"
    connection_error = "connection_error"

    # Context / payload
    context_overflow = "context_overflow"
    payload_too_large = "payload_too_large"

    # Model
    model_not_found = "model_not_found"

    # Request format
    format_error = "format_error"

    # Tool execution
    tool_error = "tool_error"
    tool_not_found = "tool_not_found"
    tool_blocked = "tool_blocked"

    # Resource
    resource_not_found = "resource_not_found"
    permission_denied = "permission_denied"

    # Catch-all
    unknown = "unknown"


class RecoveryAction(enum.Enum):
    """Recovery actions to take based on error classification."""
    retry = "retry"
    retry_with_backoff = "retry_with_backoff"
    compress_and_retry = "compress_and_retry"
    rotate_credential = "rotate_credential"
    fallback_provider = "fallback_provider"
    fallback_model = "fallback_model"
    abort = "abort"
    escalate_to_human = "escalate_to_human"


@dataclass
class ClassifiedError:
    """Structured classification of an error with recovery hints."""

    reason: FailoverReason
    message: str = ""
    status_code: Optional[int] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    tool_name: Optional[str] = None
    error_context: dict = field(default_factory=dict)

    retryable: bool = True
    should_compress: bool = False
    should_rotate_credential: bool = False
    should_fallback: bool = False
    should_react: bool = False  # 重新分析问题，换策略

    recovery_action: RecoveryAction = RecoveryAction.retry

    def to_dict(self) -> dict:
        return {
            "reason": self.reason.value,
            "message": self.message,
            "status_code": self.status_code,
            "retryable": self.retryable,
            "recovery_action": self.recovery_action.value,
        }


class ErrorClassifier:
    """错误分类器 - 将错误分类为 FailoverReason 并确定恢复策略"""

    def __init__(self):
        self._handlers: list[Callable[[Exception, Any], Optional[ClassifiedError]]] = []

    def register_handler(
        self, handler: Callable[[Exception, Any], Optional[ClassifiedError]]
    ) -> None:
        """注册自定义错误处理函数"""
        self._handlers.append(handler)

    def classify(
        self,
        error: Exception,
        context: Any = None,
        status_code: Optional[int] = None,
        tool_name: Optional[str] = None,
    ) -> ClassifiedError:
        """对错误进行分类并返回恢复策略

        Args:
            error: 异常对象
            context: 额外上下文
            status_code: HTTP 状态码
            tool_name: 工具名称（如果是工具执行错误）

        Returns:
            ClassifiedError with recovery hints
        """
        print(f"[DEBUG error_classifier] classify() error={error}, status_code={status_code}, tool_name={tool_name}")

        # 先尝试自定义 handlers
        for handler in self._handlers:
            result = handler(error, context)
            if result is not None:
                print(f"[DEBUG error_classifier] custom handler returned: {result.reason.value}")
                return result

        print(f"[DEBUG error_classifier] using built-in classification: error_type={type(error).__name__}")

        # 内置分类逻辑
        error_message = str(error).lower()
        error_type = type(error).__name__

        # HTTP 状态码分类
        if status_code:
            if status_code == 401 or status_code == 403:
                if "api" in error_message or "key" in error_message:
                    return ClassifiedError(
                        reason=FailoverReason.auth,
                        message=str(error),
                        status_code=status_code,
                        retryable=False,
                        should_rotate_credential=True,
                        recovery_action=RecoveryAction.rotate_credential,
                    )
                return ClassifiedError(
                    reason=FailoverReason.auth_permanent,
                    message=str(error),
                    status_code=status_code,
                    retryable=False,
                    recovery_action=RecoveryAction.abort,
                )

            if status_code == 429:
                return ClassifiedError(
                    reason=FailoverReason.rate_limit,
                    message=str(error),
                    status_code=status_code,
                    retryable=True,
                    recovery_action=RecoveryAction.retry_with_backoff,
                )

            if status_code == 500:
                return ClassifiedError(
                    reason=FailoverReason.server_error,
                    message=str(error),
                    status_code=status_code,
                    retryable=True,
                    recovery_action=RecoveryAction.retry_with_backoff,
                )

            if status_code == 502 or status_code == 503 or status_code == 529:
                return ClassifiedError(
                    reason=FailoverReason.overloaded,
                    message=str(error),
                    status_code=status_code,
                    retryable=True,
                    recovery_action=RecoveryAction.retry_with_backoff,
                )

            if status_code == 404:
                return ClassifiedError(
                    reason=FailoverReason.resource_not_found,
                    message=str(error),
                    status_code=status_code,
                    retryable=False,
                    recovery_action=RecoveryAction.abort,
                )

            if status_code == 413:
                return ClassifiedError(
                    reason=FailoverReason.payload_too_large,
                    message=str(error),
                    status_code=status_code,
                    retryable=False,
                    should_compress=True,
                    recovery_action=RecoveryAction.compress_and_retry,
                )

        # 异常类型分类
        if error_type in ("TimeoutException", "TimeoutError") or "timeout" in error_message:
            return ClassifiedError(
                reason=FailoverReason.timeout,
                message=str(error),
                retryable=True,
                recovery_action=RecoveryAction.retry_with_backoff,
            )

        if error_type == "ConnectError" or error_type == "ConnectionError":
            return ClassifiedError(
                reason=FailoverReason.connection_error,
                message=str(error),
                retryable=True,
                recovery_action=RecoveryAction.retry_with_backoff,
            )

        # 工具错误分类
        if tool_name:
            if "blocked" in error_message or "denied" in error_message:
                return ClassifiedError(
                    reason=FailoverReason.tool_blocked,
                    message=str(error),
                    tool_name=tool_name,
                    retryable=False,
                    recovery_action=RecoveryAction.escalate_to_human,
                )
            if "not found" in error_message or "unknown tool" in error_message:
                return ClassifiedError(
                    reason=FailoverReason.tool_not_found,
                    message=str(error),
                    tool_name=tool_name,
                    retryable=False,
                    recovery_action=RecoveryAction.abort,
                )
            return ClassifiedError(
                reason=FailoverReason.tool_error,
                message=str(error),
                tool_name=tool_name,
                retryable=True,
                should_react=True,  # 工具错误可能需要换策略
                recovery_action=RecoveryAction.retry,
            )

        # 认证相关
        if "api" in error_message and ("key" in error_message or "token" in error_message):
            return ClassifiedError(
                reason=FailoverReason.auth,
                message=str(error),
                retryable=False,
                should_rotate_credential=True,
                recovery_action=RecoveryAction.rotate_credential,
            )

        # 未找到资源
        if "not found" in error_message or "404" in error_message:
            return ClassifiedError(
                reason=FailoverReason.resource_not_found,
                message=str(error),
                retryable=False,
                recovery_action=RecoveryAction.abort,
            )

        # 默认未知错误
        return ClassifiedError(
            reason=FailoverReason.unknown,
            message=str(error),
            retryable=True,
            should_react=True,
            recovery_action=RecoveryAction.retry_with_backoff,
        )


class RetryPolicy:
    """重试策略 - 带指数退避和 jitter"""

    def __init__(
        self,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        max_attempts: int = 3,
        jitter_ratio: float = 0.3,
    ):
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.max_attempts = max_attempts
        self.jitter_ratio = jitter_ratio

    def should_retry(self, attempt: int, classified: ClassifiedError) -> bool:
        """判断是否应该重试"""
        if attempt >= self.max_attempts:
            return False
        if not classified.retryable:
            return False
        return True

    def get_delay(self, attempt: int, classified: ClassifiedError) -> float:
        """计算退避延迟"""
        if classified.reason == FailoverReason.rate_limit:
            delay = min(self.base_delay * (2 ** attempt) * 2, self.max_delay)
        else:
            delay = min(self.base_delay * (2 ** attempt), self.max_delay)

        # 添加 jitter 防止多实例同时重试
        jitter = random.uniform(0, delay * self.jitter_ratio)
        return delay + jitter

    def execute_with_retry(
        self,
        func: Callable,
        *args,
        classified_error: Optional[ClassifiedError] = None,
        **kwargs,
    ) -> tuple[Any, Optional[ClassifiedError]]:
        """带重试的执行

        Returns:
            (result, error) - 成功时 result 为返回值，error 为 None
                           - 失败时 result 为 None，error 为 ClassifiedError
        """
        attempt = 0
        last_error: Optional[ClassifiedError] = classified_error

        while True:
            if last_error and not self.should_retry(attempt, last_error):
                return None, last_error

            if attempt > 0 and last_error:
                delay = self.get_delay(attempt, last_error)
                logger.info(
                    f"Retrying after {delay:.2f}s (attempt {attempt + 1}/{self.max_attempts})"
                )
                time.sleep(delay)

            try:
                result = func(*args, **kwargs)
                return result, None
            except Exception as e:
                last_error = ErrorClassifier().classify(e)
                logger.warning(f"Attempt {attempt + 1} failed: {last_error}")

                # 检查是否应该换策略（react）
                if last_error.should_react:
                    logger.info("Error suggests a different approach might be needed")

                # 检查是否应该压缩后重试
                if last_error.should_compress:
                    logger.info("Context overflow - compression needed before retry")

                # 检查是否应该切换 provider
                if last_error.should_fallback:
                    logger.info("Should fallback to another provider")

            attempt += 1

        return None, last_error


# 全局错误分类器实例
_classifier: Optional[ErrorClassifier] = None


def get_error_classifier() -> ErrorClassifier:
    """获取全局错误分类器"""
    global _classifier
    if _classifier is None:
        _classifier = ErrorClassifier()
    return _classifier


def classify_error(
    error: Exception,
    context: Any = None,
    status_code: Optional[int] = None,
    tool_name: Optional[str] = None,
) -> ClassifiedError:
    """快速错误分类函数"""
    return get_error_classifier().classify(error, context, status_code, tool_name)
