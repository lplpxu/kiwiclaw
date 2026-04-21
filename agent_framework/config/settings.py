"""Configuration management for Agent Framework"""
import os
from dataclasses import dataclass, field
from typing import Optional, Dict, Any

# Load .env file
from dotenv import load_dotenv
load_dotenv(override=True)


@dataclass
class AgentConfig:
    name: str = "agent"
    model: str = os.getenv("MODEL_ID", "claude-sonnet-4-20250514")
    max_tokens: int = 8192
    temperature: float = 1.0
    system_prompt: Optional[str] = None
    tools: list = field(default_factory=list)
    sandbox_enabled: bool = False
    mode: str = "simple"  # simple, deep, plan, debug


@dataclass
class SandboxConfig:
    image: str = "python:3.11-slim"
    cpu_limit: str = "1.0"
    memory_limit: str = "512m"
    network_disabled: bool = False
    read_only_root: bool = True


@dataclass
class MCPConfig:
    command: str
    args: list = field(default_factory=list)
    env: Dict[str, str] = field(default_factory=dict)


@dataclass
class Settings:
    anthropic_api_key: Optional[str] = None
    minimax_api_key: Optional[str] = None
    docker_host: str = "unix:///var/run/docker.sock"
    work_dir: str = ".workdir"
    transcript_dir: str = ".transcripts"
    task_dir: str = ".tasks"
    team_dir: str = ".team"
    inbox_dir: str = "inbox"

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY"),
            minimax_api_key=os.getenv("MINIMAX_API_KEY"),
            docker_host=os.getenv("DOCKER_HOST", "unix:///var/run/docker.sock"),
            work_dir=os.getenv("AGENT_WORK_DIR", ".workdir"),
        )


settings = Settings.from_env()