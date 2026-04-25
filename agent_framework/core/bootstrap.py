"""Bootstrap Module

Provides startup and initialization flow for the agent framework.
"""

import os
import time
import logging
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from enum import Enum
import asyncio


class BootstrapState(Enum):
    """Bootstrap process state"""
    IDLE = "idle"
    LOADING_CONFIG = "loading_config"
    INITIALIZING_LOGGING = "initializing_logging"
    INITIALIZING_TRACING = "initializing_tracing"
    INITIALIZING_METRICS = "initializing_metrics"
    CONNECTING_TRANSPORT = "connecting_transport"
    LOADING_TOOLS = "loading_tools"
    LOADING_SKILLS = "loading_skills"
    RESTORING_SESSION = "restoring_session"
    READY = "ready"
    FAILED = "failed"


@dataclass
class BootstrapConfig:
    """Configuration for bootstrap process"""
    config_file: str = ".claw.json"
    sandbox_enabled: bool = True
    restore_session: bool = True
    init_tracing: bool = True
    init_metrics: bool = True
    load_skills: bool = True
    plugin_dirs: List[str] = field(default_factory=lambda: ["plugins", ".claw/plugins"])


@dataclass
class BootstrapResult:
    """Result of bootstrap process"""
    success: bool
    state: BootstrapState
    duration_ms: float
    error: str = ""
    initialized_components: Dict[str, Any] = field(default_factory=dict)


class Bootstrap:
    """Bootstrap orchestrator for agent startup

    Manages the ordered initialization of all agent components.
    """

    def __init__(self, config: BootstrapConfig = None):
        self.config = config or BootstrapConfig()
        self.state = BootstrapState.IDLE
        self.logger = logging.getLogger("bootstrap")
        self._components: Dict[str, Any] = {}
        self._start_time: float = 0

    async def run(self) -> BootstrapResult:
        """Run the full bootstrap process

        Returns:
            BootstrapResult with success status and initialized components
        """
        self._start_time = time.time()
        print("[DEBUG bootstrap] === Bootstrap 开始 ===")

        try:
            # Phase 1: Configuration
            self.state = BootstrapState.LOADING_CONFIG
            print("[DEBUG bootstrap] Phase 1: Loading config...")
            await self._load_config()

            # Phase 2: Logging
            self.state = BootstrapState.INITIALIZING_LOGGING
            print("[DEBUG bootstrap] Phase 2: Initializing logging...")
            await self._init_logging()

            # Phase 3: Tracing
            if self.config.init_tracing:
                self.state = BootstrapState.INITIALIZING_TRACING
                print("[DEBUG bootstrap] Phase 3: Initializing tracing...")
                await self._init_tracing()

            # Phase 4: Metrics
            if self.config.init_metrics:
                self.state = BootstrapState.INITIALIZING_METRICS
                print("[DEBUG bootstrap] Phase 4: Initializing metrics...")
                await self._init_metrics()

            # Phase 5: Transport
            self.state = BootstrapState.CONNECTING_TRANSPORT
            print("[DEBUG bootstrap] Phase 5: Connecting transport...")
            await self._connect_transport()

            # Phase 6: Tools
            self.state = BootstrapState.LOADING_TOOLS
            print("[DEBUG bootstrap] Phase 6: Loading tools...")
            await self._load_tools()

            # Phase 7: Skills
            if self.config.load_skills:
                self.state = BootstrapState.LOADING_SKILLS
                print("[DEBUG bootstrap] Phase 7: Loading skills...")
                await self._load_skills()

            # Phase 8: Session
            if self.config.restore_session:
                self.state = BootstrapState.RESTORING_SESSION
                print("[DEBUG bootstrap] Phase 8: Restoring session...")
                await self._restore_session()

            # Complete
            self.state = BootstrapState.READY
            duration = (time.time() - self._start_time) * 1000
            print(f"[DEBUG bootstrap] === Bootstrap 完成 | duration={duration:.1f}ms ===")
            return BootstrapResult(
                success=True,
                state=self.state,
                duration_ms=duration,
                initialized_components=self._components,
            )

        except Exception as e:
            print(f"[DEBUG bootstrap] Bootstrap 失败: {e}")
            self.logger.error(f"Bootstrap failed: {e}")
            self.state = BootstrapState.FAILED
            return BootstrapResult(
                success=False,
                state=self.state,
                duration_ms=(time.time() - self._start_time) * 1000,
                error=str(e),
            )

    async def _load_config(self) -> None:
        """Load configuration from file"""
        self.logger.info("Loading configuration...")

        # Look for config file in current directory and parent directories
        config_paths = [
            self.config.config_file,
            os.path.join(os.getcwd(), self.config.config_file),
            os.path.expanduser(f"~/.claw/{self.config.config_file}"),
        ]

        config_data = {}
        for path in config_paths:
            if os.path.exists(path):
                try:
                    import json
                    with open(path) as f:
                        config_data = json.load(f)
                    self.logger.info(f"Loaded config from {path}")
                    break
                except Exception as e:
                    self.logger.warning(f"Failed to load config from {path}: {e}")

        self._components["config"] = config_data

    async def _init_logging(self) -> None:
        """Initialize logging system"""
        self.logger.info("Initializing logging...")

        from ..observability.logger import StructuredLogger, LogLevel

        structured_logger = StructuredLogger(
            name="agent_framework",
            level=LogLevel.INFO,
        )

        self._components["logger"] = structured_logger
        self.logger.info("Logging initialized")

    async def _init_tracing(self) -> None:
        """Initialize distributed tracing"""
        self.logger.info("Initializing tracing...")

        from ..observability.tracing import Tracing, get_tracing

        tracing = get_tracing()
        self._components["tracing"] = tracing

        self.logger.info("Tracing initialized")

    async def _init_metrics(self) -> None:
        """Initialize metrics collection"""
        self.logger.info("Initializing metrics...")

        from ..observability.metrics import MetricsCollector, get_metrics

        metrics = get_metrics()
        self._components["metrics"] = metrics

        self.logger.info("Metrics initialized")

    async def _connect_transport(self) -> None:
        """Connect to LLM transport adapter"""
        self.logger.info("Connecting to transport...")

        # In production, this would initialize the transport adapter
        # (Anthropic, OpenAI, etc.)
        from ..core import client, MODEL

        self._components["transport"] = {
            "client": client,
            "model": MODEL,
        }

        self.logger.info(f"Transport connected (model: {MODEL})")

    async def _load_tools(self) -> None:
        """Load tool registry"""
        self.logger.info("Loading tools...")

        from ..core import ToolRegistry

        registry = ToolRegistry()
        self._components["tools"] = registry

        self.logger.info(f"Loaded {len(registry.list_tools())} tools")

    async def _load_skills(self) -> None:
        """Load skill system"""
        self.logger.info("Loading skills...")

        try:
            from ..skills import get_registry

            registry = get_registry()
            skill_count = len(registry.list())
            self._components["skills"] = registry

            self.logger.info(f"Loaded {skill_count} skills")
        except Exception as e:
            self.logger.warning(f"Skill loading failed: {e}")
            self._components["skills"] = None

    async def _restore_session(self) -> None:
        """Restore previous session if available"""
        self.logger.info("Restoring session...")

        # Session restoration would go here
        # For now, just mark as complete
        self._components["session"] = None

        self.logger.info("Session restoration complete")

    def get_component(self, name: str) -> Optional[Any]:
        """Get an initialized component by name

        Args:
            name: Component name

        Returns:
            Component instance or None
        """
        return self._components.get(name)

    def get_state(self) -> BootstrapState:
        """Get current bootstrap state"""
        return self.state


