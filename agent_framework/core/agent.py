"""Agent base class for Agent Framework"""
import asyncio
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field
from .tool import Tool, ToolRegistry
from ..config import AgentConfig


@dataclass
class Message:
    role: str
    content: str
    tool_calls: Optional[List[Dict]] = None
    tool_results: Optional[List[Dict]] = None


@dataclass
class Agent:
    name: str
    config: AgentConfig
    tools: List[Tool] = field(default_factory=list)
    messages: List[Message] = field(default_factory=list)
    _client = None

    def __post_init__(self):
        self._registry = ToolRegistry()
        for t in self.tools:
            self._registry.register(t)

    def use_mcp(self, mcp_server) -> "Agent":
        """Attach an MCP server to this agent"""
        for tool in mcp_server.tools:
            self._registry.register(tool)
        return self

    async def think(self, prompt: str) -> str:
        """Main agent thinking loop - to be implemented with LLM"""
        raise NotImplementedError("Subclasses must implement think()")

    def add_message(self, role: str, content: str) -> None:
        self.messages.append(Message(role=role, content=content))

    def get_tools_schema(self) -> List[Dict]:
        """Get tools in Anthropic format"""
        tools = []
        for t in self._registry.list_tools():
            if t.enabled:
                tools.append({
                    "name": t.name,
                    "description": t.description,
                    "input_schema": t.input_schema
                })
        return tools

    def call_tool(self, name: str, **kwargs) -> Any:
        """Call a registered tool"""
        tool = self._registry.get(name)
        if not tool:
            return {"error": f"Tool '{name}' not found"}
        if not tool.enabled:
            return {"error": f"Tool '{name}' is disabled"}
        try:
            result = tool.handler(**kwargs)
            if asyncio.iscoroutine(result):
                return asyncio.run(result)
            return result
        except Exception as e:
            return {"error": str(e)}


class CliAgent(Agent):
    """CLI-based agent using Anthropic API"""

    def __init__(self, name: str = "cli-agent", config: Optional[AgentConfig] = None):
        config = config or AgentConfig(name=name)
        super().__init__(name, config)
        self._setup_anthropic()

    def _setup_anthropic(self):
        from anthropic import Anthropic
        api_key = self.config.system_prompt  # We'll use env var instead
        self._client = Anthropic()

    async def think(self, prompt: str) -> str:
        """Call Anthropic API"""
        self.add_message("user", prompt)

        response = self._client.messages.create(
            model=self.config.model,
            max_tokens=self.config.max_tokens,
            messages=[{"role": m.role, "content": m.content} for m in self.messages],
            tools=self.get_tools_schema()
        )

        response_content = ""
        for block in response.content:
            if block.type == "text":
                response_content += block.text
            elif block.type == "tool_use":
                tool_name = block.name
                tool_input = block.input
                result = self.call_tool(tool_name, **tool_input)
                self.messages.append(Message(
                    role="user",
                    content=f"Tool result: {result}",
                    tool_results=[{"tool_use_id": block.id, "content": str(result)}]
                ))

        self.add_message("assistant", response_content)
        return response_content