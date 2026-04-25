"""Plugin Runtime

Provides runtime context and services for plugins.
Inspired by openclaw's plugin runtime.
"""

import asyncio
from typing import Dict, Any, Optional, List, Callable
from dataclasses import dataclass, field
from enum import Enum

from .registry import Plugin, PluginRegistry, PluginState, get_plugin_registry
from .loader import PluginLoader


class SandboxMode(Enum):
    """Sandbox isolation modes"""
    NONE = "none"  # No sandboxing
    DOCKER = "docker"  # Docker container isolation
    PROCESS = "process"  # Separate process isolation
    WEB = "web"  # WebAssembly sandbox


@dataclass
class PluginContext:
    """Context provided to plugins at runtime

    Provides access to framework services and resources.
    """
    plugin: Plugin
    registry: PluginRegistry
    config: Dict[str, Any] = field(default_factory=dict)

    # Services provided by the framework
    agent = None  # AIAgent instance
    tools = None  # Tool registry/executor
    sandbox = None  # Sandbox manager

    # Event callbacks
    on_tool_call: Optional[Callable] = None
    on_tool_result: Optional[Callable] = None
    on_message: Optional[Callable] = None
    on_error: Optional[Callable] = None

    def get_service(self, service_name: str) -> Any:
        """Get a framework service by name"""
        services = {
            "agent": self.agent,
            "tools": self.tools,
            "sandbox": self.sandbox,
        }
        return services.get(service_name)

    def emit_tool_call(self, tool_name: str, tool_input: Dict[str, Any]) -> None:
        """Emit a tool call event"""
        if self.on_tool_call:
            self.on_tool_call(tool_name, tool_input)

    def emit_tool_result(self, tool_name: str, tool_output: str) -> None:
        """Emit a tool result event"""
        if self.on_tool_result:
            self.on_tool_result(tool_name, tool_output)

    def emit_message(self, message: str, message_type: str = "info") -> None:
        """Emit a message event"""
        if self.on_message:
            self.on_message(message, message_type)

    def emit_error(self, error: str, fatal: bool = False) -> None:
        """Emit an error event"""
        if self.on_error:
            self.on_error(error, fatal)


