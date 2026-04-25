"""Docker Sandbox

Provides Docker-based isolated execution environment.
"""

import asyncio
import json
import time
from typing import Dict, Optional, List
from dataclasses import dataclass, field


@dataclass
class DockerConfig:
    """Configuration for Docker sandbox"""
    image: str = "python:3.11-slim"
    cpu_limit: float = 1.0
    memory_limit: str = "512m"
    network_disabled: bool = True
    read_only: bool = True
    max_duration_seconds: int = 300


@dataclass
class DockerResult:
    """Result of Docker execution"""
    container_id: str
    exit_code: int
    output: str
    duration_ms: float
    timed_out: bool = False

    @property
    def success(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


class DockerSandbox:
    """Docker-based sandbox

    Creates isolated containers for code execution.
    """

    def __init__(self, config: DockerConfig = None):
        self.config = config or DockerConfig()
        self._client = None
        self._container = None

    def _get_client(self):
        """Get or create Docker client"""
        if self._client is None:
            import docker
            self._client = docker.from_env()
        return self._client

    async def create(self, container_name: str = None) -> str:
        """Create a new container

        Args:
            container_name: Optional name for container

        Returns:
            Container ID
        """
        client = self._get_client()

        container_config = {
            "image": self.config.image,
            "detach": True,
            "cpu_period": 100000,
            "cpu_quota": int(100000 * self.config.cpu_limit),
            "mem_limit": self.config.memory_limit,
            "network_disabled": self.config.network_disabled,
            "read_only": self.config.read_only,
            "tty": True,
            "stdin_open": True,
        }

        if container_name:
            container_config["name"] = container_name

        loop = asyncio.get_event_loop()
        self._container = await loop.run_in_executor(
            None,
            lambda: client.containers.create(**container_config)
        )
        await loop.run_in_executor(None, self._container.start)
        return self._container.id

    async def execute(
        self,
        code: str,
        language: str = "python",
        timeout: int = None,
    ) -> DockerResult:
        """Execute code in the container

        Args:
            code: Code to execute
            language: Programming language (python, node, bash)
            timeout: Timeout in seconds

        Returns:
            DockerResult with execution details
        """
        if not self._container:
            return DockerResult(
                container_id="",
                exit_code=-1,
                output="",
                duration_ms=0,
                timed_out=False,
            )

        timeout = timeout or self.config.max_duration_seconds

        # Build execution command
        if language == "python":
            exec_command = f"python3 -c '{self._escape_code(code)}'"
        elif language == "node":
            exec_command = f"node -e '{self._escape_code(code)}'"
        else:
            exec_command = f"bash -c '{self._escape_code(code)}'"

        start_time = time.time()

        try:
            loop = asyncio.get_event_loop()
            result = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: self._container.exec_run(
                        exec_command,
                        demux=False,
                    )
                ),
                timeout=timeout
            )

            duration_ms = (time.time() - start_time) * 1000

            # Handle different result formats
            output = result.output.decode("utf-8", errors="replace") if isinstance(result.output, bytes) else str(result.output)

            return DockerResult(
                container_id=self._container.id,
                exit_code=result.exit_code,
                output=output,
                duration_ms=duration_ms,
                timed_out=False,
            )

        except asyncio.TimeoutError:
            duration_ms = (time.time() - start_time) * 1000
            return DockerResult(
                container_id=self._container.id,
                exit_code=-1,
                output="Execution timed out",
                duration_ms=duration_ms,
                timed_out=True,
            )

        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            return DockerResult(
                container_id=self._container.id,
                exit_code=-1,
                output=str(e),
                duration_ms=duration_ms,
            )

    def _escape_code(self, code: str) -> str:
        """Escape code for shell embedding"""
        return code.replace("'", "'\"'\"'")

    async def destroy(self) -> None:
        """Destroy the container"""
        if self._container:
            try:
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, self._container.stop)
                await loop.run_in_executor(None, self._container.remove)
            except Exception:
                pass
            self._container = None

    async def list_containers(label: str = "agent_framework") -> List[Dict]:
        """List all agent framework containers

        Args:
            label: Container label to filter by

        Returns:
            List of container info dicts
        """
        try:
            import docker
            client = docker.from_env()
            containers = client.containers.list(
                filters={"label": f"{label}=true"}
            )
            return [
                {
                    "id": c.id,
                    "name": c.name,
                    "status": c.status,
                    "created": c.attrs.get("Created", ""),
                }
                for c in containers
            ]
        except Exception:
            return []

    @staticmethod
    async def prune_containers(label: str = "agent_framework") -> int:
        """Remove all stopped containers with the given label

        Args:
            label: Container label to filter by

        Returns:
            Number of containers removed
        """
        try:
            import docker
            client = docker.from_env()
            containers = client.containers.list(
                all=True,
                filters={"label": f"{label}=true"}
            )

            count = 0
            for c in containers:
                if c.status != "running":
                    c.remove()
                    count += 1

            return count
        except Exception:
            return 0


# Global docker sandbox factory
def create_docker_sandbox(config: DockerConfig = None) -> DockerSandbox:
    """Create a new Docker sandbox instance

    Args:
        config: Docker configuration

    Returns:
        New DockerSandbox instance
    """
    return DockerSandbox(config)