"""Plugin Loader

Handles plugin loading, initialization, and lifecycle management.
Inspired by openclaw's plugin loader.
[PHASE4] 插件系统 - PluginLoader
"""

import importlib.util
import sys
import json
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass

from .registry import PluginRegistry, Plugin, PluginManifest, PluginState

# Debug print helper
def _debug(msg: str):
    print(f"[PHASE4] [PluginLoader] {msg}")


class PluginLoader:
    """Handles plugin loading and lifecycle

    Responsible for:
    - Discovering plugins from various sources
    - Loading plugin code and resources
    - Initializing plugins
    - Managing plugin dependencies
    """

    def __init__(self, registry: PluginRegistry = None):
        self.registry = registry or get_plugin_registry()
        self._loaders: Dict[str, "PluginLoaderBase"] = {}  # Registered loaders by type

        # Register default loaders
        self._register_default_loaders()

    def _register_default_loaders(self) -> None:
        """Register default plugin loaders"""
        # Python module loader
        self.register_loader("python", PythonPluginLoader())

        # Directory-based plugin loader
        self.register_loader("directory", DirectoryPluginLoader())

        # JSON manifest loader
        self.register_loader("manifest", ManifestPluginLoader())

    def register_loader(self, loader_type: str, loader: "PluginLoaderBase") -> None:
        """Register a plugin loader for a specific type"""
        _debug(f"→ register_loader(type={loader_type})")
        self._loaders[loader_type] = loader
        _debug(f"← register_loader {loader_type} registered")

    def get_loader(self, loader_type: str) -> Optional["PluginLoaderBase"]:
        """Get a registered loader by type"""
        _debug(f"→ get_loader(type={loader_type})")
        loader = self._loaders.get(loader_type)
        _debug(f"← get_loader {loader_type} -> {'found' if loader else 'not found'}")
        return loader

    def discover_plugins(
        self,
        paths: List[Path],
        patterns: List[str] = None
    ) -> List[Plugin]:
        """Discover plugins from filesystem paths

        Args:
            paths: List of directory paths to search
            patterns: Optional list of filename patterns to match (e.g., ["*.json", "*.py"])

        Returns:
            List of discovered Plugin objects
        """
        discovered = []

        for path in paths:
            if not path.exists():
                continue

            # If path is a file, load it directly
            if path.is_file():
                plugin = self.load_plugin_from_file(path)
                if plugin:
                    discovered.append(plugin)
                continue

            # If path is a directory, search recursively
            for item in path.rglob("*"):
                if item.is_dir():
                    manifest = item / "plugin.json"
                    if manifest.exists():
                        plugin = self.load_plugin_from_file(manifest)
                        if plugin:
                            discovered.append(plugin)

        return discovered

    def load_plugin_from_file(self, file_path: Path) -> Optional[Plugin]:
        """Load a plugin from a file

        Supports:
        - plugin.json manifest files
        - Python .py files with plugin metadata
        """
        if not file_path.exists():
            return None

        try:
            if file_path.suffix == ".json":
                # JSON manifest
                manifest = PluginManifest.from_file(file_path)
                plugin = Plugin(manifest=manifest)
                self.registry.register(plugin)
                return plugin

            elif file_path.suffix == ".py":
                # Python module - need to extract metadata
                return self._load_python_plugin(file_path)

        except Exception as e:
            print(f"Failed to load plugin from {file_path}: {e}")

        return None

    def _load_python_plugin(self, file_path: Path) -> Optional[Plugin]:
        """Load a Python file as a plugin"""
        module_name = file_path.stem

        # Try to load the module
        spec = importlib.util.spec_from_file_location(module_name, file_path)
        if not spec or not spec.loader:
            return None

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module

        try:
            spec.loader.exec_module(module)
        except Exception as e:
            print(f"Failed to execute plugin module {module_name}: {e}")
            return None

        # Extract manifest from module attributes
        manifest_data = {
            "name": getattr(module, "PLUGIN_NAME", module_name),
            "version": getattr(module, "PLUGIN_VERSION", "1.0.0"),
            "description": getattr(module, "PLUGIN_DESCRIPTION", ""),
            "author": getattr(module, "PLUGIN_AUTHOR", ""),
            "tools": getattr(module, "PLUGIN_TOOLS", []),
            "channels": getattr(module, "PLUGIN_CHANNELS", []),
            "skills": getattr(module, "PLUGIN_SKILLS", []),
            "entry_point": str(file_path),
            "init_function": getattr(module, "PLUGIN_INIT", "init"),
            "shutdown_function": getattr(module, "PLUGIN_SHUTDOWN", "shutdown"),
        }

        manifest = PluginManifest.from_dict(manifest_data)
        plugin = Plugin(manifest=manifest, module=module)

        self.registry.register(plugin)
        return plugin

    def load_plugin(self, name: str) -> bool:
        """Load a registered plugin by name"""
        return self.registry.load_plugin(name)

    def unload_plugin(self, name: str) -> bool:
        """Unload a plugin by name"""
        return self.registry.unload_plugin(name)

    def initialize_plugin(self, name: str, config: Dict[str, Any] = None) -> bool:
        """Initialize a loaded plugin with configuration"""
        plugin = self.registry.get(name)
        if not plugin or plugin.state != PluginState.LOADED:
            return False

        try:
            if config:
                plugin.config.update(config)

            # Call initialization function if exists
            if plugin.module and hasattr(plugin.module, plugin.manifest.init_function):
                init_fn = getattr(plugin.module, plugin.manifest.init_function)
                if callable(init_fn):
                    init_fn(plugin.config)

            plugin.state = PluginState.INITIALIZED

            # Fire on_init callback
            if plugin.on_init:
                plugin.on_init(plugin)

            return True

        except Exception as e:
            plugin.state = PluginState.FAILED
            plugin.error_message = str(e)
            return False

    def load_all(self) -> Dict[str, bool]:
        """Load all discovered plugins

        Returns:
            Dictionary mapping plugin names to success/failure
        """
        results = {}
        for plugin in self.registry.list_plugins():
            results[plugin.manifest.name] = self.registry.load_plugin(plugin.manifest.name)
        return results

    def initialize_all(self) -> Dict[str, bool]:
        """Initialize all loaded plugins

        Returns:
            Dictionary mapping plugin names to success/failure
        """
        results = {}
        for plugin in self.registry.list_by_state(PluginState.LOADED):
            results[plugin.manifest.name] = self.initialize_plugin(plugin.manifest.name)
        return results


