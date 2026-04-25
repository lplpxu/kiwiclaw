"""ACP Server Implementation

ACP server that wraps AIAgent to expose it via the Agent Client Protocol.
Inspired by hermes-agent/acp_adapter/server.py HermesACPAgent
"""

import asyncio
import json
import time
from typing import Optional, Dict, Any, Callable, List
from dataclasses import dataclass

from .session import SessionManager, SessionConfig, ACPSession, SessionState
from .events import ACPEventBus, EventType, ACPEvent
from .permissions import PermissionPolicy, PermissionMode, PermissionEnforcer


@dataclass
class ACPCapabilities:
    """Capabilities advertised by the ACP server"""
    session_resume: bool = True
    session_fork: bool = True
    session_list: bool = True
    model_switch: bool = True
    tools: bool = True
    streaming: bool = True
    slash_commands: bool = True


@dataclass
class ACPromptRequest:
    """Request to prompt the agent"""
    session_id: str
    message: str
    model: str = None
    system_prompt: str = None
    stream: bool = True


@dataclass
class ACPromptResponse:
    """Response from a prompt request"""
    session_id: str
    content: str
    done: bool
    usage: Dict[str, Any] = None
    error: str = None


class ACPServer:
    """ACP Server implementation

    Wraps an AIAgent to expose it via the Agent Client Protocol,
    handling session lifecycle, prompt execution, and event streaming.
    """

    def __init__(
        self,
        agent,  # AIAgent instance
        session_manager: SessionManager = None,
        event_bus: ACPEventBus = None,
    ):
        self.agent = agent
        self.session_manager = session_manager or SessionManager()
        self.event_bus = event_bus or ACPEventBus()

        # Default capabilities
        self.capabilities = ACPCapabilities()

        # Permission policy
        self.permission_policy = PermissionPolicy(mode=PermissionMode.PROMPT)
        self.permission_enforcer = PermissionEnforcer(self.permission_policy)

        # Slash commands handler
        self._slash_commands = {
            "/help": self._handle_help,
            "/model": self._handle_model,
            "/tools": self._handle_tools,
            "/context": self._handle_context,
            "/reset": self._handle_reset,
            "/compact": self._handle_compact,
            "/version": self._handle_version,
        }

    # === Server Lifecycle ===

    async def initialize(self) -> Dict[str, Any]:
        """Initialize the server and return capabilities"""
        return {
            "capabilities": self.capabilities.__dict__,
            "version": "1.0.0",
            "server_time": time.time(),
        }

    async def shutdown(self) -> None:
        """Shutdown the server gracefully"""
        # Save all sessions
        for session in self.session_manager._sessions.values():
            self.session_manager.save_session(session)

    # === Session Lifecycle ===

    async def new_session(
        self,
        config: SessionConfig = None,
        session_id: str = None
    ) -> Dict[str, Any]:
        """Create a new session"""
        session = self.session_manager.create_session(session_id, config)
        return {
            "session_id": session.session_id,
            "state": session.state.value,
            "model": session.model,
            "created_at": session.created_at,
        }

    async def load_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Load an existing session"""
        session = self.session_manager.get_session(session_id)
        if not session:
            return None

        return {
            "session_id": session.session_id,
            "state": session.state.value,
            "model": session.model,
            "message_count": len(session.messages),
            "updated_at": session.updated_at,
        }

    async def resume_session(
        self,
        session_id: str,
        additional_context: str = None
    ) -> Optional[str]:
        """Resume a session with additional context"""
        session = self.session_manager.get_session(session_id)
        if not session:
            return None

        if additional_context:
            session.add_user_message(f"[Resumed with context]\n{additional_context}")

        return session.session_id

    async def fork_session(
        self,
        session_id: str,
        new_session_id: str = None
    ) -> Optional[Dict[str, Any]]:
        """Fork an existing session"""
        forked = self.session_manager.fork_session(session_id, new_session_id)
        if not forked:
            return None

        return {
            "session_id": forked.session_id,
            "parent_session_id": session_id,
            "state": forked.state.value,
            "message_count": len(forked.messages),
        }

    async def cancel_session(self, session_id: str) -> bool:
        """Cancel a running session"""
        session = self.session_manager.get_session(session_id)
        if not session:
            return False

        session.state = SessionState.CANCELLED
        self.session_manager.save_session(session)

        # Emit cancellation event
        self.event_bus.publish(ACPEvent(
            type=EventType.SESSION_CANCELLED,
            session_id=session_id,
            data={}
        ))

        return True

    async def list_sessions(
        self,
        limit: int = 50,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """List all sessions"""
        return self.session_manager.list_sessions(limit, offset)

    async def set_session_model(
        self,
        session_id: str,
        model: str
    ) -> bool:
        """Switch the model for a session"""
        session = self.session_manager.get_session(session_id)
        if not session:
            return False

        session.model = model
        self.session_manager.save_session(session)
        return True

    # === Prompt Execution ===

    async def prompt(self, request: ACPromptRequest) -> ACPromptResponse:
        """Execute a prompt in a session"""
        # Get or create session
        session = self.session_manager.get_session(request.session_id)
        if not session:
            return ACPromptResponse(
                session_id=request.session_id,
                content="",
                done=False,
                error=f"Session {request.session_id} not found"
            )

        # Check if session is running
        if session.state != SessionState.RUNNING:
            return ACPromptResponse(
                session_id=request.session_id,
                content="",
                done=False,
                error=f"Session is in state {session.state.value}"
            )

        # Handle slash commands locally
        if request.message.startswith("/"):
            return await self._handle_slash_command(session, request.message)

        # Add user message to session
        session.add_user_message(request.message)

        try:
            # Run the agent
            result = await self._run_agent(session, request)

            # Save session after prompt
            self.session_manager.save_session(session)

            return result

        except Exception as e:
            return ACPromptResponse(
                session_id=request.session_id,
                content="",
                done=False,
                error=str(e)
            )

    async def _run_agent(
        self,
        session: ACPSession,
        request: ACPromptRequest
    ) -> ACPromptResponse:
        """Run the agent for a session"""
        # Create event callbacks for this run
        from .events import make_tool_progress_cb, make_thinking_cb, make_message_cb

        tool_cb = make_tool_progress_cb(session.session_id, "", "")
        thinking_cb = make_thinking_cb(session.session_id)
        message_cb = make_message_cb(session.session_id)

        # Build messages for agent
        messages = [
            {"role": m.type, "content": m.content}
            for m in session.messages
        ]

        # Run agent's think method
        response_text = await self.agent.think(
            request.message,
            status_callback=None  # Could add progress callbacks here
        )

        # Add assistant response to session
        session.add_assistant_message(response_text)

        return ACPromptResponse(
            session_id=session.session_id,
            content=response_text,
            done=True,
            usage={}  # Could track token usage here
        )

    async def _handle_slash_command(
        self,
        session: ACPSession,
        command: str
    ) -> ACPromptResponse:
        """Handle a slash command locally (without LLM)"""
        parts = command.split(maxsplit=1)
        cmd = parts[0]
        arg = parts[1] if len(parts) > 1 else ""

        handler = self._slash_commands.get(cmd)
        if not handler:
            return ACPromptResponse(
                session_id=session.session_id,
                content=f"Unknown command: {cmd}\nKnown commands: {', '.join(self._slash_commands.keys())}",
                done=True
            )

        try:
            result = await handler(session, arg)
            return ACPromptResponse(
                session_id=session.session_id,
                content=result,
                done=True
            )
        except Exception as e:
            return ACPromptResponse(
                session_id=session.session_id,
                content=f"Error executing {cmd}: {str(e)}",
                done=True,
                error=str(e)
            )

    # === Slash Command Handlers ===

    async def _handle_help(self, session: ACPSession, arg: str) -> str:
        """Handle /help command"""
        return """Available commands:
