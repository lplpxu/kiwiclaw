"""Agent Framework - Modular Agent System"""
__version__ = "0.1.0"

from .core import (
    Agent, AgentConfig, Tool, ToolRegistry,
    TodoManager, TaskManager, BackgroundManager, MessageBus,
    TODO, TASK_MGR, BG, BUS,
    run_bash, run_read, run_write, run_edit,
    microcompact, auto_compact, estimate_tokens,
    DockerSandbox, SandboxConfig,
    MCPServer, MCPClient, AgentRunner,
)
from .config import settings

__all__ = [
    "Agent", "AgentConfig", "Tool", "ToolRegistry",
    "TodoManager", "TaskManager", "BackgroundManager", "MessageBus",
    "TODO", "TASK_MGR", "BG", "BUS",
    "run_bash", "run_read", "run_write", "run_edit",
    "microcompact", "auto_compact", "estimate_tokens",
    "DockerSandbox", "SandboxConfig",
    "MCPServer", "MCPClient", "AgentRunner",
    "settings"
]