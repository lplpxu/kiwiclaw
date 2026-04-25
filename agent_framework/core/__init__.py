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
from .error_classifier import (
    ErrorClassifier, ClassifiedError, FailoverReason, RecoveryAction,
    classify_error, get_error_classifier,
)
from .state import get_state_manager, AgentFlag
from .bootstrap import get_bootstrap
from ..observability.tracing import SpanKind
from ..observability.hooks import get_hook_runner, ToolHookContext, LLIHookContext, HookName
from ..planning.recovery import (
    FailureRecovery,
    FailurePhase,
    run_react_analysis,
    format_recovery_message,
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

        # Initialize failure recovery system (PHASE8)
        self._failure_recovery = FailureRecovery(max_failures_before_react=2)

        # Initialize permission system (参考 claw-code permissions.rs)
        from ..acp.permissions import PermissionPolicy, PermissionEnforcer, PermissionMode
        perm_mode = getattr(self.config, 'permission_mode', 'danger_full_access')
        perm_mode = PermissionMode(perm_mode) if isinstance(perm_mode, str) else perm_mode
        policy = PermissionPolicy(mode=perm_mode)
        self._permission_enforcer = PermissionEnforcer(policy)

        # Initialize skills system (参考 hermes-agent skills/)
        try:
            from ..skills import get_registry
            self._skill_registry = get_registry()
        except Exception:
            self._skill_registry = None

        # Initialize memory system
        try:
            from ..memory import get_vector_store, get_semantic_search
            self._vector_store = get_vector_store()
            self._semantic_search = get_semantic_search()
        except Exception:
            self._vector_store = None
            self._semantic_search = None

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
            {"name": "web_search", "description": "Search the internet to obtain the URLs needed to retrieve information. Returns metadata only (URLs, titles, snippets). ALWAYS use web_fetch after search to get full page content for detailed information or structured data.",
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

    def _add_failure_message(self) -> None:
        """Add failure message after max failures reached"""
        msg = "工具结果已多次未能解决您的问题。请放弃前面的方法，使用其他可用的资源、条件或自己创造条件来完成任务。"
        print(f"[DEBUG judge] Max failures reached, adding message: {msg}")
        self.messages.append({
            "role": "user",
            "content": msg
        })

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

    def get_relevant_memories(self, query: str, limit: int = 3) -> str:
        """Get relevant memories for a query (参考 hermes-agent 跨会话记忆)

        Args:
            query: Query string to search for
            limit: Maximum number of memories to return

        Returns:
            String containing relevant memory content
        """
        if not self._semantic_search:
            return ""

        try:
            results = self._semantic_search.search(query, limit=limit)
            if not results:
                return ""

            memory_lines = ["\n\n=== 相关记忆 ==="]
            for result in results:
                entry = result.entry
                memory_lines.append(f"- [{entry.created_at}] {entry.content[:200]}")
            memory_lines.append("=== 记忆结束 ===\n")
            return "\n".join(memory_lines)
        except Exception:
            return ""

    def save_memory(self, content: str, metadata: dict = None) -> bool:
        """Save a memory entry (参考 hermes-agent 记忆系统)

        Args:
            content: Memory content to save
            metadata: Optional metadata dict

        Returns:
            True if saved successfully
        """
        if not self._vector_store:
            return False

        try:
            import uuid
            from ..memory.vector import MemoryEntry
            entry = MemoryEntry(
                id=str(uuid.uuid4()),
                content=content,
                metadata=metadata or {},
            )
            return self._vector_store.add(entry)
        except Exception:
            return False

    def get_system_prompt(self, memory_query: str = None) -> str:
        mode = getattr(self.config, 'mode', 'simple')
        if mode != self._current_mode:
            load_soul_prompts()
            self._current_mode = mode

        # Import prompts module
        from ..prompts import (
            SystemPromptBuilder,
            EnvironmentContext,
            IDENTITY_SECTION,
            SYSTEM_RULES,
            DOING_TASKS,
            EXECUTING_ACTIONS,
            TOOL_USAGE_STRATEGY,
            get_harness_mode_hint,
            get_permission_hint,
            get_git_context,
            get_environment_section,
            get_project_context_section,
        )

        # Get all skills content dynamically
        skills_content = _get_all_skills()

        # Get relevant memories if query provided (参考 hermes-agent 跨会话记忆)
        memory_content = ""
        if memory_query and self._semantic_search:
            memory_content = self.get_relevant_memories(memory_query)

        # Build prompt using SystemPromptBuilder
        builder = SystemPromptBuilder()

        # 1. Bootstrap (Static)
        builder.with_identity(IDENTITY_SECTION)
        builder.with_system_rules(SYSTEM_RULES)
        builder.with_doing_tasks(DOING_TASKS)
        builder.with_actions_care(EXECUTING_ACTIONS)

        # 1.5 Tool Usage Strategy (指导 web_search → web_fetch 组合)
        builder.with_tool_usage_strategy(TOOL_USAGE_STRATEGY)

        # 2. Permission hint
        perm_mode = getattr(self.config, 'permission_mode', 'read_only')
        builder.with_permission_hint(get_permission_hint(perm_mode))

        # 3. Environment context (Dynamic)
        from datetime import datetime
        import platform as plt
        env = EnvironmentContext(
            model_family=self.config.model or "unknown",
            working_directory=str(self.config.cwd) if hasattr(self.config, 'cwd') else str(Path.cwd()),
            current_date=datetime.now().strftime("%Y-%m-%d"),
            platform=plt.platform(),
        )
        builder.with_environment(get_environment_section(env))

        # 4. Git context + Instruction files (Dynamic)
        from ..prompts._discovery import discover_instruction_files
        git_ctx = get_git_context()
        if git_ctx:
            # 发现指令文件并合并到 project context
            instruction_files = discover_instruction_files(Path.cwd())
            git_ctx.instruction_files = instruction_files
            builder.with_project_context(get_project_context_section(git_ctx))
        else:
            # 即使没有 git，也发现指令文件
            instruction_files = discover_instruction_files(Path.cwd())
            if instruction_files:
                from ..prompts.context import ProjectContext
                empty_ctx = ProjectContext(
                    git_status=None,
                    git_diff=None,
                    git_log=None,
                    instruction_files=instruction_files
                )
                builder.with_project_context(get_project_context_section(empty_ctx))

        # 5. Session state (Dynamic)
        builder.with_session_state({
            "iteration": getattr(self, '_iteration', 0),
            "mode": mode,
        })

        # 6. Mode prompt (Soul) - Dynamic boundary inserted before this
        builder.with_mode_prompt(SOUL_PROMPTS.get(mode, SOUL_PROMPTS["simple"]))

        # 7. Skills content
        if skills_content:
            builder.with_skills(skills_content)

        # 8. Relevant memories
        if memory_content:
            builder.with_memories(memory_content)

        # 9. Harness mode override
        harness_mode = getattr(self.config, 'harness_mode', 'repl')
        hint = get_harness_mode_hint(harness_mode)
        if hint:
            builder.with_harness_mode(hint)

        return builder.build()

    async def think(self, prompt: str, status_callback=None) -> str:
        """Main thinking loop (集成tracing - 参考claw-code conversation.rs)"""
        import time
        from .bootstrap import get_bootstrap
        from ..observability.tracing import SpanKind
        from ..observability.hooks import get_hook_runner, ToolHookContext, LLIHookContext, HookName
        from .state import get_state_manager, AgentFlag

        def _debug(msg: str):
            print(f"[DEBUG] {msg}")

        _debug(f"=== Agent.think() 开始 ===")
        _debug(f"Prompt: {prompt[:100]}...")

        # Get tracing, hooks, and state manager from bootstrap
        bootstrap = get_bootstrap()
        tracing = bootstrap.get_component("tracing")
        hook_runner = get_hook_runner()
        state_manager = get_state_manager()

        # Initialize or update state
        state_manager.update(lambda s: s.set_flag(AgentFlag.RUNNING))
        state_manager.update(lambda s: setattr(s, 'current_task', prompt[:50]))

        # 保存原始问题供后续 judge 评估使用（避免多轮后丢失原始问题）
        original_prompt = prompt

        _debug(f"Bootstrap components: tracing={tracing is not None}, hook_runner={hook_runner is not None}")

        # Run session_start hooks
        await hook_runner.run_after_llm_call(
            LLIHookContext(messages=self.messages, system_prompt=self.get_system_prompt(), model=self.config.model, tools=self._tools),
            None
        )

        # Start turn span (参考 claw-code: turn_started)
        turn_span = None
        if tracing:
            turn_span = tracing.start_span(
                "agent.turn",
                SpanKind.INTERNAL,
                prompt_length=len(prompt),
            )

        try:
            self.messages.append({"role": "user", "content": prompt})

            while True:
                current_iteration = state_manager.state.iteration
                current_call_depth = state_manager.state.call_depth
                _debug(f"--- Iteration {current_iteration} 开始 | call_depth={current_call_depth} ---")

                # Check call_depth (防止无限递归)
                if current_call_depth >= state_manager.state.max_call_depth:
                    _debug(f"达到 max_call_depth={state_manager.state.max_call_depth}，退出防止递归")
                    if turn_span:
                        turn_span.set_attribute("completed", False)
                        turn_span.set_attribute("error", "max_call_depth_reached")
                        tracing.end_span(turn_span)
                    return f"达到最大调用深度 {state_manager.state.max_call_depth}，停止执行"

                # Check max_iterations
                if current_iteration >= state_manager.state.max_iterations:
                    _debug(f"达到 max_iterations={state_manager.state.max_iterations}，退出")
                    if turn_span:
                        turn_span.set_attribute("completed", False)
                        turn_span.set_attribute("error", "max_iterations_reached")
                        tracing.end_span(turn_span)
                    return f"达到最大迭代次数 {state_manager.state.max_iterations}，停止执行"

                # Increment iteration and call_depth
                state_manager.update(lambda s: s.increment_iteration())

                if status_callback is not None:
                    await status_callback("思考中...")

                # Start iteration span (参考 claw-code: assistant_iteration_completed)
                iteration_span = None
                if tracing:
                    iteration_span = tracing.start_span(
                        "agent.iteration",
                        SpanKind.INTERNAL,
                    )

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
                        # 处理 tool_use 响应和 tool_result 消息
                        text_parts = []
                        has_tool_result = False
                        for part in msg["content"]:
                            if isinstance(part, dict) and part.get("type") == "text":
                                text_parts.append(part.get("text", ""))
                            elif isinstance(part, dict) and part.get("type") == "tool_result":
                                has_tool_result = True
                                tool_content = part.get("content", "")
                                tool_id = part.get("tool_use_id", "")
                                if tool_id:
                                    text_parts.append(f"[TOOL_RESULT id={tool_id}]{tool_content}[/TOOL_RESULT]")
                                else:
                                    text_parts.append(str(tool_content))
                        if text_parts:
                            llm_messages.append({"role": msg["role"], "content": "\n".join(text_parts)})
                        elif has_tool_result:
                            # 有 tool_result 但没有文本内容，也保留消息
                            llm_messages.append({"role": msg["role"], "content": "[tool executed]"})
                    else:
                        llm_messages.append(msg)

                system_msg = {"role": "system", "content": self.get_system_prompt(prompt)}
                all_messages = [system_msg] + llm_messages

                _debug(f"LLM 调用中... messages={len(all_messages)}, tools={len(self._tools)}")

                # Start LLM call span
                llm_span = None
                if tracing:
                    llm_span = tracing.start_span(
                        "llm.call",
                        SpanKind.CLIENT,
                        model=self.config.model,
                    )

                llm_start = time.time()
                response = client.messages.create(
                    model=self.config.model,
                    messages=all_messages,
                    tools=self._tools,
                    max_tokens=8000,
                )
                llm_duration = time.time() - llm_start

                _debug(f"LLM 响应: stop_reason={response.stop_reason}, duration={llm_duration:.2f}s")

                if llm_span:
                    llm_span.set_attribute("stop_reason", response.stop_reason)
                    tracing.end_span(llm_span)

                self.messages.append({"role": "assistant", "content": response.content})

                if iteration_span:
                    tracing.end_span(iteration_span)

                if response.stop_reason != "tool_use":
                    _debug(f"无工具调用，LLM 直接返回文本，进行 judge 判定")
                    # 获取 LLM 返回的文本内容
                    llm_text = "".join(b.text for b in response.content if hasattr(b, 'text')) or "(no response)"
                    # 使用 judge 评估 LLM 最终输出
                    judge_pass, judge_advice = run_judge(llm_text, original_prompt)
                    _debug(f"[DEBUG judge] LLM直接输出评估: pass={judge_pass}, advice={judge_advice[:100] if judge_advice else 'empty'}")

                    if judge_pass:
                        if turn_span:
                            turn_span.set_attribute("completed", True)
                            tracing.end_span(turn_span)
                        return llm_text
                    else:
                        # Judge 失败，添加 advice 并继续让 LLM 改进
                        self._judge_fail_count += 1
                        self.messages.append({"role": "user", "content": f"你的回答未完全解决用户问题。\n\n建议：{judge_advice}"})
                        _debug(f"[PHASE8] judge_fail_count={self._judge_fail_count}")
                        continue

                results = []
                manual_compress = False
                image_result = None
                consecutive_tool_calls = 0
                last_tool_name = None  # 追踪最后一个工具名称
                _debug(f"发现 {sum(1 for b in response.content if b.type == 'tool_use')} 个工具调用")

                # Increment call_depth for tool execution
                state_manager.update(lambda s: s.increment_call_depth())
                _debug(f"call_depth incremented to {state_manager.state.call_depth}")

                for block in response.content:
                    if block.type == "tool_use":
                        consecutive_tool_calls += 1
                        last_tool_name = block.name  # 记录工具名称
                        _debug(f"  工具 #{consecutive_tool_calls}: {block.name} | input={block.input}")
                        if block.name == "compress":
                            manual_compress = True

                        # Start tool execution span (参考 claw-code: tool_execution_started/finished)
                        tool_span = None
                        if tracing:
                            tool_span = tracing.start_span(
                                f"tool.{block.name}",
                                SpanKind.INTERNAL,
                            )

                        if status_callback is not None:
                            await status_callback(f"执行工具: {block.name}...")

                        # Run before_tool_call hooks (参考 openclaw plugins/hooks.ts)
                        tool_context = ToolHookContext(
                            tool_name=block.name,
                            tool_input=block.input,
                            agent_name=self.name,
                            messages=self.messages,
                            iteration=consecutive_tool_calls,
                        )
                        blocked, modified_input = await hook_runner.run_before_tool_call(tool_context)
                        if blocked:
                            output = "[HOOK BLOCKED] Tool execution was blocked by a before_tool_call hook"
                            _debug(f"  [HOOK BLOCKED] {block.name}")
                            if tool_span:
                                tool_span.set_attribute("hook_blocked", True)
                                tracing.end_span(tool_span)
                            results.append({"type": "tool_result", "tool_use_id": block.id, "content": str(output)})
                            self.messages.append({"role": "user", "content": results})
                            if turn_span:
                                turn_span.set_attribute("completed", False)
                                turn_span.set_attribute("error", "hook_blocked")
                                tracing.end_span(turn_span)
                            return f"工具执行被hook阻止: {block.name}"
                        if modified_input:
                            _debug(f"  [HOOK MODIFIED] {block.name}: {modified_input}")
                            block.input = modified_input

                        # Permission check (参考 hermes-agent tools/approval.py)
                        permission_enforcer = getattr(self, '_permission_enforcer', None)
                        if permission_enforcer:
                            perm_result = permission_enforcer.check(block.name, block.input)
                            if not perm_result.allowed:
                                _debug(f"  [PERMISSION DENIED] {block.name}: {perm_result.reason}")
                                output = f"[PERMISSION DENIED] {perm_result.reason}"
                                if tool_span:
                                    tool_span.set_attribute("permission_denied", True)
                                    tracing.end_span(tool_span)
                                results.append({"type": "tool_result", "tool_use_id": block.id, "content": str(output)})
                                self.messages.append({"role": "user", "content": results})
                                if turn_span:
                                    turn_span.set_attribute("completed", False)
                                    turn_span.set_attribute("error", "permission_denied")
                                    tracing.end_span(turn_span)
                                return f"权限被拒绝: {perm_result.reason}"

                        handler = self._tool_handlers.get(block.name)
                        tool_start = time.time()
                        try:
                            output = handler(**block.input) if handler else f"Unknown tool: {block.name}"
                        except Exception as e:
                            # 错误分类和恢复策略
                            classified = classify_error(e, tool_name=block.name)
                            error_msg = f"[{classified.reason.value.upper()}] {str(e)}"

                            # 根据错误类型添加恢复提示
                            recovery_hint = ""
                            if classified.should_react:
                                recovery_hint = " [提示: 考虑换一种方法解决这个问题]"
                            elif classified.should_compress:
                                recovery_hint = " [提示: 上下文过长，需要压缩后重试]"
                            elif classified.reason == FailoverReason.rate_limit:
                                recovery_hint = " [提示: 请求过于频繁，建议稍后重试]"

                            output = error_msg + recovery_hint
                            if tool_span:
                                tool_span.record_exception(e)
                                tool_span.set_attribute("error_classified", classified.reason.value)
                        tool_duration = time.time() - tool_start
                        output_str = str(output)[:200]
                        output_clean = output_str.encode('ascii', 'replace').decode('ascii')
                        print(f"> {block.name}: {output_clean}")
                        _debug(f"  工具完成: {block.name} | duration={tool_duration:.2f}s | output_len={len(str(output))}")

                        # Run after_tool_call hooks (参考 openclaw plugins/hooks.ts)
                        output = await hook_runner.run_after_tool_call(tool_context, output)

                        if tool_span:
                            tool_span.set_attribute("tool_name", block.name)
                            tracing.end_span(tool_span)

                        if block.name == "text_to_image":
                            try:
                                img_data = json.loads(output)
                                if img_data.get("type") == "image" and img_data.get("image"):
                                    image_result = img_data
                            except:
                                pass

                        results.append({"type": "tool_result", "tool_use_id": block.id, "content": str(output)})

                self.messages.append({"role": "user", "content": results})

                # Decrement call_depth after tool execution
                state_manager.update(lambda s: s.decrement_call_depth())
                _debug(f"call_depth decremented to {state_manager.state.call_depth}")

                for r in results:
                    if isinstance(r, dict) and "[FATAL_ERROR]" in str(r.get("content", "")):
                        fatal_msg = r.get("content", "")
                        if turn_span:
                            turn_span.set_attribute("completed", False)
                            turn_span.set_attribute("error", "fatal_error")
                            tracing.end_span(turn_span)
                        return f"工具执行失败:\n{fatal_msg}\n\n请根据此错误信息回复用户。"

                if image_result:
                    if turn_span:
                        turn_span.set_attribute("completed", True)
                        tracing.end_span(turn_span)
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
                                    # 使用原始问题供 judge 评估（避免多轮后消息中丢失原始问题）
                                    user_prompt = original_prompt
                                    _debug(f"调用 Judge 系统评估结果... (original_prompt={original_prompt[:60]}...)")
                                    try:
                                        judge_pass, judge_advice = run_judge(content, user_prompt)
                                        print(f"[DEBUG judge] pass={judge_pass}, advice={judge_advice[:100] if judge_advice else 'empty'}")

                                        if judge_pass:
                                            self._judge_fail_count = 0
                                            if judge_advice:
                                                self.messages.append({
                                                    "role": "user",
                                                    "content": f"工具结果已返回。\n\n建议：{judge_advice}"
                                                })
                                            if turn_span:
                                                turn_span.set_attribute("completed", True)
                                                tracing.end_span(turn_span)
                                            return content
                                        else:
                                            self._judge_fail_count += 1
                                            print(f"[DEBUG judge] fail_count={self._judge_fail_count}")

                                            # Get original user prompt for context
                                            user_prompt = ""
                                            for msg in reversed(self.messages[:-1]):
                                                if msg["role"] == "user" and isinstance(msg.get("content"), str):
                                                    user_prompt = msg["content"]
                                                    break

                                            # Record failure in recovery system
                                            should_react, phase = self._failure_recovery.record_failure(
                                                task=user_prompt or prompt,
                                                tool_name=last_tool_name or "unknown",
                                                tool_result=content,
                                                judge_advice=judge_advice
                                            )
                                            _debug(f"[PHASE8] record_failure returned: should_react={should_react}, phase={phase}, fail_count={self._judge_fail_count}")

                                            if should_react:
                                                # Trigger ReAct analysis after 2 failures
                                                _debug(f"[PHASE8] Triggering ReAct analysis (failure #{self._judge_fail_count})")
                                                try:
                                                    # Get failure context
                                                    failure_ctx = self._failure_recovery.get_failure_context()
                                                    if failure_ctx:
                                                        # Run async ReAct analysis
                                                        loop = asyncio.get_event_loop()
                                                        analysis = await run_react_analysis(
                                                            task=user_prompt or prompt,
                                                            failure_context=failure_ctx
                                                        )
                                                        # Format and add analysis to messages
                                                        recovery_msg = format_recovery_message(analysis)
                                                        self.messages.append({
                                                            "role": "user",
                                                            "content": recovery_msg
                                                        })
                                                        _debug(f"[PHASE8] ReAct analysis complete: confidence={analysis.confidence:.0%}")
                                                        # Continue with the plan
                                                        self._failure_recovery.set_react_plan(analysis.solution_plan)
                                                except Exception as e:
                                                    _debug(f"[PHASE8] ReAct analysis failed: {e}")
                                                    # Fallback to old behavior
                                                    self._add_failure_message()
                                            elif self._judge_fail_count > 3:
                                                # After max failures, give up and try different approach
                                                self._add_failure_message()
                                                self._judge_fail_count = 0
                                                self._failure_recovery.reset()
                                            elif judge_advice:
                                                print(f"[DEBUG judge] Adding advice: {judge_advice[:100]}")
                                                self.messages.append({
                                                    "role": "user",
                                                    "content": f"工具结果未完全解决您的问题。\n\n建议：{judge_advice}"
                                                })
                                    except Exception as e:
                                        print(f"[judge error: {e}]")
                if consecutive_tool_calls > 10:
                    print("[tool call limit reached]")
                    for r in results:
                        if isinstance(r, dict) and r.get("type") == "tool_result":
                            if turn_span:
                                turn_span.set_attribute("completed", True)
                                tracing.end_span(turn_span)
                            return str(r.get("content", ""))

        except Exception as e:
            if turn_span:
                turn_span.set_attribute("completed", False)
                turn_span.record_exception(e)
                tracing.end_span(turn_span)
            raise


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