/help - Show this help
/model <model> - Switch model
/tools - List available tools
/context - Show context status
/reset - Reset conversation
/compact - Manually trigger compression
/version - Show version"""

    async def _handle_model(self, session: ACPSession, arg: str) -> str:
        """Handle /model command"""
        if arg:
            session.model = arg
            return f"Model switched to {arg}"
        return f"Current model: {session.model}"

    async def _handle_tools(self, session: ACPSession, arg: str) -> str:
        """Handle /tools command"""
        tools = self.agent._tools
        tool_list = "\n".join(f"- {t['name']}: {t['description']}" for t in tools)
        return f"Available tools:\n{tool_list}"

    async def _handle_context(self, session: ACPSession, arg: str) -> str:
        """Handle /context command"""
        from ..core._managers import estimate_tokens
        tokens = estimate_tokens([{"role": m.type, "content": m.content} for m in session.messages])
        return f"Messages: {len(session.messages)}\nEstimated tokens: {tokens}"

    async def _handle_reset(self, session: ACPSession, arg: str) -> str:
        """Handle /reset command"""
        session.messages.clear()
        return "Conversation reset"

    async def _handle_compact(self, session: ACPSession, arg: str) -> str:
        """Handle /compact command"""
        from ..core._managers import auto_compact
        from ..core import client, MODEL
        old_count = len(session.messages)
        session.messages[:] = auto_compact(
            [{"role": m.type, "content": m.content} for m in session.messages],
            client,
            session.model
        )
        new_count = len(session.messages)
        return f"Compacted from {old_count} to {new_count} messages"

    async def _handle_version(self, session: ACPSession, arg: str) -> str:
        """Handle /version command"""
        return "Agent Framework ACP Server v1.0.0"

    # === Permission Handling ===

    def set_permission_mode(self, mode: PermissionMode) -> None:
        """Set the global permission mode"""
        self.permission_policy.set_mode(mode)

    def allow_tool(self, tool_name: str) -> None:
        """Always allow a specific tool"""
        from .permissions import ToolPermissionMapper
        action = ToolPermissionMapper.get_action(tool_name)
        self.permission_policy.allow_always(action)

    def deny_tool(self, tool_name: str) -> None:
        """Always deny a specific tool"""
        from .permissions import ToolPermissionMapper
        action = ToolPermissionMapper.get_action(tool_name)
        self.permission_policy.deny_always(action)


class ACPClient:
    """ACP Client for connecting to an ACP server"""

    def __init__(self, server_url: str):
        self.server_url = server_url
        self._session_id: Optional[str] = None

    async def connect(self) -> Dict[str, Any]:
        """Connect to the server and get capabilities"""
        # In a real implementation, this would make an HTTP request
        # For now, return a mock response
        return {
            "capabilities": {
                "session_resume": True,
                "session_fork": True,
                "session_list": True,
            },
            "version": "1.0.0",
        }

    async def create_session(self, config: SessionConfig = None) -> str:
        """Create a new session"""
        # Mock implementation
        import uuid
        self._session_id = str(uuid.uuid4())
        return self._session_id

    async def prompt(
        self,
        message: str,
        stream: bool = True
    ) -> ACPromptResponse:
        """Send a prompt to the server"""
        if not self._session_id:
            raise RuntimeError("Not connected. Call create_session first.")

        # Mock implementation
        return ACPromptResponse(
            session_id=self._session_id,
            content=f"Mock response to: {message[:50]}...",
            done=True
        )

    async def fork_session(self) -> Optional[str]:
        """Fork the current session"""
        if not self._session_id:
            return None

        import uuid
        return str(uuid.uuid4())

    async def cancel(self) -> bool:
        """Cancel the current session"""
        # Mock implementation
        return True
