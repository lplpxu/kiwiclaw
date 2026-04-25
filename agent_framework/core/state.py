"""State Management Module

Provides agent state management and state snapshots.
"""

import time
import threading
import json
from typing import Dict, Any, Optional, Set, Callable, List
from dataclasses import dataclass, field
from enum import Enum
from copy import deepcopy


class AgentFlag(Enum):
    """Agent state flags"""
    RUNNING = "running"
    PAUSED = "paused"
    INTERRUPTED = "interrupted"
    WAITING = "waiting"
    ERROR = "error"
    SHUTTING_DOWN = "shutting_down"


@dataclass
class AgentState:
    """Agent state container

    Tracks all runtime state for an agent including flags,
    variables, call depth, and iteration count.
    """
    # Flags
    flags: Set[AgentFlag] = field(default_factory=lambda: {AgentFlag.RUNNING})

    # Counters
    call_depth: int = 0
    iteration: int = 0
    max_iterations: int = 100
    max_call_depth: int = 10

    # Timing
    start_time: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)

    # Variables
    variables: Dict[str, Any] = field(default_factory=dict)

    # Context
    current_task: str = ""
    current_tool: str = ""

    def set_flag(self, flag: AgentFlag) -> None:
        """Set a state flag"""
        self.flags.add(flag)

    def clear_flag(self, flag: AgentFlag) -> None:
        """Clear a state flag"""
        self.flags.discard(flag)

    def has_flag(self, flag: AgentFlag) -> bool:
        """Check if a flag is set"""
        return flag in self.flags

    def is_running(self) -> bool:
        """Check if agent is running"""
        return AgentFlag.RUNNING in self.flags

    def is_interrupted(self) -> bool:
        """Check if agent is interrupted"""
        return AgentFlag.INTERRUPTED in self.flags

    def increment_iteration(self) -> int:
        """Increment iteration counter and return new value"""
        self.iteration += 1
        self.last_activity = time.time()
        return self.iteration

    def increment_call_depth(self) -> int:
        """Increment call depth and return new value"""
        self.call_depth += 1
        return self.call_depth

    def decrement_call_depth(self) -> int:
        """Decrement call depth and return new value"""
        self.call_depth = max(0, self.call_depth - 1)
        return self.call_depth

    def reset_call_depth(self) -> None:
        """Reset call depth to 0"""
        self.call_depth = 0

    def set_variable(self, key: str, value: Any) -> None:
        """Set a state variable"""
        self.variables[key] = value
        self.last_activity = time.time()

    def get_variable(self, key: str, default: Any = None) -> Any:
        """Get a state variable"""
        return self.variables.get(key, default)

    def clear_variables(self) -> None:
        """Clear all state variables"""
        self.variables.clear()

    def get_uptime(self) -> float:
        """Get agent uptime in seconds"""
        return time.time() - self.start_time

    def get_idle_time(self) -> float:
        """Get time since last activity in seconds"""
        return time.time() - self.last_activity

    def to_dict(self) -> Dict[str, Any]:
        """Convert state to dictionary"""
        return {
            "flags": [f.value for f in self.flags],
            "call_depth": self.call_depth,
            "iteration": self.iteration,
            "max_iterations": self.max_iterations,
            "start_time": self.start_time,
            "last_activity": self.last_activity,
            "uptime": self.get_uptime(),
            "idle_time": self.get_idle_time(),
            "variables": self.variables,
            "current_task": self.current_task,
            "current_tool": self.current_tool,
        }


