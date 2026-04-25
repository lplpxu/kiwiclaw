"""Plugin Registry

Manages plugin registration and discovery.
Inspired by openclaw's plugin registry.
"""

import json
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from enum import Enum
import importlib.util
import sys


class PluginState(Enum):
    """Plugin lifecycle states"""
    DISCOVERED = "discovered"
    LOADING = "loading"
    LOADED = "loaded"
    INITIALIZED = "initialized"
    FAILED = "failed"
    UNLOADED = "unloaded"


@dataclass
class PluginManifest:
    """Plugin manifest defining plugin metadata and capabilities"""
    name: str
    version: str
    description: str = ""
    author: str = ""
    license: str = ""
    homepage: str = ""

    # Capabilities
    tools: List[Dict[str, Any]] = field(default_factory=list)  # Tools provided by this plugin
    channels: List[str] = field(default_factory=list)  # Channel types provided
    skills: List[str] = field(default_factory=list)  # Skills provided

    # Dependencies
    dependencies: List[str] = field(default_factory=list)  # Other plugin names required
    system_requirements: Dict[str, str] = field(default_factory=dict)  # e.g., {"python_version": ">=3.8"}

    # Configuration
    config_schema: Dict[str, Any] = field(default_factory=dict)  # JSON schema for config
    default_config: Dict[str, Any] = field(default_factory=dict)

    # Lifecycle
    entry_point: str = ""  # Module or function to call for loading
    init_function: str = "init"  # Function to call for initialization
    shutdown_function: str = "shutdown"  # Function to call for cleanup

    @classmethod
    def from_dict(cls, data: dict) -> "PluginManifest":
        """Create manifest from dictionary"""
        return cls(
            name=data["name"],
            version=data["version"],
            description=data.get("description", ""),
            author=data.get("author", ""),
            license=data.get("license", ""),
            homepage=data.get("homepage", ""),
            tools=data.get("tools", []),
            channels=data.get("channels", []),
            skills=data.get("skills", []),
            dependencies=data.get("dependencies", []),
            system_requirements=data.get("system_requirements", {}),
            config_schema=data.get("config_schema", {}),
            default_config=data.get("default_config", {}),
            entry_point=data.get("entry_point", ""),
            init_function=data.get("init_function", "init"),
            shutdown_function=data.get("shutdown_function", "shutdown"),
        )

    def to_dict(self) -> dict:
        """Convert manifest to dictionary"""
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "author": self.author,
            "license": self.license,
            "homepage": self.homepage,
            "tools": self.tools,
            "channels": self.channels,
            "skills": self.skills,
            "dependencies": self.dependencies,
            "system_requirements": self.system_requirements,
            "config_schema": self.config_schema,
            "default_config": self.default_config,
            "entry_point": self.entry_point,
            "init_function": self.init_function,
            "shutdown_function": self.shutdown_function,
        }

    @classmethod
    def from_file(cls, path: Path) -> "PluginManifest":
        """Load manifest from a JSON file"""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls.from_dict(data)


@dataclass
class Plugin:
    """Represents a loaded plugin instance"""
    manifest: PluginManifest
    state: PluginState = PluginState.DISCOVERED
    module: Any = None  # Loaded Python module
    instance: Any = None  # Plugin instance (if class-based)
    config: Dict[str, Any] = field(default_factory=dict)
    error_message: str = ""

    # Callbacks
    on_load: Optional[Callable] = None
    on_init: Optional[Callable] = None
    on_unload: Optional[Callable] = None

    def to_dict(self) -> dict:
        """Convert plugin to dictionary"""
        return {
            "name": self.manifest.name,
            "version": self.manifest.version,
            "state": self.state.value,
            "config": self.config,
            "error_message": self.error_message,
        }