class PluginLoaderBase:
    """Base class for plugin loaders"""

    def can_load(self, path: Path) -> bool:
        """Check if this loader can handle the given path"""
        raise NotImplementedError

    def load(self, path: Path) -> Optional[Plugin]:
        """Load a plugin from the given path"""
        raise NotImplementedError


class DirectoryPluginLoader(PluginLoaderBase):
    """Loads plugins from directories containing plugin.json"""

    def can_load(self, path: Path) -> bool:
        return path.is_dir() and (path / "plugin.json").exists()

    def load(self, path: Path) -> Optional[Plugin]:
        manifest_file = path / "plugin.json"
        if not manifest_file.exists():
            return None

        try:
            manifest = PluginManifest.from_file(manifest_file)
            return Plugin(manifest=manifest)
        except Exception as e:
            print(f"Failed to load plugin from {manifest_file}: {e}")
            return None


class ManifestPluginLoader(PluginLoaderBase):
    """Loads plugins from JSON manifest files"""

    def can_load(self, path: Path) -> bool:
        return path.is_file() and path.suffix == ".json" and path.stem == "plugin"

    def load(self, path: Path) -> Optional[Plugin]:
        try:
            manifest = PluginManifest.from_file(path)
            return Plugin(manifest=manifest)
        except Exception as e:
            print(f"Failed to load plugin from {path}: {e}")
            return None


class PythonPluginLoader(PluginLoaderBase):
    """Loads plugins from Python files with PLUGIN_* metadata"""

    def can_load(self, path: Path) -> bool:
        return path.is_file() and path.suffix == ".py"

    def load(self, path: Path) -> Optional[Plugin]:
        module_name = path.stem

        spec = importlib.util.spec_from_file_location(module_name, path)
        if not spec or not spec.loader:
            return None

        module = importlib.util.module_from_spec(spec)

        try:
            spec.loader.exec_module(module)
        except Exception as e:
            print(f"Failed to execute plugin module {module_name}: {e}")
            return None

        # Extract manifest from module
        manifest_data = {
            "name": getattr(module, "PLUGIN_NAME", module_name),
            "version": getattr(module, "PLUGIN_VERSION", "1.0.0"),
            "description": getattr(module, "PLUGIN_DESCRIPTION", ""),
            "entry_point": str(path),
            "init_function": getattr(module, "PLUGIN_INIT", "init"),
        }

        manifest = PluginManifest.from_dict(manifest_data)
        return Plugin(manifest=manifest, module=module)


# Decorator for defining plugins
def plugin(
    name: str,
    version: str = "1.0.0",
    description: str = "",
    tools: List[Dict] = None,
    channels: List[str] = None,
):
    """Decorator for defining a plugin"""

    def decorator(func_or_class):
        # Set module-level attributes
        module = func_or_class.__module__
        setattr(func_or_class, "PLUGIN_NAME", name)
        setattr(func_or_class, "PLUGIN_VERSION", version)
        setattr(func_or_class, "PLUGIN_DESCRIPTION", description)
        setattr(func_or_class, "PLUGIN_TOOLS", tools or [])
        setattr(func_or_class, "PLUGIN_CHANNELS", channels or [])

        # Auto-register the plugin
        registry = get_plugin_registry()
        manifest = PluginManifest(
            name=name,
            version=version,
            description=description,
            tools=tools or [],
            channels=channels or [],
            entry_point=func_or_class.__file__ if hasattr(func_or_class, "__file__") else "",
        )
        plugin_obj = Plugin(manifest=manifest, instance=func_or_class)
        registry.register(plugin_obj)

        return func_or_class

    return decorator
