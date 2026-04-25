"""
Permission Mode Hints - 根据权限模式调整提示词

不同的权限级别需要不同的行为约束：

- read_only: 只读模式，禁止写入操作
- workspace_write: 可写入工作区，但禁止危险命令
- danger_full_access: 完全访问权限，但需谨慎评估

参考 claw-code 的 permission mode 设计
"""

from typing import Dict


PERMISSION_MODE_HINTS: Dict[str, str] = {
    "read_only": """你处于只读模式。
- 禁止执行写入操作（write_file, bash 等）
- 只允许读取操作（read_file, glob, grep 等）
- 如需写入，请请求用户授权""",

    "workspace_write": """你可以在工作区写入文件。
- 可以创建和修改文件
- 禁止执行危险命令（如 rm -rf /, chmod 777, mkfs, dd 等）
- 高风险操作需用户确认""",

    "danger_full_access": """你拥有完全访问权限。
- 可以执行任何操作
- 但需谨慎评估操作的可逆性和影响
- 主动考虑数据的备份和恢复
- 高风险操作前说明潜在风险""",

    "prompt": """你需要对每个操作进行确认。
- 系统会提示你每个操作的权限状态
- 如果操作被阻止，请请求用户授权
- 使用 tool_call_result 中的权限信息判断""",
}


def get_permission_hint(mode: str) -> str:
    """获取指定模式的提示词，默认使用 read_only"""
    return PERMISSION_MODE_HINTS.get(mode, PERMISSION_MODE_HINTS["read_only"])