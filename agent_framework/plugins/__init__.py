"""Plugin System for Agent Framework

Provides extensibility through plugins for tools, channels, and other extensions.
Inspired by openclaw's plugin system.
"""

from .registry import PluginRegistry, PluginManifest, Plugin, PluginState
from .loader import PluginLoader
from .runtime import PluginRuntime, PluginContext

__all__ = [
    "PluginRegistry",
    "PluginManifest",
    "Plugin",
    "PluginState",
    "PluginLoader",
    "PluginRuntime",
    "PluginContext",
]