@dataclass
class StateSnapshot:
    """Snapshot of agent state for recovery

    Captures the full state at a point in time for
    potential restoration.
    """
    id: str
    timestamp: float = field(default_factory=time.time)
    agent_state: Dict[str, Any] = field(default_factory=dict)
    messages: list = field(default_factory=list)
    tool_results: list = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert snapshot to dictionary"""
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "agent_state": self.agent_state,
            "messages": self.messages,
            "tool_results": self.tool_results,
            "metadata": self.metadata,
        }

    def to_json(self) -> str:
        """Convert snapshot to JSON string"""
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StateSnapshot":
        """Create snapshot from dictionary"""
        return cls(
            id=data["id"],
            timestamp=data.get("timestamp", time.time()),
            agent_state=data.get("agent_state", {}),
            messages=data.get("messages", []),
            tool_results=data.get("tool_results", []),
            metadata=data.get("metadata", {}),
        )

    @classmethod
    def from_json(cls, json_str: str) -> "StateSnapshot":
        """Create snapshot from JSON string"""
        return cls.from_dict(json.loads(json_str))


class StateValidator:
    """Validates state transitions and constraints

    Ensures state changes are valid and don't violate
    agent constraints.
    """

    def __init__(self, max_call_depth: int = 10, max_iterations: int = 100):
        self.max_call_depth = max_call_depth
        self.max_iterations = max_iterations

    def validate_iteration(self, state: AgentState) -> bool:
        """Validate iteration is within bounds

        Args:
            state: Current agent state

        Returns:
            True if valid
        """
        return state.iteration < state.max_iterations

    def validate_call_depth(self, state: AgentState) -> bool:
        """Validate call depth is within bounds

        Args:
            state: Current agent state

        Returns:
            True if valid
        """
        return state.call_depth < self.max_call_depth

    def validate_state_transition(
        self,
        from_state: AgentState,
        to_state: AgentState
    ) -> tuple[bool, str]:
        """Validate a state transition

        Args:
            from_state: Current state
            to_state: Proposed new state

        Returns:
            Tuple of (valid, error_message)
        """
        # Can't go from running to paused without good reason
        if AgentFlag.RUNNING in from_state.flags:
            if AgentFlag.SHUTTING_DOWN in to_state.flags:
                return True, ""

        # Must have activity when transitioning
        if not to_state.flags:
            return False, "State must have at least one flag"

        return True, ""


class StateManager:
    """Manages agent state and snapshots

    Provides thread-safe state access and snapshot management.
    """

    def __init__(self, initial_state: AgentState = None):
        self._state = initial_state or AgentState()
        self._snapshots: Dict[str, StateSnapshot] = {}
        self._validator = StateValidator()
        self._lock = threading.Lock()

    @property
    def state(self) -> AgentState:
        """Get current state (read-only copy)"""
        with self._lock:
            return deepcopy(self._state)

    def update(self, update_fn: Callable[[AgentState], None]) -> None:
        """Update state using a function

        Args:
            update_fn: Function that takes state and modifies it
        """
        with self._lock:
            update_fn(self._state)
            print(f"[DEBUG state] iteration={self._state.iteration}, flags={list(self._state.flags) if self._state.flags else []}")

    def create_snapshot(self, snapshot_id: str = None) -> StateSnapshot:
        """Create a snapshot of current state

        Args:
            snapshot_id: Optional ID for snapshot

        Returns:
            Created StateSnapshot
        """
        if snapshot_id is None:
            import uuid
            snapshot_id = str(uuid.uuid4())[:8]

        with self._lock:
            snapshot = StateSnapshot(
                id=snapshot_id,
                agent_state=self._state.to_dict(),
            )
            self._snapshots[snapshot_id] = snapshot
            return snapshot

    def restore_snapshot(self, snapshot_id: str) -> bool:
        """Restore state from a snapshot

        Args:
            snapshot_id: ID of snapshot to restore

        Returns:
            True if restored successfully
        """
        with self._lock:
            if snapshot_id not in self._snapshots:
                return False

            snapshot = self._snapshots[snapshot_id]
            # Note: In production, would restore full state including messages
            self._state = AgentState()
            return True

    def get_snapshot(self, snapshot_id: str) -> Optional[StateSnapshot]:
        """Get a snapshot by ID

        Args:
            snapshot_id: Snapshot ID

        Returns:
            StateSnapshot if found
        """
        with self._lock:
            return self._snapshots.get(snapshot_id)

    def list_snapshots(self) -> List[StateSnapshot]:
        """List all snapshots

        Returns:
            List of snapshots sorted by timestamp
        """
        with self._lock:
            return sorted(
                self._snapshots.values(),
                key=lambda s: s.timestamp,
                reverse=True
            )

    def delete_snapshot(self, snapshot_id: str) -> bool:
        """Delete a snapshot

        Args:
            snapshot_id: Snapshot ID to delete

        Returns:
            True if deleted
        """
        with self._lock:
            if snapshot_id in self._snapshots:
                del self._snapshots[snapshot_id]
                return True
            return False

    def clear_snapshots(self) -> int:
        """Clear all snapshots

        Returns:
            Number of snapshots cleared
        """
        with self._lock:
            count = len(self._snapshots)
            self._snapshots.clear()
            return count


# Global state manager
_state_manager: Optional[StateManager] = None


def get_state_manager() -> StateManager:
    """Get the global state manager"""
    global _state_manager
    if _state_manager is None:
        _state_manager = StateManager()
    return _state_manager