"""ACP Permission System

Bridges ACP approval requests to Hermes approval callbacks.
Inspired by hermes-agent/acp_adapter/permissions.py
"""

from enum import Enum
from dataclasses import dataclass
from typing import Callable, Optional, Dict, Any


class PermissionMode(Enum):
    """Permission modes for ACP sessions"""
    READ_ONLY = "read_only"          # Only read operations allowed
    WORKSPACE_WRITE = "workspace_write"  # Write to workspace allowed
    DANGER_FULL_ACCESS = "danger_full_access"  # All operations allowed
    PROMPT = "prompt"                # Prompt user for each permission


class PermissionAction(Enum):
    """Types of permissionable actions"""
    READ_FILE = "read_file"
    WRITE_FILE = "write_file"
    EDIT_FILE = "edit_file"
    DELETE_FILE = "delete_file"
    RUN_BASH = "run_bash"
    RUN_DOCKER = "run_docker"
    NETWORK_REQUEST = "network_request"
    USE_TOOL = "use_tool"


@dataclass
class ACPermission:
    """Represents a permission request"""
    action: PermissionAction
    resource: str  # File path, command, URL, etc.
    details: Dict[str, Any]
    reason: str = ""  # Why this permission is needed


@dataclass
class PermissionResult:
    """Result of a permission check"""
    allowed: bool
    reason: str = ""
    once: bool = False  # Allow this once
    always: bool = False  # Always allow this action


class PermissionPolicy:
    """Policy engine for permission evaluation"""

    def __init__(self, mode: PermissionMode = PermissionMode.PROMPT):
        self.mode = mode
        self._always_allow: set = set()  # Actions that are always allowed
        self._always_deny: set = set()   # Actions that are always denied
        self._prompter: Optional[Callable] = None

    def set_mode(self, mode: PermissionMode) -> None:
        """Set the permission mode"""
        self.mode = mode

    def set_prompter(self, prompter: Callable[[ACPermission], PermissionResult]) -> None:
        """Set the permission prompter callback"""
        self._prompter = prompter

    def allow_always(self, action: PermissionAction) -> None:
        """Always allow an action"""
        self._always_allow.add(action)

    def deny_always(self, action: PermissionAction) -> None:
        """Always deny an action"""
        self._always_deny.add(action)

    def evaluate(self, permission: ACPermission) -> PermissionResult:
        """Evaluate a permission request"""
        # Check always allow/deny lists
        if permission.action in self._always_deny:
            return PermissionResult(
                allowed=False,
                reason=f"Action {permission.action.value} is always denied"
            )

        if permission.action in self._always_allow:
            return PermissionResult(
                allowed=True,
                reason=f"Action {permission.action.value} is always allowed",
                always=True
            )

        # Evaluate based on mode
        if self.mode == PermissionMode.READ_ONLY:
            read_actions = {
                PermissionAction.READ_FILE,
                PermissionAction.USE_TOOL,
                PermissionAction.NETWORK_REQUEST,
            }
            if permission.action in read_actions:
                return PermissionResult(
                    allowed=True,
                    reason="Allowed in read-only mode"
                )
            return PermissionResult(
                allowed=False,
                reason=f"Action {permission.action.value} not allowed in read-only mode"
            )

        elif self.mode == PermissionMode.WORKSPACE_WRITE:
            workspace_actions = {
                PermissionAction.READ_FILE,
                PermissionAction.WRITE_FILE,
                PermissionAction.EDIT_FILE,
                PermissionAction.USE_TOOL,
            }
            if permission.action in workspace_actions:
                return PermissionResult(
                    allowed=True,
                    reason="Allowed in workspace-write mode"
                )
            return PermissionResult(
                allowed=False,
                reason=f"Action {permission.action.value} requires full access"
            )

        elif self.mode == PermissionMode.DANGER_FULL_ACCESS:
            return PermissionResult(
                allowed=True,
                reason="Allowed in danger-full-access mode",
                always=True
            )

        elif self.mode == PermissionMode.PROMPT:
            if self._prompter:
                return self._prompter(permission)
            # If no prompter, deny by default
            return PermissionResult(
                allowed=False,
                reason="No prompter configured"
            )

        return PermissionResult(
            allowed=False,
            reason=f"Unknown permission mode: {self.mode}"
        )

    def authorize(self, action: PermissionAction, resource: str,
                  details: Dict[str, Any] = None) -> PermissionResult:
        """Convenience method to authorize an action"""
        permission = ACPermission(
            action=action,
            resource=resource,
            details=details or {},
        )
        return self.evaluate(permission)


