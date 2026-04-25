"""Bash Sandbox

Provides local bash execution in a restricted environment.
"""

import asyncio
import subprocess
import os
import threading
import time
from typing import Dict, Optional, List, Callable
from dataclasses import dataclass, field
from enum import Enum


class SandboxPermission(Enum):
    """Permission levels for bash sandbox"""
    NONE = "none"
    READ_ONLY = "read_only"
    WRITE = "write"
    EXECUTE = "execute"
    FULL = "full"


@dataclass
class BashResult:
    """Result of bash execution"""
    command: str
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: float
    timed_out: bool = False

    @property
    def success(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


@dataclass
class BashSandboxConfig:
    """Configuration for bash sandbox"""
    allowed_paths: List[str] = field(default_factory=list)
    blocked_commands: List[str] = field(default_factory=lambda: ["rm", "dd", "mkfs", ":(){:|:&};:", "fork", "kill"])
    max_output_size: int = 1024 * 1024  # 1MB
    max_duration_ms: float = 30000
    permission_level: SandboxPermission = SandboxPermission.FULL


class BashSandbox:
    """Bash execution sandbox

    Executes bash commands in a restricted environment with
    configurable permissions and timeout.
    """

    def __init__(self, config: BashSandboxConfig = None):
        self.config = config or BashSandboxConfig()
        self._env: Dict[str, str] = {}
        self._setup_environment()

    def _setup_environment(self) -> None:
        """Setup restricted environment variables"""
        self._env = {
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "HOME": os.path.expanduser("~"),
            "LANG": "en_US.UTF-8",
        }

    def _is_command_blocked(self, command: str) -> bool:
        """Check if command contains blocked patterns"""
        cmd_lower = command.lower()
        for blocked in self.config.blocked_commands:
            if blocked.lower() in cmd_lower:
                return True
        return False

    def _prepare_command(self, command: str) -> str:
        """Prepare command for safe execution"""
        # Remove newlines and excessive whitespace
        command = " ".join(command.split())

        # Add timeout wrapper
        return f"timeout {self.config.max_duration_ms / 1000}s {command} 2>&1"

    async def execute(
        self,
        command: str,
        timeout_ms: float = None,
        cwd: str = None,
    ) -> BashResult:
        """Execute a bash command

        Args:
            command: Command to execute
            timeout_ms: Timeout in milliseconds (uses config default if None)
            cwd: Working directory

        Returns:
            BashResult with execution details
        """
        timeout_ms = timeout_ms or self.config.max_duration_ms

        # Check for blocked commands
        if self._is_command_blocked(command):
            return BashResult(
                command=command,
                exit_code=1,
                stdout="",
                stderr=f"Command contains blocked patterns",
                duration_ms=0,
            )

        start_time = time.time()
        prepared = self._prepare_command(command)

        try:
            proc = await self._run_process(
                prepared,
                timeout_ms / 1000,
                cwd,
            )

            duration_ms = (time.time() - start_time) * 1000

            # Truncate output if too large
            stdout = proc.stdout
            stderr = proc.stderr
            if len(stdout) > self.config.max_output_size:
                stdout = stdout[:self.config.max_output_size] + "\n[output truncated]"
            if len(stderr) > self.config.max_output_size:
                stderr = stderr[:self.config.max_output_size] + "\n[output truncated]"

            return BashResult(
                command=command,
                exit_code=proc.exit_code,
                stdout=stdout,
                stderr=stderr,
                duration_ms=duration_ms,
                timed_out=proc.exit_code == 124,  # timeout uses 124
            )

        except Exception as e:
            return BashResult(
                command=command,
                exit_code=-1,
                stdout="",
                stderr=str(e),
                duration_ms=(time.time() - start_time) * 1000,
            )

    async def _run_process(
        self,
        command: str,
        timeout: float,
        cwd: str,
    ) -> subprocess.CompletedProcess:
        """Run subprocess with timeout"""
        loop = asyncio.get_event_loop()

        def run():
            return subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=cwd,
                env=self._env,
            )

        return await loop.run_in_executor(None, run)

    def set_environment_var(self, key: str, value: str) -> None:
        """Set an environment variable for executions"""
        self._env[key] = value

    def get_environment_var(self, key: str) -> Optional[str]:
        """Get an environment variable"""
        return self._env.get(key)


# Global bash sandbox
_bash_sandbox: Optional[BashSandbox] = None


def get_bash_sandbox() -> BashSandbox:
    """Get the global bash sandbox"""
    global _bash_sandbox
    if _bash_sandbox is None:
        _bash_sandbox = BashSandbox()
    return _bash_sandbox