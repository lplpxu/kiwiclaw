"""Structured Logger

Provides structured logging for the agent framework.
[PHASE10] 可观测性 - StructuredLogger
"""

import json
import time
import logging
from typing import Any, Dict, Optional
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path

# Debug print helper
def _debug(msg: str):
    print(f"[PHASE10] [StructuredLogger] {msg}")


class LogLevel(Enum):
    """Log levels"""
    DEBUG = 10
    INFO = 20
    WARNING = 30
    ERROR = 40
    CRITICAL = 50


@dataclass
class LogEntry:
    """A structured log entry"""
    timestamp: float
    level: str
    message: str
    logger: str = "agent_framework"

    # Context fields
    session_id: str = ""
    user_id: str = ""
    agent_id: str = ""
    tool_name: str = ""
    task_id: str = ""

    # Additional metadata
    metadata: Dict[str, Any] = field(default_factory=dict)

    # Trace info
    trace_id: str = ""
    span_id: str = ""

    def to_dict(self) -> dict:
        """Convert to dictionary"""
        result = {
            "timestamp": self.timestamp,
            "level": self.level,
            "message": self.message,
            "logger": self.logger,
        }

        # Add context fields if present
        for field in ["session_id", "user_id", "agent_id", "tool_name", "task_id",
                      "trace_id", "span_id"]:
            value = getattr(self, field)
            if value:
                result[field] = value

        if self.metadata:
            result["metadata"] = self.metadata

        return result

    def to_json(self) -> str:
        """Convert to JSON string"""
        return json.dumps(self.to_dict(), default=str)

    @classmethod
    def from_dict(cls, data: dict) -> "LogEntry":
        """Create from dictionary"""
        return cls(
            timestamp=data.get("timestamp", time.time()),
            level=data.get("level", "INFO"),
            message=data.get("message", ""),
            logger=data.get("logger", "agent_framework"),
            session_id=data.get("session_id", ""),
            user_id=data.get("user_id", ""),
            agent_id=data.get("agent_id", ""),
            tool_name=data.get("tool_name", ""),
            task_id=data.get("task_id", ""),
            metadata=data.get("metadata", {}),
            trace_id=data.get("trace_id", ""),
            span_id=data.get("span_id", ""),
        )


class StructuredLogger:
    """Structured logger with multiple output sinks

    Supports:
    - Console output
    - File output (JSON lines)
    - Remote logging (HTTP)
    - Python logging integration
    """

    def __init__(
        self,
        name: str = "agent_framework",
        level: LogLevel = LogLevel.INFO,
        log_dir: Path = None,
        console_output: bool = True,
    ):
        self.name = name
        self.level = level
        self.log_dir = log_dir
        self.console_output = console_output

        # Output handlers
        self._handlers: list = []

        # Python logger integration
        self._python_logger = logging.getLogger(name)
        self._python_logger.setLevel(self._level_to_python(level))
        self._python_logger.handlers.clear()

        # File handler
        if log_dir:
            log_dir.mkdir(parents=True, exist_ok=True)
            self._log_file = log_dir / f"{name}_{int(time.time())}.jsonl"
        else:
            self._log_file = None

    def _level_to_python(self, level: LogLevel) -> int:
        """Convert LogLevel to Python logging level"""
        return {
            LogLevel.DEBUG: logging.DEBUG,
            LogLevel.INFO: logging.INFO,
            LogLevel.WARNING: logging.WARNING,
            LogLevel.ERROR: logging.ERROR,
            LogLevel.CRITICAL: logging.CRITICAL,
        }.get(level, logging.INFO)

    def _python_level_to_str(self, level: int) -> str:
        """Convert Python logging level to string"""
        return {
            logging.DEBUG: "DEBUG",
            logging.INFO: "INFO",
            logging.WARNING: "WARNING",
            logging.ERROR: "ERROR",
            logging.CRITICAL: "CRITICAL",
        }.get(level, "INFO")

    def _create_entry(
        self,
        level: LogLevel,
        message: str,
        **kwargs
    ) -> LogEntry:
        """Create a log entry"""
        return LogEntry(
            timestamp=time.time(),
            level=level.value if isinstance(level, LogLevel) else self._python_level_to_str(level),
            message=message,
            logger=self.name,
            **kwargs
        )

    def _write_entry(self, entry: LogEntry) -> None:
        """Write a log entry to all handlers"""
        # Console output
        if self.console_output:
            print(f"[{entry.level}] {entry.message}")

        # Python logger
        python_level = getattr(logging, entry.level, logging.INFO)
        self._python_logger.log(python_level, entry.message)

        # File output
        if self._log_file:
            with open(self._log_file, "a", encoding="utf-8") as f:
                f.write(entry.to_json() + "\n")

    def debug(self, message: str, **kwargs) -> None:
        """Log debug message"""
        if self.level.value <= LogLevel.DEBUG.value:
            entry = self._create_entry(LogLevel.DEBUG, message, **kwargs)
            self._write_entry(entry)

    def info(self, message: str, **kwargs) -> None:
        """Log info message"""
        if self.level.value <= LogLevel.INFO.value:
            entry = self._create_entry(LogLevel.INFO, message, **kwargs)
            self._write_entry(entry)

    def warning(self, message: str, **kwargs) -> None:
        """Log warning message"""
        if self.level.value <= LogLevel.WARNING.value:
            entry = self._create_entry(LogLevel.WARNING, message, **kwargs)
            self._write_entry(entry)

    def error(self, message: str, **kwargs) -> None:
        """Log error message"""
        if self.level.value <= LogLevel.ERROR.value:
            entry = self._create_entry(LogLevel.ERROR, message, **kwargs)
            self._write_entry(entry)

    def critical(self, message: str, **kwargs) -> None:
        """Log critical message"""
        entry = self._create_entry(LogLevel.CRITICAL, message, **kwargs)
        self._write_entry(entry)

    # Context managers for scoped logging
    def context(self, **kwargs) -> "LogContext":
        """Create a logging context"""
        return LogContext(self, kwargs)

    def task(self, task_id: str, task_name: str = "") -> "LogContext":
        """Create a task-scoped logger"""
        return self.context(task_id=task_id, task_name=task_name)

    def agent(self, agent_id: str, session_id: str = "") -> "LogContext":
        """Create an agent-scoped logger"""
        return self.context(agent_id=agent_id, session_id=session_id)

    def tool(self, tool_name: str, task_id: str = "") -> "LogContext":
        """Create a tool-scoped logger"""
        return self.context(tool_name=tool_name, task_id=task_id)


class LogContext:
    """Context manager for scoped logging"""

    def __init__(self, logger: StructuredLogger, context: dict):
        self.logger = logger
        self.context = context
        self._old_level: Optional[LogLevel] = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    def debug(self, message: str, **kwargs):
        kwargs.update(self.context)
        self.logger.debug(message, **kwargs)

    def info(self, message: str, **kwargs):
        kwargs.update(self.context)
        self.logger.info(message, **kwargs)

    def warning(self, message: str, **kwargs):
        kwargs.update(self.context)
        self.logger.warning(message, **kwargs)

    def error(self, message: str, **kwargs):
        kwargs.update(self.context)
        self.logger.error(message, **kwargs)


# Default logger instance
_default_logger: Optional[StructuredLogger] = None


def get_logger(name: str = "agent_framework") -> StructuredLogger:
    """Get the default logger instance"""
    global _default_logger
    if _default_logger is None:
        _default_logger = StructuredLogger(name=name)
    return _default_logger
