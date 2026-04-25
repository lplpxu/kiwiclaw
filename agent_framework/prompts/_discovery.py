"""
Instruction File Discovery - 从 CWD 向上遍历发现指令文件

参考 claw-code 的 discover_instruction_files() 实现

支持的指令文件模式：
- .agent.md
- AGENTS.md, agents.md
- CLAUDE.md, claude.md
- CLAUDE.local.md
- .cursorrules
- .cursor/rules/*.mdc
- .claude/instructions.md

扫描策略：
1. 从 CWD 开始
2. 向上遍历父目录（最多 5 层或到 git root）
3. 每个目录只加载一个同名文件
4. 内容会被安全扫描和截断
"""

import subprocess
from pathlib import Path
from typing import Dict

from ._security import scan_content

# 支持的上下文文件模式
CONTEXT_FILE_PATTERNS = [
    ".agent.md",
    "AGENTS.md",
    "agents.md",
    "CLAUDE.md",
    "claude.md",
    "CLAUDE.local.md",
    ".cursorrules",
    ".claude/instructions.md",
]

# 每个文件的最大字符数
MAX_FILE_CHARS = 4000

# 最大遍历深度
MAX_DEPTH = 5


def discover_instruction_files(root: Path, max_depth: int = MAX_DEPTH) -> Dict[str, str]:
    """
    从 root 向上遍历发现指令文件

    Args:
        root: 起始目录（CWD）
        max_depth: 最大遍历深度

    Returns:
        Dict[str, str] - filename -> content
    """
    found: Dict[str, str] = {}
    current = Path(root).resolve()
    depth = 0

    # 用于检测是否到达文件系统根
    last_valid_parent = current

    while depth < max_depth:
        for pattern in CONTEXT_FILE_PATTERNS:
            # 处理 glob 模式（如 .cursor/rules/*.mdc）
            if '*' in pattern:
                for match in current.glob(pattern):
                    if match.is_file() and match.name not in found:
                        content = _read_and_process_file(match)
                        if content:
                            found[match.name] = content
            else:
                path = current / pattern
                if path.is_file() and pattern not in found:
                    content = _read_and_process_file(path)
                    if content:
                        found[pattern] = content

        # 向上遍历
        parent = current.parent
        if parent == current:  # 到达根目录
            break

        # 检查是否是 git root（防止遍历超过仓库范围）
        git_root = _find_git_root(current)
        if git_root is not None:
            try:
                # 使用 try-except 处理 is_relative_to 的兼容性问题
                if not git_root.is_relative_to(parent):
                    # 已经超过 git root，不再向上
                    break
            except (TypeError, ValueError):
                # 如果 is_relative_to 不可用，使用简单的路径比较
                git_root_str = str(git_root)
                parent_str = str(parent)
                if git_root_str and parent_str and not parent_str.startswith(git_root_str):
                    break

        current = parent
        last_valid_parent = parent
        depth += 1

    return found


def _read_and_process_file(path: Path) -> str:
    """
    读取并处理文件内容

    1. 读取内容
    2. 安全扫描
    3. 截断到最大字符数

    Args:
        path: 文件路径

    Returns:
        处理后的内容，如果失败则返回空字符串
    """
    try:
        content = path.read_text(encoding='utf-8')

        # 安全扫描
        content = scan_content(content, str(path))

        # 截断
        if len(content) > MAX_FILE_CHARS:
            content = content[:MAX_FILE_CHARS] + "\n... (truncated)"

        return content
    except Exception:
        return ""


def _find_git_root(path: Path) -> Path:
    """查找最近的 git root"""
    try:
        result = subprocess.run(
            ['git', 'rev-parse', '--show-toplevel'],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=path
        )
        if result.returncode == 0:
            return Path(result.stdout.strip())
    except Exception:
        pass
    return None