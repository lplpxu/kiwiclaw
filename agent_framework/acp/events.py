"""ACP Event System

Event types and callback factories for ACP session updates.
Inspired by hermes-agent/acp_adapter/events.py
"""

import time
from typing import Callable, Optional, Dict, Any, List
from enum import Enum
from dataclasses import dataclass, field


class EventType(Enum):
    """ACP event types"""
    # Session events
    SESSION_STARTED = "session_started"
    SESSION_ENDED = "session_ended"
    SESSION_FORKED = "session_forked"
    SESSION_CANCELLED = "session_cancelled"

    # Message events
    MESSAGE_START = "message_start"
    MESSAGE_DELTA = "message_delta"
    MESSAGE_COMPLETE = "message_complete"

    # Tool events
    TOOL_CALL_START = "tool_call_start"
    TOOL_CALL_PROGRESS = "tool_call_progress"
    TOOL_CALL_COMPLETE = "tool_call_complete"
    TOOL_CALL_FAILED = "tool_call_failed"

    # Thinking events
    THINKING_START = "thinking_start"
    THINKING_DELTA = "thinking_delta"
    THINKING_COMPLETE = "thinking_complete"

    # Step events
    STEP_COMPLETE = "step_complete"
    STEP_FAILED = "step_failed"

    # Error events
    ERROR = "error"
    TIMEOUT = "timeout"

    # Permission events
    PERMISSION_REQUEST = "permission_request"
    PERMISSION_GRANTED = "permission_granted"
    PERMISSION_DENIED = "permission_denied"


@dataclass
class ACPEvent:
    """Base ACP event structure"""
    type: EventType
    session_id: str
    timestamp: float = field(default_factory=time.time)
    data: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "type": self.type.value,
            "session_id": self.session_id,
            "timestamp": self.timestamp,
            "data": self.data,
        }


@dataclass
class ToolCallStartEvent(ACPEvent):
    """Event fired when a tool call starts"""
    tool_name: str = ""
    tool_input: str = ""
    tool_id: str = ""

    def __init__(self, session_id: str, tool_name: str, tool_input: str, tool_id: str = ""):
        super().__init__(
            type=EventType.TOOL_CALL_START,
            session_id=session_id,
            data={
                "tool_name": tool_name,
                "tool_input": tool_input,
                "tool_id": tool_id,
            }
        )
        self.tool_name = tool_name
        self.tool_input = tool_input
        self.tool_id = tool_id


@dataclass
class ToolCallProgressEvent(ACPEvent):
    """Event fired during tool execution progress"""
    tool_name: str = ""
    tool_output: str = ""
    tool_id: str = ""
    is_complete: bool = False

    def __init__(self, session_id: str, tool_name: str, tool_output: str,
                 tool_id: str = "", is_complete: bool = False):
        super().__init__(
            type=EventType.TOOL_CALL_PROGRESS,
            session_id=session_id,
            data={
                "tool_name": tool_name,
                "tool_output": tool_output,
                "tool_id": tool_id,
                "is_complete": is_complete,
            }
        )
        self.tool_name = tool_name
        self.tool_output = tool_output
        self.tool_id = tool_id
        self.is_complete = is_complete


@dataclass
class ToolCallCompleteEvent(ACPEvent):
    """Event fired when a tool call completes"""
    tool_name: str = ""
    tool_output: str = ""
    tool_id: str = ""
    is_error: bool = False

    def __init__(self, session_id: str, tool_name: str, tool_output: str,
                 tool_id: str = "", is_error: bool = False):
        super().__init__(
            type=EventType.TOOL_CALL_COMPLETE,
            session_id=session_id,
            data={
                "tool_name": tool_name,
                "tool_output": tool_output,
                "tool_id": tool_id,
                "is_error": is_error,
            }
        )
        self.tool_name = tool_name
        self.tool_output = tool_output
        self.tool_id = tool_id
        self.is_error = is_error


@dataclass
class ThinkingEvent(ACPEvent):
    """Event fired during agent thinking"""
    thinking: str = ""
    is_complete: bool = False

    def __init__(self, session_id: str, thinking: str, is_complete: bool = False):
        super().__init__(
            type=EventType.THINKING_COMPLETE if is_complete else EventType.THINKING_DELTA,
            session_id=session_id,
            data={"thinking": thinking, "is_complete": is_complete}
        )
        self.thinking = thinking
        self.is_complete = is_complete


@dataclass
class MessageDeltaEvent(ACPEvent):
    """Event fired for message content deltas (streaming)"""
    content: str = ""

    def __init__(self, session_id: str, content: str):
        super().__init__(
            type=EventType.MESSAGE_DELTA,
            session_id=session_id,
            data={"content": content}
        )
        self.content = content


@dataclass
class StepCompleteEvent(ACPEvent):
    """Event fired when a step completes"""
    step_type: str = ""  # "user", "assistant", "tool"
    step_summary: str = ""

    def __init__(self, session_id: str, step_type: str, step_summary: str):
        super().__init__(
            type=EventType.STEP_COMPLETE,
            session_id=session_id,
            data={"step_type": step_type, "step_summary": step_summary}
        )
        self.step_type = step_type
        self.step_summary = step_summary


# Callback types for integration with AIAgent
EventCallback = Callable[[ACPEvent], None]


