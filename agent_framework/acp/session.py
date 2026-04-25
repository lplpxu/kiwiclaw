"""ACP Session Management

Handles ACP session lifecycle: create, load, resume, fork, cancel.
Inspired by hermes-agent/acp_adapter/session.py
[PHASE3] ACP协议 - ACPSession
"""

import json
import time
import sqlite3
from pathlib import Path
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from enum import Enum
from threading import Lock
import uuid

# Debug print helper
def _debug(msg: str):
    print(f"[PHASE3] [ACPSession] {msg}")


class SessionState(Enum):
    """Session state enumeration"""
    CREATING = "creating"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class ACPMessage:
    """ACP message structure"""
    id: str
    type: str  # user, assistant, tool_call, tool_result, system
    content: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    attachments: List[Dict[str, Any]] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type,
            "content": self.content,
            "metadata": self.metadata,
            "attachments": self.attachments,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ACPMessage":
        return cls(
            id=data["id"],
            type=data["type"],
            content=data["content"],
            metadata=data.get("metadata", {}),
            attachments=data.get("attachments", []),
            timestamp=data.get("timestamp", time.time()),
        )


@dataclass
class SessionConfig:
    """Configuration for an ACP session"""
    model: str = "claude-sonnet-4-20250514"
    temperature: float = 1.0
    max_tokens: int = 8000
    system_prompt: str = ""
    tools_enabled: bool = True
    sandbox_enabled: bool = False


