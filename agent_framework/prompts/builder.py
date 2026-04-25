"""
SystemPromptBuilder - 链式调用构建系统提示词

参考 claw-code prompt.rs 的设计，支持分层结构：
- STATIC 部分（可缓存）- Identity, System Rules, Doing Tasks, Actions
- DYNAMIC 部分（每轮更新）- Environment, Project Context, Session State, Mode Prompt
- MODE OVERRIDES - Harness 模式特定覆盖

Usage:
    builder = SystemPromptBuilder()
    builder.with_identity(IDENTITY_SECTION)
    builder.with_system_rules(SYSTEM_RULES)
    ...
    prompt = builder.build()
"""

from typing import List, Dict, Optional, Any


class SystemPromptBuilder:
    """链式调用构建系统提示词"""

    CACHE_BOUNDARY = "__SYSTEM_PROMPT_CACHE_BOUNDARY__"
    DYNAMIC_BOUNDARY = "__SYSTEM_PROMPT_DYNAMIC_BOUNDARY__"

    def __init__(self):
        self._identity: Optional[str] = None
        self._system_rules: List[str] = []
        self._doing_tasks: List[str] = []
        self._tool_usage_strategy: Optional[str] = None
        self._actions_care: Optional[str] = None
        self._environment: Optional[str] = None
        self._project_context: Optional[str] = None
        self._session_state: Optional[str] = None
        self._mode_prompt: Optional[str] = None
        self._skills: Optional[str] = None
        self._memories: Optional[str] = None
        self._permission_hint: Optional[str] = None
        self._harness_mode_hint: Optional[str] = None
        self._provider_override: Optional[str] = None

    def with_identity(self, identity: str) -> 'SystemPromptBuilder':
        """设置 Identity Section"""
        self._identity = identity
        return self

    def with_system_rules(self, rules: List[str]) -> 'SystemPromptBuilder':
        """设置 System Rules"""
        self._system_rules = rules
        return self

    def with_doing_tasks(self, tasks: List[str]) -> 'SystemPromptBuilder':
        """设置 Doing Tasks"""
        self._doing_tasks = tasks
        return self

    def with_tool_usage_strategy(self, strategy: str) -> 'SystemPromptBuilder':
        """设置工具使用策略"""
        self._tool_usage_strategy = strategy
        return self

    def with_actions_care(self, text: str) -> 'SystemPromptBuilder':
        """设置 Executing Actions"""
        self._actions_care = text
        return self

    def with_environment(self, env: str) -> 'SystemPromptBuilder':
        """设置 Environment Context"""
        self._environment = env
        return self

    def with_project_context(self, ctx: str) -> 'SystemPromptBuilder':
        """设置 Project Context"""
        self._project_context = ctx
        return self

    def with_session_state(self, state: Dict[str, Any]) -> 'SystemPromptBuilder':
        """设置 Session State"""
        parts = ["# Session State"]
        if "iteration" in state:
            parts.append(f"- Iteration: {state['iteration']}")
        if "mode" in state:
            parts.append(f"- Mode: {state['mode']}")
        if "todos" in state and state["todos"]:
            parts.append(f"- Active todos: {', '.join(state['todos'][:5])}")
        self._session_state = "\n".join(parts)
        return self

    def with_mode_prompt(self, mode_prompt: str) -> 'SystemPromptBuilder':
        """设置 Mode Prompt (Soul)"""
        self._mode_prompt = mode_prompt
        return self

    def with_skills(self, content: str) -> 'SystemPromptBuilder':
        """设置 Skills Content"""
        self._skills = content
        return self

    def with_memories(self, content: str) -> 'SystemPromptBuilder':
        """设置 Relevant Memories"""
        self._memories = content
        return self

    def with_permission_hint(self, hint: str) -> 'SystemPromptBuilder':
        """设置 Permission Hint"""
        self._permission_hint = hint
        return self

    def with_harness_mode(self, hint: str) -> 'SystemPromptBuilder':
        """设置 Harness Mode Hint"""
        self._harness_mode_hint = hint
        return self

    def with_provider_override(self, override: str) -> 'SystemPromptBuilder':
        """设置 Provider Override"""
        self._provider_override = override
        return self

    def build(self) -> str:
        """构建完整的系统提示词"""
        parts = []

        # === STATIC SECTION (可缓存) ===
        # 1. Identity
        if self._identity:
            parts.append(self._identity)

        # 2. System Rules
        if self._system_rules:
            system_section = ["# System"]
            for rule in self._system_rules:
                system_section.append(f"- {rule}")
            parts.append("\n".join(system_section))

        # 3. Doing Tasks
        if self._doing_tasks:
            tasks_section = ["# Doing tasks"]
            for task in self._doing_tasks:
                tasks_section.append(f"- {task}")
            parts.append("\n".join(tasks_section))

        # 4. Executing Actions
        if self._actions_care:
            parts.append(f"# Executing actions with care\n{self._actions_care}")

        # 5. Tool Usage Strategy (重要！指导 web_search → web_fetch 组合)
        if self._tool_usage_strategy:
            parts.append(self._tool_usage_strategy)

        # 6. Permission Hint (静态部分)
        if self._permission_hint:
            parts.append(self._permission_hint)

        # Cache boundary marker
        parts.append(f"\n{self.CACHE_BOUNDARY}\n")

        # === DYNAMIC SECTION (每轮更新) ===
        # 6. Environment Context
        if self._environment:
            parts.append(self._environment)

        # 7. Project Context (git, instruction files)
        if self._project_context:
            parts.append(self._project_context)

        # 8. Session State
        if self._session_state:
            parts.append(self._session_state)

        # Dynamic boundary marker
        parts.append(f"\n{self.DYNAMIC_BOUNDARY}\n")

        # 9. Mode Prompt (Soul)
        if self._mode_prompt:
            parts.append(self._mode_prompt)

        # 10. Skills Content
        if self._skills:
            parts.append(f"# Skills\n{self._skills}")

        # 11. Relevant Memories
        if self._memories:
            parts.append(f"# Relevant Memories\n{self._memories}")

        # 12. Provider Override (最优先)
        if self._provider_override:
            parts.append(self._provider_override)

        # 13. Harness Mode Override (最后)
        if self._harness_mode_hint:
            parts.append(self._harness_mode_hint)

        return "\n\n".join(parts)

    def clear(self) -> 'SystemPromptBuilder':
        """清空所有内容"""
        self._identity = None
        self._system_rules = []
        self._doing_tasks = []
        self._actions_care = None
        self._environment = None
        self._project_context = None
        self._session_state = None
        self._mode_prompt = None
        self._skills = None
        self._memories = None
        self._permission_hint = None
        self._harness_mode_hint = None
        self._provider_override = None
        return self