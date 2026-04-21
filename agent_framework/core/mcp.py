"""MCP protocol support for Agent Framework"""
import asyncio
import json
import subprocess
from typing import Any, Dict, List, Optional, Callable
from dataclasses import dataclass


@dataclass
class MCPResource:
    name: str
    description: str
    uri_pattern: str


@dataclass
class MCPTool:
    name: str
    description: str
    input_schema: Dict[str, Any]


class MCPServer:
    """MCP server base class"""

    def __init__(self, name: str):
        self.name = name
        self.tools: List[MCPTool] = []
        self.resources: List[MCPResource] = []

    def add_tool(self, tool: MCPTool) -> None:
        self.tools.append(tool)

    def tool(self, name: str, description: str, input_schema: Dict[str, Any]) -> Callable:
        """Decorator to add a tool"""
        def decorator(func: Callable) -> Callable:
            self.tools.append(MCPTool(name, description, input_schema))
            return func
        return decorator

    async def start(self) -> subprocess.Popen:
        """Start the MCP server as a subprocess"""
        raise NotImplementedError

    def get_manifest(self) -> Dict[str, Any]:
        """Get MCP server manifest"""
        return {
            "name": self.name,
            "tools": [{"name": t.name, "description": t.description, "input_schema": t.input_schema} for t in self.tools],
            "resources": [{"name": r.name, "description": r.description, "uri_pattern": r.uri_pattern} for r in self.resources]
        }


class MCPClient:
    """MCP client for connecting to MCP servers"""

    def __init__(self):
        self.servers: Dict[str, subprocess.Popen] = {}
        self._callbacks: Dict[str, Callable] = {}

    async def connect(self, name: str, command: str, args: List[str] = None, env: Dict[str, str] = None) -> None:
        """Connect to an MCP server"""
        cmd = [command] + (args or [])
        process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env or {}
        )
        self.servers[name] = process

    async def disconnect(self, name: str) -> None:
        """Disconnect from an MCP server"""
        if name in self.servers:
            self.servers[name].terminate()
            del self.servers[name]

    async def call_tool(self, server_name: str, tool_name: str, arguments: Dict[str, Any]) -> Any:
        """Call a tool on an MCP server"""
        if server_name not in self.servers:
            raise ValueError(f"MCP server '{server_name}' not connected")

        request = {
            "jsonrpc": "2.0",
            "id": str(asyncio.get_event_loop().time()),
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments}
        }

        process = self.servers[server_name]
        process.stdin.write(json.dumps(request).encode())
        process.stdin.write(b"\n")
        process.stdin.flush()

        response_line = await asyncio.get_event_loop().run_in_executor(
            None, process.stdout.readline
        )
        if response_line:
            response = json.loads(response_line)
            return response.get("result")


class MCPServerStdio(MCPServer):
    """MCP server using stdio transport"""

    def __init__(self, name: str, command: str, args: List[str] = None, env: Dict[str, str] = None):
        super().__init__(name)
        self.command = command
        self.args = args or []
        self.env = env or {}
        self._process: Optional[subprocess.Popen] = None

    async def start(self) -> None:
        """Start the MCP server"""
        self._process = subprocess.Popen(
            [self.command] + self.args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self.env
        )

    async def stop(self) -> None:
        """Stop the MCP server"""
        if self._process:
            self._process.terminate()
            self._process = None

    async def send_request(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Send a JSON-RPC request"""
        if not self._process:
            raise RuntimeError("MCP server not started")

        request = {
            "jsonrpc": "2.0",
            "id": str(asyncio.get_event_loop().time()),
            "method": method,
            "params": params
        }

        self._process.stdin.write(json.dumps(request).encode())
        self._process.stdin.write(b"\n")
        self._process.stdin.flush()

        response_line = await asyncio.get_event_loop().run_in_executor(
            None, self._process.stdout.readline
        )
        return json.loads(response_line) if response_line else {}

    async def list_tools(self) -> List[MCPTool]:
        """List available tools"""
        response = await self.send_request("tools/list", {})
        return [MCPTool(**t) for t in response.get("tools", [])]

    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        """Call a tool"""
        response = await self.send_request("tools/call", {
            "name": tool_name,
            "arguments": arguments
        })
        return response.get("result")