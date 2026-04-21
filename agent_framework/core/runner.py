"""Agent runner for managing agent lifecycle"""
import asyncio
from typing import Optional, Dict, Any
from .agent import Agent
from .sandbox import DockerSandbox, SandboxConfig


class AgentRunner:
    """Manages agent lifecycle and execution"""

    def __init__(self, agent: Agent, sandbox_config: Optional[SandboxConfig] = None):
        self.agent = agent
        self.sandbox: Optional[DockerSandbox] = None
        self.sandbox_config = sandbox_config
        self._running = False

    async def start(self) -> None:
        """Start the agent runner"""
        self._running = True
        if self.agent.config.sandbox_enabled and self.sandbox_config:
            self.sandbox = DockerSandbox(self.sandbox_config)
            await self.sandbox.create()

    async def stop(self) -> None:
        """Stop the agent runner"""
        self._running = False
        if self.sandbox:
            await self.sandbox.destroy()
            self.sandbox = None

    async def run_task(self, prompt: str) -> str:
        """Run a single task"""
        return await self.agent.think(prompt)

    async def run_loop(self, prompts: list[str]) -> list[str]:
        """Run multiple tasks"""
        results = []
        for prompt in prompts:
            if not self._running:
                break
            result = await self.run_task(prompt)
            results.append(result)
        return results


class MultiAgentRunner:
    """Manages multiple agents working together"""

    def __init__(self):
        self.agents: Dict[str, Agent] = {}
        self.runners: Dict[str, AgentRunner] = {}

    def add_agent(self, name: str, agent: Agent, sandbox_config: Optional[SandboxConfig] = None) -> None:
        self.agents[name] = agent
        self.runners[name] = AgentRunner(agent, sandbox_config)

    async def start_all(self) -> None:
        for runner in self.runners.values():
            await runner.start()

    async def stop_all(self) -> None:
        for runner in self.runners.values():
            await runner.stop()

    async def run_task(self, agent_name: str, prompt: str) -> str:
        if agent_name not in self.runners:
            raise ValueError(f"Agent '{agent_name}' not found")
        return await self.runners[agent_name].run_task(prompt)