class ACPSession:
    """Represents a single ACP session"""

    def __init__(self, session_id: str, config: SessionConfig = None):
        self.session_id = session_id
        self.config = config or SessionConfig()
        self.state = SessionState.CREATING
        self.messages: List[ACPMessage] = []
        self.created_at = time.time()
        self.updated_at = time.time()
        self.model = self.config.model
        self._lock = Lock()

    def add_message(self, msg: ACPMessage) -> None:
        """Add a message to the session"""
        with self._lock:
            self.messages.append(msg)
            self.updated_at = time.time()

    def add_user_message(self, content: str, metadata: dict = None) -> ACPMessage:
        """Add a user message"""
        msg = ACPMessage(
            id=str(uuid.uuid4()),
            type="user",
            content=content,
            metadata=metadata or {},
        )
        self.add_message(msg)
        return msg

    def add_assistant_message(self, content: str, metadata: dict = None) -> ACPMessage:
        """Add an assistant message"""
        msg = ACPMessage(
            id=str(uuid.uuid4()),
            type="assistant",
            content=content,
            metadata=metadata or {},
        )
        self.add_message(msg)
        return msg

    def add_tool_message(self, tool_name: str, tool_input: str, tool_output: str,
                         tool_id: str = None, is_error: bool = False) -> ACPMessage:
        """Add a tool result message"""
        metadata = {
            "tool_name": tool_name,
            "tool_input": tool_input,
            "is_error": is_error,
        }
        if tool_id:
            metadata["tool_id"] = tool_id

        msg = ACPMessage(
            id=str(uuid.uuid4()),
            type="tool_result",
            content=tool_output,
            metadata=metadata,
        )
        self.add_message(msg)
        return msg

    def fork(self, new_session_id: str = None) -> "ACPSession":
        """Create a fork of this session with a new ID"""
        new_id = new_session_id or str(uuid.uuid4())
        forked = ACPSession(new_id, self.config)
        forked.messages = self.messages.copy()
        forked.state = self.state
        forked.model = self.model
        return forked

    def to_dict(self) -> dict:
        """Serialize session to dict"""
        return {
            "session_id": self.session_id,
            "config": {
                "model": self.config.model,
                "temperature": self.config.temperature,
                "max_tokens": self.config.max_tokens,
                "system_prompt": self.config.system_prompt,
                "tools_enabled": self.config.tools_enabled,
                "sandbox_enabled": self.config.sandbox_enabled,
            },
            "state": self.state.value,
            "messages": [m.to_dict() for m in self.messages],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "model": self.model,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ACPSession":
        """Deserialize session from dict"""
        config = SessionConfig(**data["config"])
        session = cls(data["session_id"], config)
        session.state = SessionState(data["state"])
        session.messages = [ACPMessage.from_dict(m) for m in data["messages"]]
        session.created_at = data["created_at"]
        session.updated_at = data["updated_at"]
        session.model = data.get("model", config.model)
        return session


class SessionManager:
    """Manages ACP sessions with in-memory and persistent storage

    Sessions are stored in memory and persisted to SQLite for durability.
    Inspired by hermes-agent/acp_adapter/session.py SessionManager
    """

    def __init__(self, db_path: str = None):
        if db_path is None:
            db_path = str(Path.home() / ".agent_framework" / "sessions.db")

        self.db_path = db_path
        self._sessions: Dict[str, ACPSession] = {}
        self._lock = Lock()

        # Ensure directory exists
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        # Initialize database
        self._init_db()

    def _init_db(self) -> None:
        """Initialize SQLite database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                data TEXT NOT NULL,
                updated_at REAL NOT NULL
            )
        """)
        conn.commit()
        conn.close()

    def create_session(self, session_id: str = None, config: SessionConfig = None) -> ACPSession:
        """Create a new session"""
        sid = session_id or str(uuid.uuid4())

        with self._lock:
            if sid in self._sessions:
                raise ValueError(f"Session {sid} already exists")

            session = ACPSession(sid, config)
            session.state = SessionState.RUNNING
            self._sessions[sid] = session
            self._persist_session(session)

        return session

    def get_session(self, session_id: str) -> Optional[ACPSession]:
        """Get a session by ID, loading from DB if not in memory"""
        with self._lock:
            if session_id in self._sessions:
                return self._sessions[session_id]

            # Try to load from database
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT data FROM sessions WHERE session_id = ?",
                (session_id,)
            )
            row = cursor.fetchone()
            conn.close()

            if row:
                data = json.loads(row[0])
                session = ACPSession.from_dict(data)
                self._sessions[session_id] = session
                return session

            return None

    def save_session(self, session: ACPSession) -> None:
        """Persist session to database"""
        with self._lock:
            self._persist_session(session)

    def _persist_session(self, session: ACPSession) -> None:
        """Internal persist method"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO sessions (session_id, data, updated_at) VALUES (?, ?, ?)",
            (session.session_id, json.dumps(session.to_dict()), time.time())
        )
        conn.commit()
        conn.close()

    def delete_session(self, session_id: str) -> bool:
        """Delete a session"""
        with self._lock:
            if session_id in self._sessions:
                del self._sessions[session_id]

            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
            deleted = cursor.rowcount > 0
            conn.commit()
            conn.close()

            return deleted

    def list_sessions(self, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
        """List all sessions"""
        # First get in-memory sessions
        in_memory = [
            {"session_id": sid, "state": s.state.value, "updated_at": s.updated_at}
            for sid, s in self._sessions.items()
        ]

        # Then get from database
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT session_id, data, updated_at FROM sessions ORDER BY updated_at DESC LIMIT ? OFFSET ?",
            (limit, offset)
        )
        rows = cursor.fetchall()
        conn.close()

        db_sessions = []
        for row in rows:
            try:
                data = json.loads(row[1])
                db_sessions.append({
                    "session_id": row[0],
                    "state": data.get("state", "unknown"),
                    "updated_at": row[2],
                })
            except:
                db_sessions.append({
                    "session_id": row[0],
                    "state": "unknown",
                    "updated_at": row[2],
                })

        # Merge in-memory and DB sessions, preferring in-memory
        all_sessions = {s["session_id"]: s for s in db_sessions}
        all_sessions.update({s["session_id"]: s for s in in_memory})

        # Sort by updated_at descending
        sorted_sessions = sorted(
            all_sessions.values(),
            key=lambda x: x["updated_at"],
            reverse=True
        )

        return sorted_sessions[:limit]

    def fork_session(self, session_id: str, new_session_id: str = None) -> Optional[ACPSession]:
        """Fork an existing session"""
        original = self.get_session(session_id)
        if not original:
            return None

        forked = original.fork(new_session_id)
        with self._lock:
            self._sessions[forked.session_id] = forked
            self._persist_session(forked)

        return forked