class PluginRuntime:
    """Manages plugin runtime lifecycle

    Coordinates between the plugin system and the agent framework,
    handling initialization, tool registration, and event routing.
    """

    def __init__(
        self,
        registry: PluginRegistry = None,
        loader: PluginLoader = None,
        sandbox_mode: SandboxMode = SandboxMode.NONE,
    ):
        self.registry = registry or get_plugin_registry()
        self.loader = loader or PluginLoader(self.registry)
        self.sandbox_mode = sandbox_mode

        # Plugin contexts
        self._contexts: Dict[str, PluginContext] = {}

        # Sandbox management
        self._sandboxes: Dict[str, Any] = {}  # plugin_name -> sandbox instance

        # Event routing
        self._event_handlers: Dict[str, List[Callable]] = {}

        # Tool executor
        self._tool_handlers: Dict[str, Callable] = {}

    def create_context(self, plugin: Plugin) -> PluginContext:
        """Create a runtime context for a plugin"""
        ctx = PluginContext(
            plugin=plugin,
            registry=self.registry,
            config=plugin.config.copy() if plugin.config else {},
        )
        self._contexts[plugin.manifest.name] = ctx
        return ctx

    def get_context(self, plugin_name: str) -> Optional[PluginContext]:
        """Get the runtime context for a plugin"""
        return self._contexts.get(plugin_name)

    def register_tool_handler(
        self,
        tool_name: str,
        handler: Callable,
        plugin_name: str = None
    ) -> None:
        """Register a tool handler from a plugin"""
        self._tool_handlers[tool_name] = handler

    def unregister_tool_handler(self, tool_name: str) -> None:
        """Unregister a tool handler"""
        if tool_name in self._tool_handlers:
            del self._tool_handlers[tool_name]

    async def execute_tool(
        self,
        tool_name: str,
        tool_input: Dict[str, Any],
        sandbox: bool = False
    ) -> Dict[str, Any]:
        """Execute a tool, optionally in a sandbox

        Args:
            tool_name: Name of the tool to execute
            tool_input: Input parameters for the tool
            sandbox: Whether to run in sandbox

        Returns:
            Dictionary with 'output' or 'error' key
        """
        # Get tool handler
        handler = self._tool_handlers.get(tool_name)
        if not handler:
            return {"error": f"Unknown tool: {tool_name}"}

        # Emit tool call event
        self._emit_event("tool_call", {"tool": tool_name, "input": tool_input})

        try:
            if sandbox and self.sandbox_mode != SandboxMode.NONE:
                # Execute in sandbox
                output = await self._execute_in_sandbox(tool_name, tool_input)
            else:
                # Execute directly
                if asyncio.iscoroutinefunction(handler):
                    output = await handler(**tool_input)
                else:
                    output = handler(**tool_input)

            # Emit success event
            self._emit_event("tool_result", {
                "tool": tool_name,
                "output": str(output)[:1000],  # Truncate for logging
            })

            return {"output": output}

        except Exception as e:
            error_msg = f"Tool execution failed: {e}"

            # Emit error event
            self._emit_event("tool_error", {
                "tool": tool_name,
                "error": error_msg,
            })

            return {"error": error_msg}

    async def _execute_in_sandbox(
        self,
        tool_name: str,
        tool_input: Dict[str, Any]
    ) -> Any:
        """Execute a tool in a sandbox"""
        if self.sandbox_mode == SandboxMode.DOCKER:
            return await self._execute_in_docker(tool_name, tool_input)
        elif self.sandbox_mode == SandboxMode.PROCESS:
            return await self._execute_in_process(tool_name, tool_input)
        else:
            raise NotImplementedError(f"Sandbox mode {self.sandbox_mode} not implemented")

    async def _execute_in_docker(
        self,
        tool_name: str,
        tool_input: Dict[str, Any]
    ) -> Any:
        """Execute tool in Docker container"""
        # This would use Docker SDK to run the tool in a container
        # For now, just execute directly
        handler = self._tool_handlers.get(tool_name)
        if asyncio.iscoroutinefunction(handler):
            return await handler(**tool_input)
        return handler(**tool_input)

    async def _execute_in_process(
        self,
        tool_name: str,
        tool_input: Dict[str, Any]
    ) -> Any:
        """Execute tool in separate process"""
        # This would use multiprocessing to run the tool in isolation
        handler = self._tool_handlers.get(tool_name)
        if asyncio.iscoroutinefunction(handler):
            return await handler(**tool_input)
        return handler(**tool_input)

    def initialize_plugin(self, plugin_name: str, config: Dict[str, Any] = None) -> bool:
        """Initialize a plugin with its context"""
        plugin = self.registry.get(plugin_name)
        if not plugin:
            return False

        # Create context
        ctx = self.create_context(plugin)
        if config:
            ctx.config.update(config)

        # Register tool handlers from plugin
        for tool in plugin.manifest.tools:
            tool_name = tool.get("name")
            if tool_name and hasattr(ctx, "execute_tool"):
                # For class-based plugins, use their execute method
                if plugin.instance and hasattr(plugin.instance, "execute_tool"):
                    self.register_tool_handler(
                        tool_name,
                        lambda inp, p=plugin.instance: p.execute_tool(**inp),
                        plugin_name
                    )

        # Call plugin's init function if exists
        if plugin.module and hasattr(plugin.module, plugin.manifest.init_function):
            init_fn = getattr(plugin.module, plugin.manifest.init_function)
            if callable(init_fn):
                init_fn(ctx)

        plugin.state = PluginState.INITIALIZED
        return True

    def shutdown_plugin(self, plugin_name: str) -> bool:
        """Shutdown a plugin"""
        plugin = self.registry.get(plugin_name)
        if not plugin:
            return False

        # Call plugin's shutdown function if exists
        if plugin.module and hasattr(plugin.module, plugin.manifest.shutdown_function):
            shutdown_fn = getattr(plugin.module, plugin.manifest.shutdown_function)
            if callable(shutdown_fn):
                try:
                    shutdown_fn()
                except Exception as e:
                    print(f"Plugin {plugin_name} shutdown error: {e}")

        # Unregister tool handlers
        for tool in plugin.manifest.tools:
            tool_name = tool.get("name")
            if tool_name:
                self.unregister_tool_handler(tool_name)

        # Clean up context
        if plugin_name in self._contexts:
            del self._contexts[plugin_name]

        # Clean up sandbox if exists
        if plugin_name in self._sandboxes:
            del self._sandboxes[plugin_name]

        plugin.state = PluginState.UNLOADED
        return True

    def _emit_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """Emit an event to registered handlers"""
        handlers = self._event_handlers.get(event_type, [])
        for handler in handlers:
            try:
                handler(data)
            except Exception as e:
                print(f"Event handler error: {e}")

    def on_event(self, event_type: str, handler: Callable) -> None:
        """Register an event handler"""
        if event_type not in self._event_handlers:
            self._event_handlers[event_type] = []
        self._event_handlers[event_type].append(handler)

    def off_event(self, event_type: str, handler: Callable) -> None:
        """Unregister an event handler"""
        if event_type in self._event_handlers:
            self._event_handlers[event_type].remove(handler)

    def list_tools(self) -> List[Dict[str, Any]]:
        """List all registered tools from all plugins"""
        all_tools = []
        for plugin in self.registry.list_plugins():
            all_tools.extend(plugin.manifest.tools)
        return all_tools

    def get_tool(self, tool_name: str) -> Optional[Dict[str, Any]]:
        """Get tool specification by name"""
        for plugin in self.registry.list_plugins():
            for tool in plugin.manifest.tools:
                if tool.get("name") == tool_name:
                    return tool
        return None


# Default runtime instance
_default_runtime: Optional[PluginRuntime] = None


def get_plugin_runtime() -> PluginRuntime:
    """Get the default plugin runtime instance"""
    global _default_runtime
    if _default_runtime is None:
        _default_runtime = PluginRuntime()
    return _default_runtime
