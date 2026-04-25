"""Execution Monitor Module

Tracks task execution progress, handles failures, and provides retry logic.
"""

import time
import asyncio
from typing import Dict, Any, Optional, List, Callable
from dataclasses import dataclass, field
from enum import Enum
from collections import defaultdict


class ExecutionStatus(Enum):
    """Status of an execution"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


class FailureType(Enum):
    """Type of failure"""
    NONE = "none"
    TOOL_ERROR = "tool_error"
    TIMEOUT = "timeout"
    RATE_LIMIT = "rate_limit"
    AUTH_ERROR = "auth_error"
    VALIDATION_ERROR = "validation_error"
    UNKNOWN = "unknown"


@dataclass
class ExecutionStep:
    """A single step in task execution"""
    id: str
    name: str
    status: ExecutionStatus = ExecutionStatus.PENDING
    start_time: float = 0
    end_time: float = 0
    duration: float = 0
    result: Any = None
    error: str = ""
    failure_type: FailureType = FailureType.NONE
    retry_count: int = 0
    max_retries: int = 3

    def start(self) -> None:
        self.status = ExecutionStatus.RUNNING
        self.start_time = time.time()

    def complete(self, result: Any = None) -> None:
        self.status = ExecutionStatus.COMPLETED
        self.end_time = time.time()
        self.duration = self.end_time - self.start_time
        self.result = result

    def fail(self, error: str, failure_type: FailureType = FailureType.UNKNOWN) -> None:
        self.status = ExecutionStatus.FAILED
        self.end_time = time.time()
        self.duration = self.end_time - self.start_time
        self.error = error
        self.failure_type = failure_type

    def retry(self) -> bool:
        """Attempt a retry. Returns True if retry is allowed."""
        if self.retry_count < self.max_retries:
            self.retry_count += 1
            self.status = ExecutionStatus.RETRYING
            self.error = ""
            return True
        return False

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "status": self.status.value,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration": self.duration,
            "result": str(self.result)[:200] if self.result else None,
            "error": self.error[:200] if self.error else None,
            "failure_type": self.failure_type.value,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
        }


@dataclass
class ExecutionRecord:
    """Record of a complete task execution"""
    task_id: str
    task_name: str
    status: ExecutionStatus = ExecutionStatus.PENDING
    steps: List[ExecutionStep] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    started_at: float = 0
    completed_at: float = 0
    total_duration: float = 0

    # Metrics
    total_retries: int = 0
    tool_calls: int = 0
    tool_errors: int = 0

    # Context
    user_prompt: str = ""
    final_result: Any = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def start(self) -> None:
        self.status = ExecutionStatus.RUNNING
        self.started_at = time.time()

    def complete(self, result: Any = None) -> None:
        self.status = ExecutionStatus.COMPLETED
        self.completed_at = time.time()
        self.total_duration = self.completed_at - self.started_at
        self.final_result = result

    def fail(self, reason: str = "") -> None:
        self.status = ExecutionStatus.FAILED
        self.completed_at = time.time()
        self.total_duration = self.completed_at - self.started_at
        if reason:
            self.metadata["failure_reason"] = reason

    def add_step(self, step: ExecutionStep) -> None:
        self.steps.append(step)

    def get_step(self, step_id: str) -> Optional[ExecutionStep]:
        for step in self.steps:
            if step.id == step_id:
                return step
        return None

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "task_name": self.task_name,
            "status": self.status.value,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "total_duration": self.total_duration,
            "total_retries": self.total_retries,
            "tool_calls": self.tool_calls,
            "tool_errors": self.tool_errors,
            "steps": [s.to_dict() for s in self.steps],
            "user_prompt": self.user_prompt,
            "final_result": str(self.final_result)[:200] if self.final_result else None,
            "metadata": self.metadata,
        }


class ExecutionMonitor:
    """Monitors task execution and handles failure recovery

    Tracks:
    - Execution progress through steps
    - Tool call counts and errors
    - Retry attempts
    - Timeout handling
    - Success/failure metrics
    """

    def __init__(
        self,
        max_retries: int = 3,
        retry_delay: float = 1.0,
        timeout: float = 300.0,
    ):
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.timeout = timeout

        # Execution records
        self._executions: Dict[str, ExecutionRecord] = {}
        self._current_execution: Optional[ExecutionRecord] = None

        # Metrics
        self._total_executions: int = 0
        self._successful_executions: int = 0
        self._failed_executions: int = 0
        self._total_tool_calls: int = 0
        self._total_tool_errors: int = 0

        # Callbacks
        self._on_step_complete: Optional[Callable] = None
        self._on_step_fail: Optional[Callable] = None
        self._on_execution_complete: Optional[Callable] = None
        self._on_execution_fail: Optional[Callable] = None

    def start_execution(self, task_id: str, task_name: str, user_prompt: str = "") -> ExecutionRecord:
        """Start tracking a new execution"""
        record = ExecutionRecord(
            task_id=task_id,
            task_name=task_name,
            user_prompt=user_prompt,
        )
        record.start()
        self._executions[task_id] = record
        self._current_execution = record
        self._total_executions += 1

        print(f"[DEBUG monitor] 开始执行: task_id={task_id}, task_name={task_name}")
        return record

    def end_execution(self, task_id: str, result: Any = None, success: bool = True) -> None:
        """End tracking an execution"""
        record = self._executions.get(task_id)
        if not record:
            return

        if success:
            record.complete(result)
            self._successful_executions += 1
            print(f"[DEBUG monitor] 执行完成: task_id={task_id}, duration={record.total_duration:.2f}s")
            if self._on_execution_complete:
                self._on_execution_complete(record)
        else:
            record.fail()
            self._failed_executions += 1
            print(f"[DEBUG monitor] 执行失败: task_id={task_id}")
            if self._on_execution_fail:
                self._on_execution_fail(record)

        if self._current_execution and self._current_execution.task_id == task_id:
            self._current_execution = None

    def start_step(self, step_id: str, step_name: str) -> ExecutionStep:
        """Start a new step in the current execution"""
        if not self._current_execution:
            # Create a default record if no execution is active
            record = self.start_execution("default", step_name)
            record.task_id = step_id

        step = ExecutionStep(
            id=step_id,
            name=step_name,
            max_retries=self.max_retries,
        )
        step.start()
        self._current_execution.add_step(step)

        print(f"[DEBUG monitor] 开始步骤: step_id={step_id}, step_name={step_name}")
        return step

    def complete_step(self, step_id: str, result: Any = None) -> None:
        """Mark a step as completed"""
        if not self._current_execution:
            return

        step = self._current_execution.get_step(step_id)
        if step:
            step.complete(result)
            print(f"[DEBUG monitor] 步骤完成: step_id={step_id}, duration={step.duration:.2f}s")

            if self._on_step_complete:
                self._on_step_complete(step)

    def fail_step(
        self,
        step_id: str,
        error: str,
        failure_type: FailureType = FailureType.UNKNOWN,
    ) -> bool:
        """Mark a step as failed. Returns True if retry is allowed."""
        if not self._current_execution:
            return False

        step = self._current_execution.get_step(step_id)
        if not step:
            return False

        step.fail(error, failure_type)
        self._current_execution.tool_errors += 1
        self._total_tool_errors += 1

        print(f"[DEBUG monitor] 步骤失败: step_id={step_id}, error={error[:100]}, failure_type={failure_type.value}")

        if self._on_step_fail:
            self._on_step_fail(step)

        # Check if retry is available
        if failure_type in (FailureType.TOOL_ERROR, FailureType.TIMEOUT, FailureType.RATE_LIMIT):
            return step.retry()

        return False

    def record_tool_call(self, tool_name: str, success: bool = True) -> None:
        """Record a tool call"""
        if self._current_execution:
            self._current_execution.tool_calls += 1
        self._total_tool_calls += 1

        if not success:
            self.fail_step(
                f"tool_{tool_name}_{time.time()}",
                f"Tool {tool_name} failed",
                FailureType.TOOL_ERROR,
            )

    def get_current_execution(self) -> Optional[ExecutionRecord]:
        """Get the currently active execution record"""
        return self._current_execution

    def get_execution(self, task_id: str) -> Optional[ExecutionRecord]:
        """Get an execution record by task ID"""
        return self._executions.get(task_id)

    def get_metrics(self) -> dict:
        """Get execution metrics"""
        success_rate = 0.0
        if self._total_executions > 0:
            success_rate = self._successful_executions / self._total_executions

        avg_duration = 0.0
        completed = [r for r in self._executions.values() if r.total_duration > 0]
        if completed:
            avg_duration = sum(r.total_duration for r in completed) / len(completed)

        return {
            "total_executions": self._total_executions,
            "successful_executions": self._successful_executions,
            "failed_executions": self._failed_executions,
            "success_rate": success_rate,
            "total_tool_calls": self._total_tool_calls,
            "total_tool_errors": self._total_tool_errors,
            "average_duration": avg_duration,
            "active_executions": len([
                r for r in self._executions.values()
                if r.status == ExecutionStatus.RUNNING
            ]),
        }

    def should_retry(self, failure_type: FailureType, retry_count: int) -> bool:
        """Determine if a failed operation should be retried"""
        if retry_count >= self.max_retries:
            return False

        # Don't retry auth errors or validation errors
        if failure_type in (FailureType.AUTH_ERROR, FailureType.VALIDATION_ERROR):
            return False

        return True

    def get_retry_delay(self, retry_count: int, failure_type: FailureType) -> float:
        """Calculate retry delay with exponential backoff"""
        if failure_type == FailureType.RATE_LIMIT:
            # Longer delay for rate limits
            return self.retry_delay * (2 ** retry_count) * 2
        return self.retry_delay * (2 ** retry_count)

    # Callback setters
    def on_step_complete(self, callback: Callable) -> None:
        self._on_step_complete = callback

    def on_step_fail(self, callback: Callable) -> None:
        self._on_step_fail = callback

    def on_execution_complete(self, callback: Callable) -> None:
        self._on_execution_complete = callback

    def on_execution_fail(self, callback: Callable) -> None:
        self._on_execution_fail = callback


# Global monitor instance
_monitor: Optional[ExecutionMonitor] = None


def get_monitor() -> ExecutionMonitor:
    """Get the global execution monitor"""
    global _monitor
    if _monitor is None:
        _monitor = ExecutionMonitor()
    return _monitor


def set_monitor(monitor: ExecutionMonitor) -> None:
    """Set the global execution monitor (for testing)"""
    global _monitor
    _monitor = monitor
