"""Distributed Tracing

Provides OpenTelemetry-style distributed tracing.
"""

import time
import uuid
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from enum import Enum
from contextvars import ContextVar


# Context variable for current span
_current_span: ContextVar[Optional["Span"]] = ContextVar("current_span", default=None)


class SpanKind(Enum):
    """Kind of span"""
    INTERNAL = "internal"
    SERVER = "server"
    CLIENT = "client"
    PRODUCER = "producer"
    CONSUMER = "consumer"


@dataclass
class Span:
    """A trace span

    Represents a unit of work in a distributed trace.
    """
    name: str
    trace_id: str
    span_id: str
    kind: SpanKind = SpanKind.INTERNAL

    # Timing
    start_time: float = field(default_factory=time.time)
    end_time: float = 0
    duration_ms: float = 0

    # Relationships
    parent_span_id: str = ""
    child_span_ids: List[str] = field(default_factory=list)

    # Attributes
    attributes: Dict[str, Any] = field(default_factory=dict)

    # Status
    status: str = "OK"  # OK, ERROR
    error_message: str = ""

    def set_attribute(self, key: str, value: Any) -> None:
        """Set a span attribute"""
        self.attributes[key] = value

    def set_attributes(self, **kwargs) -> None:
        """Set multiple span attributes"""
        self.attributes.update(kwargs)

    def add_event(self, name: str, attributes: Dict[str, Any] = None) -> None:
        """Add an event to the span"""
        event = {
            "name": name,
            "timestamp": time.time(),
            "attributes": attributes or {},
        }
        if "events" not in self.attributes:
            self.attributes["events"] = []
        self.attributes["events"].append(event)

    def record_exception(self, exception: Exception) -> None:
        """Record an exception in the span"""
        self.status = "ERROR"
        self.error_message = str(exception)
        self.attributes["exception.type"] = type(exception).__name__
        self.attributes["exception.message"] = str(exception)

    def finish(self) -> None:
        """Finish the span"""
        self.end_time = time.time()
        self.duration_ms = (self.end_time - self.start_time) * 1000

    def to_dict(self) -> dict:
        """Convert to dictionary"""
        return {
            "name": self.name,
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "kind": self.kind.value,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_ms": self.duration_ms,
            "parent_span_id": self.parent_span_id,
            "child_span_ids": self.child_span_ids,
            "attributes": self.attributes,
            "status": self.status,
            "error_message": self.error_message,
        }


class Tracing:
    """Distributed tracing provider

    Provides span management and context propagation.
    """

    def __init__(self, service_name: str = "agent_framework"):
        self.service_name = service_name
        self._spans: Dict[str, Span] = {}
        self._enabled = True

    def set_enabled(self, enabled: bool) -> None:
        """Enable or disable tracing"""
        self._enabled = enabled

    def start_span(
        self,
        name: str,
        kind: SpanKind = SpanKind.INTERNAL,
        parent_span_id: str = None,
        trace_id: str = None,
        **attributes
    ) -> Span:
        """Start a new span

        Args:
            name: Span name
            kind: Span kind
            parent_span_id: Optional parent span ID
            trace_id: Optional trace ID (generates if not provided)
            **attributes: Initial span attributes

        Returns:
            The created Span
        """
        print(f"[DEBUG tracing] start_span: name={name}, kind={kind.name}, attrs={attributes}")
        if not self._enabled:
            # Return a no-op span
            return Span(
                name=name,
                trace_id=trace_id or "",
                span_id=""
            )

        # Get or create trace ID
        if not trace_id:
            trace_id = self._generate_trace_id()

        # Get parent span ID
        if not parent_span_id:
            current = _current_span.get()
            if current and current.span_id:
                parent_span_id = current.span_id

        # Create span
        span_id = self._generate_span_id()
        span = Span(
            name=name,
            trace_id=trace_id,
            span_id=span_id,
            kind=kind,
            parent_span_id=parent_span_id or "",
        )
        span.set_attributes(**attributes)

        # Store span
        self._spans[span_id] = span

        # Add as child of parent
        if parent_span_id and parent_span_id in self._spans:
            self._spans[parent_span_id].child_span_ids.append(span_id)

        # Set as current span
        _current_span.set(span)

        return span

    def end_span(self, span: Span) -> None:
        """End a span

        Args:
            span: The span to end
        """
        if not span or not span.span_id:
            return

        span.finish()
        self._spans[span.span_id] = span
        print(f"[DEBUG tracing] end_span: name={span.name}, duration={span.duration_ms:.2f}ms")

        # Reset current span
        current = _current_span.get()
        if current and current.span_id == span.span_id:
            _current_span.set(None)

    def get_current_span(self) -> Optional[Span]:
        """Get the current active span"""
        return _current_span.get()

    def get_span(self, span_id: str) -> Optional[Span]:
        """Get a span by ID"""
        return self._spans.get(span_id)

    def get_trace(self, trace_id: str) -> List[Span]:
        """Get all spans for a trace"""
        return [s for s in self._spans.values() if s.trace_id == trace_id]

    def _generate_trace_id(self) -> str:
        """Generate a trace ID"""
        return uuid.uuid4().hex[:16]

    def _generate_span_id(self) -> str:
        """Generate a span ID"""
        return uuid.uuid4().hex[:8]

    def create_span_decorator(
        self,
        name: str = None,
        kind: SpanKind = SpanKind.INTERNAL,
    ):
        """Decorator to automatically trace a function

        Usage:
            @tracing.create_span_decorator("my_function")
            async def my_function():
                ...
        """
        def decorator(func):
            async def async_wrapper(*args, **kwargs):
                span_name = name or func.__name__
                with self.start_span(span_name, kind) as span:
                    try:
                        result = await func(*args, **kwargs)
                        return result
                    except Exception as e:
                        span.record_exception(e)
                        raise

            def sync_wrapper(*args, **kwargs):
                span_name = name or func.__name__
                with self.start_span(span_name, kind) as span:
                    try:
                        result = func(*args, **kwargs)
                        return result
                    except Exception as e:
                        span.record_exception(e)
                        raise

            import asyncio
            if asyncio.iscoroutinefunction(func):
                return async_wrapper
            return sync_wrapper

        return decorator

    def export(self) -> List[dict]:
        """Export all spans as dictionaries

        Returns:
            List of span dictionaries
        """
        return [s.to_dict() for s in self._spans.values() if s.end_time > 0]


# Global tracing instance
_tracing: Optional[Tracing] = None


def get_tracing() -> Tracing:
    """Get the global tracing instance"""
    global _tracing
    if _tracing is None:
        _tracing = Tracing()
    return _tracing


class span_context:
    """Context manager for creating spans

    Usage:
        with tracing.span("my_operation") as span:
            # do work
            span.set_attribute("key", "value")
    """

    def __init__(
        self,
        name: str,
        kind: SpanKind = SpanKind.INTERNAL,
        tracing: Tracing = None,
        **attributes
    ):
        self.name = name
        self.kind = kind
        self.tracing = tracing or get_tracing()
        self.attributes = attributes
        self.span: Optional[Span] = None

    def __enter__(self):
        self.span = self.tracing.start_span(self.name, self.kind, **self.attributes)
        return self.span

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_val and self.span:
            self.span.record_exception(exc_val)
        self.tracing.end_span(self.span)