class EventCallbackFactory:
    """Factory for creating event callbacks that bridge AIAgent callbacks to ACP events"""

    def __init__(self, session_id: str, callbacks: Dict[str, Callable] = None):
        self.session_id = session_id
        self.callbacks = callbacks or {}

    def _emit(self, event: ACPEvent) -> None:
        """Emit an event to registered callbacks"""
        callback = self.callbacks.get(event.type.value)
        if callback:
            callback(event)

    def register_callback(self, event_type: str, callback: EventCallback) -> None:
        """Register a callback for an event type"""
        self.callbacks[event_type] = callback

    def make_tool_progress_cb(self, tool_name: str, tool_id: str = "") -> Callable:
        """Create a callback for tool progress events"""
        def callback(output: str = "", is_complete: bool = False):
            event = ToolCallProgressEvent(
                session_id=self.session_id,
                tool_name=tool_name,
                tool_output=output,
                tool_id=tool_id,
                is_complete=is_complete,
            )
            self._emit(event)
        return callback

    def make_thinking_cb(self) -> Callable:
        """Create a callback for thinking events"""
        def callback(thinking: str = "", is_complete: bool = False):
            event = ThinkingEvent(
                session_id=self.session_id,
                thinking=thinking,
                is_complete=is_complete,
            )
            self._emit(event)
        return callback

    def make_step_cb(self) -> Callable:
        """Create a callback for step completion events"""
        def callback(step_type: str = "", summary: str = ""):
            event = StepCompleteEvent(
                session_id=self.session_id,
                step_type=step_type,
                step_summary=summary,
            )
            self._emit(event)
        return callback

    def make_message_cb(self) -> Callable:
        """Create a callback for message delta events"""
        def callback(content: str = ""):
            event = MessageDeltaEvent(
                session_id=self.session_id,
                content=content,
            )
            self._emit(event)
        return callback


# Standalone callback factories for convenience
def make_tool_progress_cb(session_id: str, tool_name: str, tool_id: str = "") -> Callable:
    """Create a standalone tool progress callback"""
    def callback(output: str = "", is_complete: bool = False):
        event = ToolCallProgressEvent(
            session_id=session_id,
            tool_name=tool_name,
            tool_output=output,
            tool_id=tool_id,
            is_complete=is_complete,
        )
        # In a real implementation, this would emit to an event bus
        print(f"[ACP Event] {event.type.value}: {tool_name} -> {output[:100]}...")
    return callback


def make_thinking_cb(session_id: str) -> Callable:
    """Create a standalone thinking callback"""
    def callback(thinking: str = "", is_complete: bool = False):
        event = ThinkingEvent(
            session_id=session_id,
            thinking=thinking,
            is_complete=is_complete,
        )
        print(f"[ACP Event] {event.type.value}: {thinking[:100]}...")
    return callback


def make_step_cb(session_id: str) -> Callable:
    """Create a standalone step callback"""
    def callback(step_type: str = "", summary: str = ""):
        event = StepCompleteEvent(
            session_id=session_id,
            step_type=step_type,
            step_summary=summary,
        )
        print(f"[ACP Event] {event.type.value}: {step_type} -> {summary[:100]}...")
    return callback


def make_message_cb(session_id: str) -> Callable:
    """Create a standalone message callback"""
    def callback(content: str = ""):
        event = MessageDeltaEvent(
            session_id=session_id,
            content=content,
        )
        print(f"[ACP Event] {event.type.value}: {content[:100]}...")
    return callback


class ACPEventBus:
    """Simple event bus for ACP events"""

    def __init__(self):
        self._subscribers: Dict[str, List[EventCallback]] = {}

    def subscribe(self, event_type: EventType, callback: EventCallback) -> None:
        """Subscribe to an event type"""
        if event_type.value not in self._subscribers:
            self._subscribers[event_type.value] = []
        self._subscribers[event_type.value].append(callback)

    def unsubscribe(self, event_type: EventType, callback: EventCallback) -> None:
        """Unsubscribe from an event type"""
        if event_type.value in self._subscribers:
            self._subscribers[event_type.value].remove(callback)

    def publish(self, event: ACPEvent) -> None:
        """Publish an event to all subscribers"""
        callbacks = self._subscribers.get(event.type.value, [])
        for callback in callbacks:
            try:
                callback(event)
            except Exception as e:
                print(f"[ACPEventBus] Error in callback: {e}")

    def publish_tool_start(self, session_id: str, tool_name: str,
                          tool_input: str, tool_id: str = "") -> None:
        """Publish a tool call start event"""
        event = ToolCallStartEvent(session_id, tool_name, tool_input, tool_id)
        self.publish(event)

    def publish_tool_complete(self, session_id: str, tool_name: str,
                             tool_output: str, tool_id: str = "",
                             is_error: bool = False) -> None:
        """Publish a tool call complete event"""
        event = ToolCallCompleteEvent(
            session_id, tool_name, tool_output, tool_id, is_error
        )
        self.publish(event)

    def publish_thinking(self, session_id: str, thinking: str,
                         is_complete: bool = False) -> None:
        """Publish a thinking event"""
        event = ThinkingEvent(session_id, thinking, is_complete)
        self.publish(event)

    def publish_message_delta(self, session_id: str, content: str) -> None:
        """Publish a message delta event"""
        event = MessageDeltaEvent(session_id, content)
        self.publish(event)
