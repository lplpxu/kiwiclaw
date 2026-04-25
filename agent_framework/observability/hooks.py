"""Hooks System

Provides hook-based extensibility for agent lifecycle events.
Inspired by openclaw/src/plugins/hooks.ts and hermes-agent/hermes_cli/plugins.py
"""

import asyncio
import time
from typing import Dict, Any, Optional, List, Callable
from dataclasses import dataclass, field
from enum import Enum
import threading


class HookName(Enum):
    """Hook names for agent lifecycle events

    Inspired by openclaw's 28 hook types, focused on core events.
    """
    # Tool hooks
    BEFORE_TOOL_CALL = "before_tool_call"
    AFTER_TOOL_CALL = "after_tool_call"
    TOOL_RESULT_PERSIST = "tool_result_persist"

    # LLM hooks
    BEFORE_LLM_CALL = "before_llm_call"
    AFTER_LLM_CALL = "after_llm_call"
    LLM_OUTPUT = "llm_output"

    # Agent hooks
    BEFORE_AGENT_START = "before_agent_start"
    AFTER_AGENT_END = "after_agent_end"
    BEFORE_COMPACTION = "before_compaction"
    AFTER_COMPACTION = "after_compaction"
    BEFORE_RESET = "before_reset"

    # Message hooks
    MESSAGE_RECEIVED = "message_received"
    MESSAGE_SENDING = "message_sending"
    BEFORE_MESSAGE_WRITE = "before_message_write"

    # Session hooks
    SESSION_START = "session_start"
    SESSION_END = "session_end"


@dataclass
class HookResult:
    """Result of a hook execution"""
    handled: bool = False
    modified: bool = False
    modified_content: Any = None
    error: str = ""


@dataclass
class ToolHookContext:
    """Context passed to tool hooks"""
    tool_name: str
    tool_input: Dict[str, Any]
    agent_name: str
    messages: list
    iteration: int = 0


@dataclass
class LLIHookContext:
    """Context passed to LLM hooks"""
    messages: List[Dict[str, Any]]
    system_prompt: str
    model: str
    tools: List[Dict[str, Any]]


class Hook:
    """A single hook handler"""
    def __init__(
        self,
        name: HookName,
        handler: Callable,
        priority: int = 100,
    ):
        self.name = name
        self.handler = handler
        self.priority = priority


