"""
Harness Mode Hints - 根据 Harness 模式调整提示词

不同的运行模式需要不同的提示词策略：

- REPL: 持续对话，强调交互节奏
- Cron: 无用户交互，自主执行
- Single: 一次性任务，注重完成率

参考 hermes-agent 的 PLATFORM_HINTS 设计
"""

from typing import Dict


HARNESS_MODE_HINTS: Dict[str, str] = {
    "repl": """你处于 REPL 交互模式。
- 持续对话，注意交互节奏
- 不要一次性输出过多内容
- 复杂任务分步骤确认
- 用户可能会中断你的执行""",

    "cron": """你正在执行定时任务，无用户交互。
- 完全自主执行，不提问
- 做出合理决策
- 结果直接输出
- 完成后自动结束""",

    "single": """你正在执行一次性任务。
- 注重任务完成率
- 不需要持续确认
- 完成后给出总结
- 如果无法完成，说明原因和尝试的方法""",

    "api": """你正在通过 API 调用执行。
- 请求有明确的任务目标
- 返回结构化的结果
- 错误信息要清晰
- 考虑超时和重试""",
}


def get_harness_mode_hint(mode: str) -> str:
    """获取指定模式的提示词，如果没有则返回空字符串"""
    return HARNESS_MODE_HINTS.get(mode, "")