def make_approval_callback(policy: PermissionPolicy) -> Callable:
    """Create an approval callback for use with AIAgent

    This bridges ACP PermissionOption to Hermes allow_once/allow_always/deny
    Inspired by hermes-agent/acp_adapter/permissions.py make_approval_callback
    """
    def callback(permission: ACPermission) -> str:
        """Called when AIAgent requests permission"""
        result = policy.evaluate(permission)

        if result.always:
            return "allow_always"
        elif result.allowed:
            return "allow_once"
        else:
            return "deny"

    return callback


class ToolPermissionMapper:
    """Maps tool names to permission actions"""

    TOOL_TO_ACTION = {
        "read_file": PermissionAction.READ_FILE,
        "write_file": PermissionAction.WRITE_FILE,
        "edit_file": PermissionAction.EDIT_FILE,
        "delete_file": PermissionAction.DELETE_FILE,
        "bash": PermissionAction.RUN_BASH,
        "run_bash": PermissionAction.RUN_BASH,
        "docker": PermissionAction.RUN_DOCKER,
        "web_search": PermissionAction.NETWORK_REQUEST,
        "web_fetch": PermissionAction.NETWORK_REQUEST,
        "http_request": PermissionAction.NETWORK_REQUEST,
    }

    @classmethod
    def get_action(cls, tool_name: str) -> PermissionAction:
        """Get the permission action for a tool"""
        return cls.TOOL_TO_ACTION.get(tool_name, PermissionAction.USE_TOOL)

    @classmethod
    def extract_resource(cls, tool_name: str, tool_input: Dict[str, Any]) -> str:
        """Extract the resource path/identifier from tool input"""
        if tool_name == "read_file":
            return tool_input.get("path", "")
        elif tool_name == "write_file":
            return tool_input.get("path", "")
        elif tool_name == "edit_file":
            return tool_input.get("path", "")
        elif tool_name == "bash":
            return tool_input.get("command", "")
        elif tool_name == "web_search":
            return tool_input.get("query", "")
        elif tool_name == "web_fetch":
            return tool_input.get("url", "")
        return ""


class PermissionEnforcer:
    """Enforces permission checks before tool execution"""

    def __init__(self, policy: PermissionPolicy):
        self.policy = policy
        self._permission_history: Dict[str, PermissionResult] = {}

    def check(self, tool_name: str, tool_input: Dict[str, Any]) -> PermissionResult:
        """Check if a tool execution is permitted"""
        action = ToolPermissionMapper.get_action(tool_name)
        resource = ToolPermissionMapper.extract_resource(tool_name, tool_input)

        permission = ACPermission(
            action=action,
            resource=resource,
            details={"tool_name": tool_name, "tool_input": tool_input},
            reason=f"Tool {tool_name} requires {action.value} on {resource}"
        )

        result = self.policy.evaluate(permission)

        # Cache the result for this tool+resource combination
        cache_key = f"{tool_name}:{resource}"
        self._permission_history[cache_key] = result

        return result

    def is_allowed(self, tool_name: str, tool_input: Dict[str, Any]) -> bool:
        """Quick check if tool is allowed"""
        result = self.check(tool_name, tool_input)
        return result.allowed

    def get_history(self) -> Dict[str, PermissionResult]:
        """Get permission history"""
        return self._permission_history.copy()
