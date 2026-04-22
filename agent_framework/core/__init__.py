"""Agent Framework Core Module - Public API Facade"""
import os
import json
import asyncio
from pathlib import Path
from typing import Optional, Dict, Any
from dataclasses import dataclass

from dotenv import load_dotenv
load_dotenv(override=True)

# === Import from submodules ===
from ._constants import WORKDIR, TOKEN_THRESHOLD, POLL_INTERVAL, IDLE_TIMEOUT
from ._managers import (
    TodoManager, TaskManager, BackgroundManager, MessageBus,
    TODO, TASK_MGR, BG, BUS,
    estimate_tokens, microcompact, auto_compact,
)
from ._tools import (
    safe_path, run_bash, run_read, run_write, run_edit,
    run_web_search, run_web_fetch, run_judge, run_text_to_image,
)

# === Configuration ===
from ..config.settings import Settings, AgentConfig, SandboxConfig, MCPConfig, settings

# === Anthropic Client ===
from anthropic import Anthropic

api_key = os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN")
base_url = os.getenv("ANTHROPIC_BASE_URL") or os.getenv("ANTHROPIC_BASE_URL")

client = Anthropic(
    base_url=base_url if base_url else None,
    api_key=api_key
)
MODEL = os.getenv("MODEL_ID", "claude-sonnet-4-20250514")

# === Soul Prompts ===
SOUL_PROMPTS = {}


def _load_skill_content(skill_path: Path) -> tuple[str, str]:
    """Load skill content from SKILL.md. Returns (name, content) tuple."""
    try:
        content = skill_path.read_text(encoding="utf-8")
        # Extract content after YAML frontmatter (after second ---)
        parts = content.split("---")
        if len(parts) >= 3:
            skill_content = "---".join(parts[2:]).strip()
        else:
            skill_content = content.strip()

        # Get skill name from directory
        name = skill_path.parent.name.replace("-", " ").replace("_", " ")
        return name, skill_content
    except Exception:
        return "", ""


def _load_all_skills() -> str:
    """Load all skills from skills/ directory. Returns formatted skills content."""
    try:
        skills_dir = Path(__file__).parent.parent / "skills"
        if not skills_dir.exists():
            return ""

        all_skills = []
        for skill_folder in skills_dir.iterdir():
            if skill_folder.is_dir():
                skill_md = skill_folder / "SKILL.md"
                if skill_md.exists():
                    name, content = _load_skill_content(skill_md)
                    if content:
                        all_skills.append(f"# {name}\n{content}")

        if all_skills:
            return "\n\n" + "\n\n".join(all_skills)
    except Exception:
        pass
    return ""


# Cache for skills content
_SKILLS_CACHE = None
_SKILLS_LOADED = False


def _get_all_skills() -> str:
    """Get cached skills content"""
    global _SKILLS_CACHE, _SKILLS_LOADED
    if not _SKILLS_LOADED:
        _SKILLS_CACHE = _load_all_skills()
        _SKILLS_LOADED = True
    return _SKILLS_CACHE


def clear_skills_cache():
    """Clear the skills cache to force reload on next access"""
    global _SKILLS_CACHE, _SKILLS_LOADED
    _SKILLS_CACHE = None
    _SKILLS_LOADED = False


def load_soul_prompts():
    """Load prompts from soud.md file"""
    global SOUL_PROMPTS
    soul_path = WORKDIR / "soud.md"
    if not soul_path.exists():
        SOUL_PROMPTS = {
            "simple": "你是我的助手",
            "deep": "思考任务流程所涉原理和步骤，并列出来",
            "plan": "思考任务流程所涉及原理、步骤和主体，并列出来，做出计划详细步骤",
            "debug": "思考任务流程所涉及的所有主体，用三现两原原则分析问题，列出来所有主体和可能问题，逐一验证"
        }
        return

    content = soul_path.read_text(encoding="utf-8")
    current_section = None
    current_content = []

    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            if current_section is not None:
                SOUL_PROMPTS[current_section] = "\n".join(current_content).strip()
            current_section = stripped.lstrip("#").strip().lower()
            current_content = []
        elif current_section is not None:
            current_content.append(line)

    if current_section is not None:
        SOUL_PROMPTS[current_section] = "\n".join(current_content).strip()

    if "simple" not in SOUL_PROMPTS:
        SOUL_PROMPTS["simple"] = "你是我的助手"
    if "deep" not in SOUL_PROMPTS:
        SOUL_PROMPTS["deep"] = "思考任务流程所涉原理和步骤，并列出来"
    if "plan" not in SOUL_PROMPTS:
        SOUL_PROMPTS["plan"] = "思考任务流程所涉及原理、步骤和主体，并列出来，做出计划详细步骤"
    if "debug" not in SOUL_PROMPTS:
        SOUL_PROMPTS["debug"] = "思考任务流程所涉及的所有主体，用三现两原原则分析问题，列出来所有主体和可能问题，逐一验证"


