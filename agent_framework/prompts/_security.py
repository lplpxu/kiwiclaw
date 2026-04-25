"""
Security Scanning - Prompt Injection Detection

参考 hermes-agent 的 `_scan_context_content()` 实现，
用于扫描外部加载的上下文文件中的威胁模式。

检测类型：
- Prompt Injection: 尝试忽略/覆盖之前的指令
- Deception: 隐藏信息不告诉用户
- System Prompt Override: 尝试覆盖系统提示词
"""

import re
from typing import List, Tuple


# 威胁模式
CONTEXT_THREAT_PATTERNS: List[Tuple[str, str]] = [
    (r'ignore\s+(previous|all|above|prior)\s+instructions', "prompt_injection"),
    (r'do\s+not\s+tell\s+the\s+user', "deception_hide"),
    (r'system\s+prompt\s+override', "sys_prompt_override"),
    (r'ignore\s+system\s+prompt', "sys_prompt_override"),
    (r'pretend\s+you\s+are\s+a\s+different', "role_play_attempt"),
]

# 不可见的 Unicode 字符
INVISIBLE_UNICODE_CHARS = {'​', '‌', '‍', '⁠', '﻿'}


def scan_content(content: str, filename: str = "unknown") -> str:
    """
    扫描内容并清除威胁内容

    Args:
        content: 要扫描的内容
        filename: 文件名（用于警告信息）

    Returns:
        清理后的内容，如果检测到威胁会在末尾添加警告
    """
    # 1. 移除零宽字符
    for char in INVISIBLE_UNICODE_CHARS:
        content = content.replace(char, '')

    # 2. 检测注入模式
    warnings = []
    for pattern, threat_type in CONTEXT_THREAT_PATTERNS:
        if re.search(pattern, content, re.IGNORECASE):
            warnings.append(f"[WARNING: {threat_type} detected in {filename}]")

    # 3. 如果有警告，添加到内容末尾
    if warnings:
        content = content + "\n\n" + "\n".join(warnings)

    return content


def is_safe_content(content: str) -> bool:
    """检查内容是否安全（无威胁模式）"""
    for pattern, _ in CONTEXT_THREAT_PATTERNS:
        if re.search(pattern, content, re.IGNORECASE):
            return False
    return True


def remove_invisible_chars(content: str) -> str:
    """移除所有不可见 Unicode 字符"""
    result = []
    for char in content:
        if char not in INVISIBLE_UNICODE_CHARS:
            result.append(char)
    return ''.join(result)