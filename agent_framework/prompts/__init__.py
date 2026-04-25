"""
Agent Framework - Prompts Module

Provides structured prompt system for Agent with分层 architecture:
- Bootstrap prompts (Identity, System Rules, Doing Tasks, Executing Actions)
- Context (Environment, Project)
- Security scanning
- Instruction file discovery
- Harness mode hints
- Permission mode hints

Based on best practices from hermes-agent, openclaw, and claw-code.
"""

from .builder import SystemPromptBuilder
from .context import EnvironmentContext, ProjectContext, get_environment_section, get_project_context_section
from .bootstrap import (
    IDENTITY_SECTION,
    SYSTEM_RULES,
    DOING_TASKS,
    EXECUTING_ACTIONS,
    TOOL_USAGE_STRATEGY,
)
from .modes import HARNESS_MODE_HINTS, get_harness_mode_hint
from .permissions import PERMISSION_MODE_HINTS, get_permission_hint
from ._security import scan_content, CONTEXT_THREAT_PATTERNS
from ._git import get_git_context
from ._discovery import discover_instruction_files, CONTEXT_FILE_PATTERNS

__all__ = [
    # Builder
    "SystemPromptBuilder",
    # Context
    "EnvironmentContext",
    "ProjectContext",
    "get_environment_section",
    "get_project_context_section",
    # Bootstrap
    "IDENTITY_SECTION",
    "SYSTEM_RULES",
    "DOING_TASKS",
    "EXECUTING_ACTIONS",
    # Modes
    "HARNESS_MODE_HINTS",
    "get_harness_mode_hint",
    # Permissions
    "PERMISSION_MODE_HINTS",
    "get_permission_hint",
    # Security
    "scan_content",
    "CONTEXT_THREAT_PATTERNS",
    # Git
    "get_git_context",
    # Discovery
    "discover_instruction_files",
    "CONTEXT_FILE_PATTERNS",
]