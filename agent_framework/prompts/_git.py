"""
Git Context - 自动获取 Git 状态和上下文

参考 claw-code 的 read_git_status(), read_git_diff(), read_git_log() 实现

自动获取：
- git status --porcelain (简化的状态)
- git diff --stat (未提交的变更统计)
- git log --oneline -5 (最近 5 条提交)
"""

import subprocess
from typing import Optional

from .context import ProjectContext


def get_git_context() -> Optional[ProjectContext]:
    """
    获取当前 git 上下文

    Returns:
        ProjectContext 对象，包含 git 状态、diff、log
        如果不是 git 仓库或出错则返回 None
    """
    try:
        # 检查是否是 git 仓库
        subprocess.run(
            ['git', 'rev-parse', '--git-dir'],
            capture_output=True,
            check=True,
            cwd='.'
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None

    context = {
        'git_status': None,
        'git_diff': None,
        'git_log': None,
        'instruction_files': {}
    }

    # 获取 git status
    try:
        result = subprocess.run(
            ['git', 'status', '--porcelain'],
            capture_output=True,
            text=True,
            timeout=5
        )
        status = result.stdout.strip()
        context['git_status'] = status if status else None
    except Exception:
        pass

    # 获取 git diff
    try:
        result = subprocess.run(
            ['git', 'diff', '--stat'],
            capture_output=True,
            text=True,
            timeout=5
        )
        diff = result.stdout.strip()
        context['git_diff'] = diff if diff else None
    except Exception:
        pass

    # 获取 git log
    try:
        result = subprocess.run(
            ['git', 'log', '--oneline', '-5'],
            capture_output=True,
            text=True,
            timeout=5
        )
        log = result.stdout.strip()
        context['git_log'] = log if log else None
    except Exception:
        pass

    return ProjectContext(**context)


def has_uncommitted_changes() -> bool:
    """检查是否有未提交的更改"""
    try:
        result = subprocess.run(
            ['git', 'status', '--porcelain'],
            capture_output=True,
            text=True,
            timeout=5
        )
        return bool(result.stdout.strip())
    except Exception:
        return False