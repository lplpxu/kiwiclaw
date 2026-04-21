"""Docker sandbox for safe agent execution"""
import asyncio
import uuid
from typing import Optional, Dict, Any
from dataclasses import dataclass
import docker


@dataclass
class SandboxConfig:
    image: str = "python:3.11-slim"
    cpu_limit: str = "1.0"
    memory_limit: str = "512m"
    network_disabled: bool = False
    read_only_root: bool = True
    timeout: int = 300


class DockerSandbox:
    """Docker-based sandbox for running untrusted code"""

    def __init__(self, config: SandboxConfig):
        self.config = config
        self.client: Optional[docker.DockerClient] = None
        self.container = None
        self.container_id = None

    async def create(self) -> str:
        """Create a new sandbox container"""
        loop = asyncio.get_event_loop()
        self.client = docker.from_env()

        container_config = {
            "image": self.config.image,
            "detach": True,
            "cpu_period": 100000,
            "cpu_quota": int(100000 * float(self.config.cpu_limit)),
            "mem_limit": self.config.memory_limit,
            "network_disabled": self.config.network_disabled,
            "read_only": self.config.read_only_root,
            "tty": True,
            "stdin_open": True,
        }

        self.container = await loop.run_in_executor(
            None, lambda: self.client.containers.create(**container_config)
        )
        self.container_id = self.container.id
        await loop.run_in_executor(None, self.container.start)
        return self.container_id

    async def execute(self, code: str, timeout: Optional[int] = None) -> Dict[str, Any]:
        """Execute code in the sandbox"""
        if not self.container:
            return {"error": "Sandbox not created"}

        timeout = timeout or self.config.timeout
        escaped_code = code.replace("'", "'\"'\"'")

        exec_command = f"python3 -c '{escaped_code}'"

        try:
            loop = asyncio.get_event_loop()
            result = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: self.container.exec_run(exec_command, workdir="/workspace")
                ),
                timeout=timeout
            )
            return {
                "exit_code": result.exit_code,
                "output": result.output.decode("utf-8", errors="replace"),
                "error": None if result.exit_code == 0 else "Execution failed"
            }
        except asyncio.TimeoutError:
            return {"error": "Execution timed out", "exit_code": -1}
        except Exception as e:
            return {"error": str(e), "exit_code": -1}

    async def destroy(self) -> None:
        """Destroy the sandbox container"""
        if self.container:
            try:
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, self.container.stop)
                await loop.run_in_executor(None, self.container.remove)
            except Exception:
                pass
            self.container = None
            self.container_id = None

    @staticmethod
    async def list_containers() -> list[Dict[str, Any]]:
        """List all agent framework containers"""
        try:
            client = docker.from_env()
            containers = client.containers.list(
                filters={"label": "agent_framework=true"}
            )
            return [{"id": c.id, "name": c.name, "status": c.status} for c in containers]
        except Exception:
            return []


class SandboxedTool:
    """Wrapper to execute tools in a sandbox"""

    def __init__(self, sandbox: DockerSandbox):
        self.sandbox = sandbox

    async def execute_tool(self, tool_name: str, code: str) -> Dict[str, Any]:
        """Execute a tool in the sandbox"""
        result = await self.sandbox.execute(code)
        result["tool"] = tool_name
        return result