# Load prompts on import
load_soul_prompts()


# === Tool Base ===
@dataclass
class Tool:
    name: str
    description: str
    input_schema: Dict[str, Any]
    handler: callable
    enabled: bool = True


# === Tool Registry (for backward compatibility) ===
class ToolRegistry:
    """Registry for tools - singleton pattern"""
    _instance = None
    _tools: Dict[str, Tool] = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def register(self, tool: Tool):
        self._tools[tool.name] = tool

    def get(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def list_tools(self) -> list:
        return list(self._tools.values())

    def unregister(self, name: str):
        if name in self._tools:
            del self._tools[name]

    def clear(self):
        self._tools.clear()


def tool(name: str = None, description: str = "", input_schema: dict = None):
    """Decorator to register a function as a tool"""
    def decorator(func):
        tool_name = name or func.__name__
        import inspect
        sig = inspect.signature(func)
        schema = input_schema or {"type": "object", "properties": {}, "required": []}
        t = Tool(
            name=tool_name,
            description=description or func.__doc__ or "",
            input_schema=schema,
            handler=func,
            enabled=True
        )
        ToolRegistry().register(t)

        # Attach attributes to function for backward compatibility
        func.name = tool_name
        func.description = description or func.__doc__ or ""
        return func
    return decorator


# === Agent ===
class Agent:
    """Agent with full tool set"""

    def __init__(self, name: str = "agent", config: Optional[AgentConfig] = None):
        self.name = name
        self.config = config or AgentConfig(name=name)
        self.messages: list = []
        self._tools = self._build_tools()
        self._tool_handlers = self._build_handlers()
        load_soul_prompts()
        self._current_mode = getattr(self.config, 'mode', 'simple')
        self._judge_fail_count = 0  # Track consecutive judge failures

    def _build_tools(self) -> list:
        return [
            {"name": "bash", "description": "Run shell command.",
             "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
            {"name": "read_file", "description": "Read file.",
             "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["path"]}},
            {"name": "write_file", "description": "Write file.",
             "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
            {"name": "edit_file", "description": "Edit file.",
             "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}}, "required": ["path", "old_text", "new_text"]}},
            {"name": "TodoWrite", "description": "Update todo list.",
             "input_schema": {"type": "object", "properties": {"items": {"type": "array", "items": {"type": "object", "properties": {"content": {"type": "string"}, "status": {"type": "string", "enum": ["pending", "in_progress", "completed"]}, "activeForm": {"type": "string"}}}}}, "required": ["items"]}},
            {"name": "task_create", "description": "Create task.",
             "input_schema": {"type": "object", "properties": {"subject": {"type": "string"}, "description": {"type": "string"}}, "required": ["subject"]}},
            {"name": "task_get", "description": "Get task.",
             "input_schema": {"type": "object", "properties": {"task_id": {"type": "integer"}}, "required": ["task_id"]}},
            {"name": "task_update", "description": "Update task.",
             "input_schema": {"type": "object", "properties": {"task_id": {"type": "integer"}, "status": {"type": "string"}}, "required": ["task_id"]}},
            {"name": "task_list", "description": "List tasks.",
             "input_schema": {"type": "object", "properties": {}}},
            {"name": "background_run", "description": "Run in background.",
             "input_schema": {"type": "object", "properties": {"command": {"type": "string"}, "timeout": {"type": "integer"}}, "required": ["command"]}},
            {"name": "check_background", "description": "Check bg task.",
             "input_schema": {"type": "object", "properties": {"task_id": {"type": "string"}}}},
            {"name": "compress", "description": "Compress context.", "input_schema": {"type": "object", "properties": {}}},
            {"name": "web_search", "description": "Search the internet to obtain the URLs needed to retrieve information.",
             "input_schema": {"type": "object", "properties": {"query": {"type": "string", "description": "搜索关键词"}, "num_results": {"type": "integer", "description": "返回结果数量", "default": 5}}, "required": ["query"]}},
            {"name": "web_fetch", "description": "Fetch URL and extract readable content (HTML to markdown/text).",
             "input_schema": {"type": "object", "properties": {
                 "url": {"type": "string", "description": "URL to fetch"},
                 "max_chars": {"type": "integer", "description": "Maximum characters to return", "default": 50000}
             }, "required": ["url"]}},
            {"name": "text_to_image", "description": "Generate image from text prompt using MiniMax AI. Returns base64 encoded image data.",
             "input_schema": {"type": "object", "properties": {
                 "prompt": {"type": "string", "description": "图像生成描述词"},
                 "aspect_ratio": {"type": "string", "description": "图片比例，如16:9, 1:1, 9:16", "default": "1:1"},
                 "output_path": {"type": "string", "description": "输出文件路径，如image.png", "default": "generated_image.png"}
             }, "required": ["prompt"]}},
        ]

    def _build_handlers(self) -> dict:
        return {
            "bash": lambda **kw: run_bash(kw["command"]),
            "read_file": lambda **kw: run_read(kw["path"], kw.get("limit")),
            "write_file": lambda **kw: run_write(kw["path"], kw["content"]),
            "edit_file": lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"]),
            "TodoWrite": lambda **kw: TODO.update(kw["items"]),
            "task_create": lambda **kw: TASK_MGR.create(kw["subject"], kw.get("description", "")),
            "task_get": lambda **kw: TASK_MGR.get(kw["task_id"]),
            "task_update": lambda **kw: TASK_MGR.update(kw["task_id"], kw.get("status")),
            "task_list": lambda **kw: TASK_MGR.list_all(),
            "background_run": lambda **kw: BG.run(kw["command"], kw.get("timeout", 120)),
            "check_background": lambda **kw: BG.check(kw.get("task_id")),
            "compress": lambda **kw: "Compressing...",
            "web_search": lambda **kw: run_web_search(kw["query"], kw.get("num_results", 5)),
            "web_fetch": lambda **kw: run_web_fetch(kw["url"], kw.get("max_chars", 50000)),
            "text_to_image": lambda **kw: run_text_to_image(kw["prompt"], kw.get("aspect_ratio", "1:1"), kw.get("output_path", "generated_image.png")),
            "judge": lambda **kw: run_judge(kw["tool_results"], kw.get("user_prompt", "")),
        }

    def get_system_prompt(self) -> str:
        mode = getattr(self.config, 'mode', 'simple')
        if mode != self._current_mode:
            load_soul_prompts()
            self._current_mode = mode
        from datetime import datetime
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        time_prefix = f"[系统时间: {current_time}]\n\n"

        # Get all skills content dynamically
        skills_content = _get_all_skills()

        if mode == 'simple':
            return time_prefix + SOUL_PROMPTS.get("simple", "你是我的助手") + skills_content
        elif mode == 'deep':
            return time_prefix + SOUL_PROMPTS.get("deep", "思考任务流程所涉原理和步骤，并列出来") + skills_content
        elif mode == 'plan':
            return time_prefix + SOUL_PROMPTS.get("plan", "思考任务流程所涉及原理、步骤和主体，并列出来，做出计划详细步骤") + skills_content
        elif mode == 'debug':
            return time_prefix + SOUL_PROMPTS.get("debug", "思考任务流程所涉及的所有主体，用三现两原原则分析问题，列出来所有主体和可能问题，逐一验证") + skills_content
        else:
            return time_prefix + SOUL_PROMPTS.get("simple", "你是我的助手") + skills_content

    async def think(self, prompt: str, status_callback=None) -> str:
        """Main thinking loop"""
        self.messages.append({"role": "user", "content": prompt})

        while True:
            if status_callback is not None:
                await status_callback("思考中...")

            microcompact(self.messages)
            if estimate_tokens(self.messages) > TOKEN_THRESHOLD:
                print("[auto-compact triggered]")
                self.messages[:] = auto_compact(self.messages, client, MODEL)

            notifs = BG.drain()
            if notifs:
                txt = "\n".join(f"[bg:{n['task_id']}] {n['status']}: {n['result']}" for n in notifs)
                self.messages.append({"role": "user", "content": f"<background-results>\n{txt}\n</background-results>"})

            llm_messages = []
            for msg in self.messages:
                if msg.get("image_data"):
                    text_content = msg.get("content", "")
                    if text_content:
                        llm_messages.append({"role": msg["role"], "content": text_content})
                elif isinstance(msg.get("content"), list):
                    text_parts = []
                    for part in msg["content"]:
                        if isinstance(part, dict) and part.get("type") == "text":
                            text_parts.append(part["text"])
                        elif isinstance(part, dict) and part.get("type") == "tool_result":
                            tool_content = part.get("content", "")
                            if tool_content:
                                text_parts.append(str(tool_content))
                    if text_parts:
                        llm_messages.append({"role": msg["role"], "content": "\n".join(text_parts)})
                else:
                    llm_messages.append(msg)

            system_msg = {"role": "system", "content": self.get_system_prompt()}
            all_messages = [system_msg] + llm_messages
            response = client.messages.create(
                model=self.config.model,
                messages=all_messages,
                tools=self._tools,
                max_tokens=8000,
            )
            self.messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason != "tool_use":
                return "".join(b.text for b in response.content if hasattr(b, 'text')) or "(no response)"

            results = []
            manual_compress = False
            image_result = None
            consecutive_tool_calls = 0
            for block in response.content:
                if block.type == "tool_use":
                    consecutive_tool_calls += 1
                    if block.name == "compress":
                        manual_compress = True
                    if status_callback is not None:
                        await status_callback(f"执行工具: {block.name}...")
                    handler = self._tool_handlers.get(block.name)
                    try:
                        output = handler(**block.input) if handler else f"Unknown tool: {block.name}"
                    except Exception as e:
                        output = f"Error: {e}"
                    output_str = str(output)[:200]
                    output_clean = output_str.encode('ascii', 'replace').decode('ascii')
                    print(f"> {block.name}: {output_clean}")

                    if block.name == "text_to_image":
                        try:
                            img_data = json.loads(output)
                            if img_data.get("type") == "image" and img_data.get("image"):
                                image_result = img_data
                        except:
                            pass

                    results.append({"type": "tool_result", "tool_use_id": block.id, "content": str(output)})

            self.messages.append({"role": "user", "content": results})

            for r in results:
                if isinstance(r, dict) and "[FATAL_ERROR]" in str(r.get("content", "")):
                    fatal_msg = r.get("content", "")
                    return f"工具执行失败:\n{fatal_msg}\n\n请根据此错误信息回复用户。"

            if image_result:
                return json.dumps(image_result)

            if manual_compress:
                print("[manual compact]")
                self.messages[:] = auto_compact(self.messages, client, MODEL)

            if consecutive_tool_calls > 0:
                if consecutive_tool_calls == 1:
                    for r in results:
                        if isinstance(r, dict) and r.get("type") == "tool_result":
                            content = str(r.get("content", ""))
                            if len(content) > 50 and "[FATAL_ERROR]" not in content and "错误:" not in content:
                                user_prompt = ""
                                for msg in reversed(self.messages[:-1]):
                                    if msg["role"] == "user" and isinstance(msg.get("content"), str):
                                        user_prompt = msg["content"]
                                        break
                                try:
                                    judge_pass, judge_advice = run_judge(content, user_prompt)
                                    print(f"[DEBUG judge] pass={judge_pass}, advice={judge_advice[:100] if judge_advice else 'empty'}")
                                    if judge_pass:
                                        # Tool results solved the problem - return to user with advice
                                        self._judge_fail_count = 0  # Reset failure count
                                        if judge_advice:
                                            self.messages.append({
                                                "role": "user",
                                                "content": f"工具结果已返回。\n\n建议：{judge_advice}"
                                            })
                                        return content
                                    else:
                                        # Tool results did NOT solve the problem
                                        self._judge_fail_count += 1
                                        print(f"[DEBUG judge] fail_count={self._judge_fail_count}")
                                        if self._judge_fail_count > 3:
                                            # More than 3 failures - give up and try different approach
                                            msg = "工具结果已多次未能解决您的问题。请放弃前面的方法，使用其他可用的资源、条件或自己创造条件来完成任务。"
                                            print(f"[DEBUG judge] Fourth failure, adding message: {msg}")
                                            self.messages.append({
                                                "role": "user",
                                                "content": msg
                                            })
                                            self._judge_fail_count = 0  # Reset after giving warning
                                        elif judge_advice:
                                            print(f"[DEBUG judge] Adding advice: {judge_advice[:100]}")
                                            self.messages.append({
                                                "role": "user",
                                                "content": f"工具结果未完全解决您的问题。\n\n建议：{judge_advice}"
                                            })
                                except Exception as e:
                                    print(f"[judge error: {e}]")
                                    # On error, assume not solved and continue
                if consecutive_tool_calls > 10:
                    print("[tool call limit reached]")
                    for r in results:
                        if isinstance(r, dict) and r.get("type") == "tool_result":
                            return str(r.get("content", ""))


# === AgentRunner ===
class AgentRunner:
    """Manages agent lifecycle"""
    def __init__(self, agent: Agent, sandbox_config: "SandboxConfig" = None):
        self.agent = agent
        self.sandbox = None
        self.sandbox_config = sandbox_config
        self._running = False

    async def start(self):
        self._running = True
        if self.agent.config.sandbox_enabled and self.sandbox_config:
            self.sandbox = DockerSandbox(self.sandbox_config)
            await self.sandbox.create()

    async def stop(self):
        self._running = False
        if self.sandbox:
            await self.sandbox.destroy()
            self.sandbox = None

    async def run_task(self, prompt: str) -> str:
        return await self.agent.think(prompt)


# === Docker Sandbox ===
import docker


@dataclass
class SandboxConfig:
    image: str = "python:3.11-slim"
    cpu_limit: str = "1.0"
    memory_limit: str = "512m"
    network_disabled: bool = False


class DockerSandbox:
    def __init__(self, config: SandboxConfig = None):
        self.config = config or SandboxConfig()
        self.client = None
        self.container = None

    async def create(self) -> str:
        self.client = docker.from_env()
        container_config = {
            "image": self.config.image,
            "detach": True,
            "cpu_period": 100000,
            "cpu_quota": int(100000 * float(self.config.cpu_limit)),
            "mem_limit": self.config.memory_limit,
            "network_disabled": self.config.network_disabled,
            "read_only": True,
            "tty": True,
            "stdin_open": True,
        }
        loop = asyncio.get_event_loop()
        self.container = await loop.run_in_executor(
            None, lambda: self.client.containers.create(**container_config)
        )
        await loop.run_in_executor(None, self.container.start)
        return self.container.id

    async def execute(self, code: str, timeout: int = 300) -> dict:
        if not self.container:
            return {"error": "Sandbox not created"}
        escaped_code = code.replace("'", "'\"'\"'")
        exec_command = f"python3 -c '{escaped_code}'"
        try:
            loop = asyncio.get_event_loop()
            result = await asyncio.wait_for(
                loop.run_in_executor(None, lambda: self.container.exec_run(exec_command)),
                timeout=timeout
            )
            return {"exit_code": result.exit_code, "output": result.output.decode("utf-8", errors="replace")}
        except asyncio.TimeoutError:
            return {"error": "Timeout", "exit_code": -1}
        except Exception as e:
            return {"error": str(e), "exit_code": -1}

    async def destroy(self):
        if self.container:
            try:
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, self.container.stop)
                await loop.run_in_executor(None, self.container.remove)
            except Exception:
                pass
            self.container = None

    @staticmethod
    async def list_containers() -> list:
        try:
            client = docker.from_env()
            containers = client.containers.list(filters={"label": "agent_framework=true"})
            return [{"id": c.id, "name": c.name, "status": c.status} for c in containers]
        except Exception:
            return []


# === MCP ===
class MCPServer:
    def __init__(self, name: str):
        self.name = name
        self.tools = []

    def add_tool(self, name: str, description: str, input_schema: dict):
        self.tools.append({"name": name, "description": description, "input_schema": input_schema})

    def get_manifest(self) -> dict:
        return {"name": self.name, "tools": self.tools}


class MCPClient:
    def __init__(self):
        self.servers = {}

    async def connect(self, name: str, command: str, args: list = None, env: dict = None):
        import subprocess
        cmd = [command] + (args or [])
        process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env or {})
        self.servers[name] = process

    async def disconnect(self, name: str):
        if name in self.servers:
            self.servers[name].terminate()
            del self.servers[name]


# === Export ===
__all__ = [
    "Agent", "AgentConfig", "Tool",
    "TodoManager", "TaskManager", "BackgroundManager", "MessageBus",
    "TODO", "TASK_MGR", "BG", "BUS",
    "run_bash", "run_read", "run_write", "run_edit",
    "microcompact", "auto_compact", "estimate_tokens",
    "AgentRunner", "DockerSandbox", "SandboxConfig",
    "MCPServer", "MCPClient",
    "WORKDIR", "TOKEN_THRESHOLD", "client", "MODEL",
    "SOUL_PROMPTS", "load_soul_prompts", "clear_skills_cache",
]