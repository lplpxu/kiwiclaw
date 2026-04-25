"""
Context - Environment and Project Context

提供环境上下文信息：
- EnvironmentContext: 当前运行环境（CWD、平台、模型、时间）
- ProjectContext: 项目上下文（git 状态、instruction files）

参考 claw-code 的 environment_section() 和 ProjectContext 设计
"""

from dataclasses import dataclass
from typing import Dict, Optional


@dataclass
class EnvironmentContext:
    """环境上下文信息"""
    model_family: str
    working_directory: str
    current_date: str
    platform: str  # Windows 11 x64 / macOS / Linux


@dataclass
class ProjectContext:
    """项目上下文（git、instruction files）"""
    git_status: Optional[str]
    git_diff: Optional[str]
    git_log: Optional[str]
    instruction_files: Dict[str, str]  # filename -> content


def get_environment_section(env: EnvironmentContext) -> str:
    """构建环境上下文提示词"""
    return f"""# Environment
- Model: {env.model_family}
- Working directory: {env.working_directory}
- Date: {env.current_date}
- Platform: {env.platform}"""


def get_project_context_section(ctx: ProjectContext) -> str:
    """构建项目上下文提示词"""
    parts = ["# Project Context"]

    if ctx.git_status:
        parts.append(f"## Git Status\n{ctx.git_status}")

    if ctx.git_diff:
        parts.append(f"## Uncommitted Changes\n{ctx.git_diff}")

    if ctx.git_log:
        parts.append(f"## Recent Commits\n{ctx.git_log}")

    for filename, content in ctx.instruction_files.items():
        # 截断单个文件内容到 4000 字符
        truncated = content[:4000] + "\n... (truncated)" if len(content) > 4000 else content
        parts.append(f"## {filename}\n{truncated}")

    return "\n\n".join(parts)