class PluginRegistry:
    """Central registry for all plugins

    Manages plugin discovery, loading, initialization, and lifecycle.
    Implements singleton pattern for global access.
    Inspired by openclaw's plugin registry.
    """

    _instance = None
    _lock = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._plugins: Dict[str, Plugin] = {}
        self._tools: Dict[str, Dict[str, Any]] = {}  # tool_name -> tool_spec
        self._channels: Dict[str, str] = {}  # channel_type -> plugin_name
        self._skills: Dict[str, str] = {}  # skill_name -> plugin_name
        self._lock = __import__("threading").Lock()
        self._discovery_paths: List[Path] = []
        self._initialized = True

    def add_discovery_path(self, path: Path) -> None:
        """Add a path to search for plugins"""
        if path not in self._discovery_paths:
            self._discovery_paths.append(path)

    def register(self, plugin: Plugin) -> None:
        """Register a plugin"""
        with self._lock:
            self._plugins[plugin.manifest.name] = plugin

            # Register its capabilities
            for tool in plugin.manifest.tools:
                tool_name = tool.get("name")
                if tool_name:
                    self._tools[tool_name] = tool

            for channel in plugin.manifest.channels:
                self._channels[channel] = plugin.manifest.name

            for skill in plugin.manifest.skills:
                self._skills[skill] = plugin.manifest.name

    def unregister(self, name: str) -> bool:
        """Unregister a plugin"""
        with self._lock:
            if name not in self._plugins:
                return False

            plugin = self._plugins[name]

            # Remove its capabilities
            for tool in plugin.manifest.tools:
                tool_name = tool.get("name")
                if tool_name and tool_name in self._tools:
                    del self._tools[tool_name]

            for channel in plugin.manifest.channels:
                if channel in self._channels:
                    del self._channels[channel]

            for skill in plugin.manifest.skills:
                if skill in self._skills:
                    del self._skills[skill]

            del self._plugins[name]
            return True

    def get(self, name: str) -> Optional[Plugin]:
        """Get a plugin by name"""
        return self._plugins.get(name)

    def list_plugins(self) -> List[Plugin]:
        """List all registered plugins"""
        return list(self._plugins.values())

    def list_by_state(self, state: PluginState) -> List[Plugin]:
        """List plugins by state"""
        return [p for p in self._plugins.values() if p.state == state]

    def get_tool(self, tool_name: str) -> Optional[Dict[str, Any]]:
        """Get a tool by name"""
        return self._tools.get(tool_name)

    def list_tools(self) -> List[Dict[str, Any]]:
        """List all registered tools"""
        return list(self._tools.values())

    def get_channel(self, channel_type: str) -> Optional[str]:
        """Get the plugin name for a channel type"""
        return self._channels.get(channel_type)

    def list_channels(self) -> Dict[str, str]:
        """List all channel type to plugin mappings"""
        return self._channels.copy()

    def get_skill(self, skill_name: str) -> Optional[str]:
        """Get the plugin name for a skill"""
        return self._skills.get(skill_name)

    def list_skills(self) -> Dict[str, str]:
        """List all skill to plugin mappings"""
        return self._skills.copy()

    def load_plugin(self, name: str) -> bool:
        """Load a plugin by name"""
        plugin = self.get(name)
        if not plugin:
            return False

        if plugin.state == PluginState.LOADED:
            return True  # Already loaded

        plugin.state = PluginState.LOADING

        try:
            # Dynamic import based on entry_point
            if plugin.manifest.entry_point:
                spec = importlib.util.spec_from_file_location(
                    plugin.manifest.name,
                    plugin.manifest.entry_point
                )
                if spec and spec.loader:
                    module = importlib.util.module_from_spec(spec)
                    sys.modules[plugin.manifest.name] = module
                    spec.loader.exec_module(module)
                    plugin.module = module

                    # Try to call init function
                    init_fn = getattr(module, plugin.manifest.init_function, None)
                    if init_fn:
                        init_fn(plugin.config)

            plugin.state = PluginState.LOADED

            # Fire on_load callback
            if plugin.on_load:
                plugin.on_load(plugin)

            return True

        except Exception as e:
            plugin.state = PluginState.FAILED
            plugin.error_message = str(e)
            return False

    def unload_plugin(self, name: str) -> bool:
        """Unload a plugin by name"""
        plugin = self.get(name)
        if not plugin:
            return False

        if plugin.state == PluginState.UNLOADED:
            return True  # Already unloaded

        try:
            # Call shutdown function if exists
            if plugin.module and hasattr(plugin.module, plugin.manifest.shutdown_function):
                shutdown_fn = getattr(plugin.module, plugin.manifest.shutdown_function)
                shutdown_fn()

            # Fire on_unload callback
            if plugin.on_unload:
                plugin.on_unload(plugin)

            plugin.state = PluginState.UNLOADED
            return True

        except Exception as e:
            plugin.state = PluginState.FAILED
            plugin.error_message = str(e)
            return False

    def discover_plugins(self) -> List[Plugin]:
        """Discover plugins from discovery paths"""
        discovered = []

        for path in self._discovery_paths:
            if not path.exists():
                continue

            # Look for plugin directories
            for item in path.iterdir():
                if item.is_dir():
                    manifest_file = item / "plugin.json"
                    if manifest_file.exists():
                        try:
                            manifest = PluginManifest.from_file(manifest_file)
                            plugin = Plugin(manifest=manifest)
                            self.register(plugin)
                            discovered.append(plugin)
                        except Exception as e:
                            print(f"Failed to load plugin from {manifest_file}: {e}")

        return discovered

    def clear(self) -> None:
        """Clear all plugins (for testing)"""
        with self._lock:
            self._plugins.clear()
            self._tools.clear()
            self._channels.clear()
            self._skills.clear()


# Global registry instance
_global_registry: Optional[PluginRegistry] = None


def get_plugin_registry() -> PluginRegistry:
    """Get the global plugin registry instance"""
    global _global_registry
    if _global_registry is None:
        _global_registry = PluginRegistry()
    return _global_registry
