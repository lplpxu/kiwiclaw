"""SSH Sandbox

Provides remote execution via SSH connection.
"""

import asyncio
import socket
import time
from typing import Dict, Optional, List
from dataclasses import dataclass, field

try:
    import asyncssh
    ASYNCSSH_AVAILABLE = True
except ImportError:
    asyncssh = None
    ASYNCSSH_AVAILABLE = False


@dataclass
class SSHConfig:
    """Configuration for SSH sandbox"""
    host: str = "localhost"
    port: int = 22
    username: str = ""
    password: str = ""
    key_filename: str = ""
    known_hosts: str = ""
    command_prefix: str = ""
    max_output_size: int = 1024 * 1024  # 1MB


@dataclass
class SSHResult:
    """Result of SSH execution"""
    command: str
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: float
    connection_error: bool = False

    @property
    def success(self) -> bool:
        return self.exit_code == 0 and not self.connection_error


class SSHSandbox:
    """SSH-based remote sandbox

    Executes commands on a remote server via SSH.
    """

    def __init__(self, config: SSHConfig = None):
        self.config = config or SSHConfig()
        self._connection = None  # type: Optional[any]
        self._connected: bool = False

    async def connect(self, timeout: float = 30.0) -> bool:
        """Connect to SSH server

        Args:
            timeout: Connection timeout in seconds

        Returns:
            True if connected successfully
        """
        if not ASYNCSSH_AVAILABLE:
            raise ImportError("asyncssh is not installed. Install with: pip install asyncssh")

        if self._connected and self._connection:
            return True

        try:
            connect_kwargs = {
                "host": self.config.host,
                "port": self.config.port,
                "username": self.config.username,
                "known_hosts": self.config.known_hosts or None,
                "server_host_key_algs": ["ssh-rsa", "rsa-sha2-256", "rsa-sha2-512"],
            }

            if self.config.password:
                connect_kwargs["password"] = self.config.password
            elif self.config.key_filename:
                connect_kwargs["client_keys"] = [self.config.key_filename]

            self._connection = await asyncio.wait_for(
                asyncssh.connect(**connect_kwargs),
                timeout=timeout
            )
            self._connected = True
            return True

        except Exception as e:
            self._connected = False
            raise ConnectionError(f"SSH connection failed: {e}")

    async def disconnect(self) -> None:
        """Disconnect from SSH server"""
        if self._connection:
            self._connection.close()
            await self._connection.wait_closed()
            self._connection = None
            self._connected = False

    async def execute(
        self,
        command: str,
        timeout: float = None,
        cwd: str = None,
    ) -> SSHResult:
        """Execute a command via SSH

        Args:
            command: Command to execute
            timeout: Timeout in seconds
            cwd: Working directory

        Returns:
            SSHResult with execution details
        """
        if not self._connected or not self._connection:
            return SSHResult(
                command=command,
                exit_code=-1,
                stdout="",
                stderr="Not connected",
                duration_ms=0,
                connection_error=True,
            )

        # Build full command
        full_command = command
        if cwd:
            full_command = f"cd {cwd} && {full_command}"
        if self.config.command_prefix:
            full_command = f"{self.config.command_prefix} {full_command}"

        start_time = time.time()

        try:
            result = await asyncio.wait_for(
                self._connection.run(
                    full_command,
                    check=False,
                    timeout=timeout,
                ),
                timeout=timeout + 5 if timeout else None
            )

            duration_ms = (time.time() - start_time) * 1000

            # Truncate output if too large
            stdout = result.stdout or ""
            stderr = result.stderr or ""

            if len(stdout) > self.config.max_output_size:
                stdout = stdout[:self.config.max_output_size] + "\n[output truncated]"
            if len(stderr) > self.config.max_output_size:
                stderr = stderr[:self.config.max_output_size] + "\n[output truncated]"

            return SSHResult(
                command=command,
                exit_code=result.exit_status,
                stdout=stdout,
                stderr=stderr,
                duration_ms=duration_ms,
            )

        except asyncio.TimeoutError:
            duration_ms = (time.time() - start_time) * 1000
            return SSHResult(
                command=command,
                exit_code=-1,
                stdout="",
                stderr=f"Command timed out after {timeout}s",
                duration_ms=duration_ms,
            )

        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            return SSHResult(
                command=command,
                exit_code=-1,
                stdout="",
                stderr=str(e),
                duration_ms=duration_ms,
                connection_error=True,
            )

    async def upload_file(
        self,
        local_path: str,
        remote_path: str,
    ) -> bool:
        """Upload a file to the remote server

        Args:
            local_path: Local file path
            remote_path: Remote destination path

        Returns:
            True if successful
        """
        if not self._connected or not self._connection:
            return False

        try:
            await asyncssh.scp(local_path, (self._connection, remote_path))
            return True
        except Exception:
            return False

    async def download_file(
        self,
        remote_path: str,
        local_path: str,
    ) -> bool:
        """Download a file from the remote server

        Args:
            remote_path: Remote file path
            local_path: Local destination path

        Returns:
            True if successful
        """
        if not self._connected or not self._connection:
            return False

        try:
            await asyncssh.scp((self._connection, remote_path), local_path)
            return True
        except Exception:
            return False

    def is_connected(self) -> bool:
        """Check if connected"""
        return self._connected and self._connection is not None


class SSHConnectionPool:
    """Pool of SSH connections for reuse"""

    def __init__(self, max_connections: int = 5):
        self.max_connections = max_connections
        self._pool: List[SSHSandbox] = []
        self._available: List[SSHSandbox] = []
        self._lock: asyncio.Lock = None

    async def initialize(self) -> None:
        """Initialize the connection pool"""
        self._lock = asyncio.Lock()

    async def acquire(self, config: SSHConfig) -> SSHSandbox:
        """Acquire a connection from the pool

        Args:
            config: SSH configuration for connection

        Returns:
            SSHSandbox instance
        """
        async with self._lock:
            # Try to find an available connection with matching config
            for sandbox in self._available:
                if self._configs_match(sandbox.config, config):
                    self._available.remove(sandbox)
                    return sandbox

            # Create new connection
            if len(self._pool) < self.max_connections:
                sandbox = SSHSandbox(config)
                await sandbox.connect()
                self._pool.append(sandbox)
                return sandbox

            # Wait for an available connection
            raise Exception("SSH connection pool exhausted")

    async def release(self, sandbox: SSHSandbox) -> None:
        """Release a connection back to the pool

        Args:
            sandbox: SSHSandbox to release
        """
        async with self._lock:
            if sandbox in self._pool and sandbox not in self._available:
                self._available.append(sandbox)

    async def close_all(self) -> None:
        """Close all connections in the pool"""
        async with self._lock:
            for sandbox in self._pool:
                await sandbox.disconnect()
            self._pool.clear()
            self._available.clear()

    def _configs_match(self, config1: SSHConfig, config2: SSHConfig) -> bool:
        """Check if two SSH configs match"""
        return (
            config1.host == config2.host and
            config1.port == config2.port and
            config1.username == config2.username
        )


# Global SSH sandbox
_ssh_sandbox: Optional[SSHSandbox] = None


def get_ssh_sandbox(config: SSHConfig = None) -> SSHSandbox:
    """Get or create a global SSH sandbox

    Args:
        config: SSH configuration (uses default if None)

    Returns:
        SSHSandbox instance
    """
    global _ssh_sandbox
    if _ssh_sandbox is None:
        _ssh_sandbox = SSHSandbox(config)
    return _ssh_sandbox