class Shutdown:
    """Graceful shutdown handler"""

    def __init__(self, bootstrap: Bootstrap):
        self.bootstrap = bootstrap
        self._shutdown_started: float = 0
        self._timeout_seconds: float = 30.0

    async def run(self) -> None:
        """Run graceful shutdown"""
        self._shutdown_started = time.time()
        logger = logging.getLogger("shutdown")

        logger.info("Starting graceful shutdown...")

        # Phase 1: Stop accepting new requests
        logger.info("Phase 1: Stopping new requests...")

        # Phase 2: Save state
        logger.info("Phase 2: Saving state...")
        await self._save_state()

        # Phase 3: Close connections
        logger.info("Phase 3: Closing connections...")
        await self._close_connections()

        # Phase 4: Cleanup
        logger.info("Phase 4: Cleanup...")
        await self._cleanup()

        duration = time.time() - self._shutdown_started
        logger.info(f"Shutdown complete in {duration:.2f}s")

    async def _save_state(self) -> None:
        """Save current state"""
        # Save session, metrics, etc.
        pass

    async def _close_connections(self) -> None:
        """Close all connections"""
        # Close transport, channels, etc.
        pass

    async def _cleanup(self) -> None:
        """Cleanup resources"""
        # Remove temp files, close handles, etc.
        pass


# Global bootstrap instance
_bootstrap: Optional[Bootstrap] = None


def get_bootstrap() -> Bootstrap:
    """Get the global bootstrap instance"""
    global _bootstrap
    if _bootstrap is None:
        _bootstrap = Bootstrap()
    return _bootstrap