class HookRunner:
    """Manages and executes hooks

    Inspired by openclaw's createHookRunner() with priority ordering.
    Thread-safe hook registration and execution.
    """

    def __init__(self):
        self._hooks: Dict[HookName, List[Hook]] = {}
        self._sync_lock = threading.Lock()
        self._async_lock: Optional[asyncio.Lock] = None
        self._loop_detection: Dict[str, int] = {}  # For detecting hook loops

    def _get_async_lock(self) -> asyncio.Lock:
        """Get or create the async lock lazily"""
        if self._async_lock is None:
            self._async_lock = asyncio.Lock()
        return self._async_lock

    def register(
        self,
        name: HookName,
        handler: Callable,
        priority: int = 100,
    ) -> None:
        """Register a hook handler

        Args:
            name: Hook name
            handler: Callable that takes context and returns HookResult
            priority: Lower = higher priority (runs first)
        """
        with self._sync_lock:
            if name not in self._hooks:
                self._hooks[name] = []

            hook = Hook(name=name, handler=handler, priority=priority)
            self._hooks[name].append(hook)
            # Sort by priority
            self._hooks[name].sort(key=lambda h: h.priority)

    def unregister(self, name: HookName, handler: Callable) -> bool:
        """Unregister a hook handler

        Args:
            name: Hook name
            handler: Handler to remove

        Returns:
            True if handler was removed
        """
        with self._sync_lock:
            if name not in self._hooks:
                return False

            for i, hook in enumerate(self._hooks[name]):
                if hook.handler == handler:
                    del self._hooks[name][i]
                    return True
            return False

    async def run_before_tool_call(
        self,
        context: ToolHookContext,
    ) -> tuple[bool, Any]:
        """Run before_tool_call hooks

        Args:
            context: Tool hook context

        Returns:
            Tuple of (blocked, modified_input)
            - blocked: True if any hook blocked execution
            - modified_input: Modified tool input if any hook modified it
        """
        print(f"[DEBUG hooks] run_before_tool_call: tool={context.tool_name}, iteration={context.iteration}")
        if HookName.BEFORE_TOOL_CALL not in self._hooks:
            print(f"[DEBUG hooks] no before_tool_call hooks registered")
            return False, None

        # Loop detection (参考 openclaw runBeforeToolCallHook)
        loop_key = f"before_tool_call:{context.tool_name}"
        self._loop_detection[loop_key] = self._loop_detection.get(loop_key, 0) + 1
        if self._loop_detection[loop_key] > 10:
            print(f"[DEBUG hooks] loop detected for {context.tool_name}, blocking")
            return True, None  # Blocked due to loop
            return True, None  # Blocked due to loop

        try:
            async with self._get_async_lock():
                hooks = list(self._hooks.get(HookName.BEFORE_TOOL_CALL, []))

            modified_input = None
            for hook in hooks:
                try:
                    if asyncio.iscoroutinefunction(hook.handler):
                        result = await hook.handler(context)
                    else:
                        result = hook.handler(context)

                    if result and result.handled:
                        # Hook handled the call (may have modified content)
                        return True, result.modified_content
                except Exception as e:
                    # Hook error - log and continue
                    pass

            return False, None

        finally:
            self._loop_detection[loop_key] -= 1

    async def run_after_tool_call(
        self,
        context: ToolHookContext,
        result: Any,
    ) -> Any:
        """Run after_tool_call hooks

        Args:
            context: Tool hook context
            result: Tool execution result

        Returns:
            Potentially modified result
        """
        print(f"[DEBUG hooks] run_after_tool_call: tool={context.tool_name}, result_len={len(str(result))}")
        if HookName.AFTER_TOOL_CALL not in self._hooks:
            return result

        async with self._get_async_lock():
            hooks = list(self._hooks.get(HookName.AFTER_TOOL_CALL, []))

        modified_result = result
        for hook in hooks:
            try:
                if asyncio.iscoroutinefunction(hook.handler):
                    hook_result = await hook.handler(context, modified_result)
                else:
                    hook_result = hook.handler(context, modified_result)

                if hook_result and hook_result.modified:
                    modified_result = hook_result.modified_content
            except Exception:
                pass

        return modified_result

    async def run_before_llm_call(
        self,
        context: LLIHookContext,
    ) -> None:
        """Run before_llm_call hooks (fire and forget)

        Args:
            context: LLM hook context
        """
        if HookName.BEFORE_LLM_CALL not in self._hooks:
            return

        async with self._lock:
            hooks = list(self._hooks.get(HookName.BEFORE_LLM_CALL, []))

        # Fire and forget - don't wait for results
        for hook in hooks:
            try:
                if asyncio.iscoroutinefunction(hook.handler):
                    asyncio.create_task(hook.handler(context))
                else:
                    hook.handler(context)
            except Exception:
                pass

    async def run_after_llm_call(
        self,
        context: LLIHookContext,
        response: Any,
    ) -> Any:
        """Run after_llm_call hooks

        Args:
            context: LLM hook context
            response: LLM response

        Returns:
            Potentially modified response
        """
        if HookName.AFTER_LLM_CALL not in self._hooks:
            return response

        async with self._lock:
            hooks = list(self._hooks.get(HookName.AFTER_LLM_CALL, []))

        modified_response = response
        for hook in hooks:
            try:
                if asyncio.iscoroutinefunction(hook.handler):
                    hook_result = await hook.handler(context, modified_response)
                else:
                    hook_result = hook.handler(context, modified_response)

                if hook_result and hook_result.modified:
                    modified_response = hook_result.modified_content
            except Exception:
                pass

        return modified_response

    def get_registered_hooks(self) -> Dict[HookName, int]:
        """Get count of registered hooks by name

        Returns:
            Dict mapping hook name to count
        """
        with self._sync_lock:
            return {name: len(hooks) for name, hooks in self._hooks.items()}

    def clear(self) -> None:
        """Clear all hooks"""
        with self._sync_lock:
            self._hooks.clear()
            self._loop_detection.clear()


# Decorator for convenient hook registration
def hook(name: HookName, priority: int = 100):
    """Decorator to register a function as a hook handler

    Usage:
        @hook(HookName.BEFORE_TOOL_CALL, priority=50)
        async def my_handler(context: ToolHookContext) -> HookResult:
            ...
    """
    def decorator(func: Callable) -> Callable:
        # Store hook metadata on function
        func._hook_name = name
        func._hook_priority = priority
        return func
    return decorator


# Global hook runner
_hook_runner: Optional[HookRunner] = None


def get_hook_runner() -> HookRunner:
    """Get the global hook runner"""
    global _hook_runner
    if _hook_runner is None:
        _hook_runner = HookRunner()
    return _hook_runner