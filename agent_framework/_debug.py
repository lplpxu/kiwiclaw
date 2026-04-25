"""Debug Utility Module

统一 debug 打印格式，追踪模块信息流入和流出。
格式: [模块层级] 消息
"""

import functools
import asyncio
from typing import Callable, Any


# 模块层级定义
MODULE_LEVELS = {
    # Phase 1: 核心框架 + Agent Loop
    "AgentLoop": "PHASE1",
    "ContextCompressor": "PHASE1",
    "TransportAdapter": "PHASE1",

    # Phase 2: 运行时必需组件
    "Bootstrap": "PHASE2",
    "ToolRegistry": "PHASE2",
    "ConfigLoader": "PHASE2",

    # Phase 3: ACP协议
    "ACPSession": "PHASE3",
    "ACPEvents": "PHASE3",
    "PermissionBridge": "PHASE3",

    # Phase 4: 插件系统
    "PluginLoader": "PHASE4",
    "PluginRuntime": "PHASE4",

    # Phase 5: 通道集成
    "ChannelBase": "PHASE5",
    "TelegramChannel": "PHASE5",
    "DiscordChannel": "PHASE5",

    # Phase 6: Agent Harness
    "CLIHarness": "PHASE6",
    "APIHarness": "PHASE6",
    "Sandbox": "PHASE6",

    # Phase 7: 技能系统
    "SkillExecutor": "PHASE7",
    "SkillLearner": "PHASE7",
    "SkillRegistry": "PHASE7",

    # Phase 8: 规划推理
    "ReActLoop": "PHASE8",
    "TaskDecomposer": "PHASE8",
    "ExecutionMonitor": "PHASE8",
    "TaskVerifier": "PHASE8",
    "Reflector": "PHASE8",

    # Phase 9: 长期记忆
    "VectorStore": "PHASE9",
    "SemanticSearch": "PHASE9",
    "MemoryIndexer": "PHASE9",
    "MemoryDecay": "PHASE9",

    # Phase 10: 可观测性
    "StructuredLogger": "PHASE10",
    "Tracing": "PHASE10",
    "MetricsCollector": "PHASE10",
    "CostTracker": "PHASE10",
    "HookRunner": "PHASE10",

    # Phase 11: 核心运行时
    "StateManager": "PHASE11",
    "ErrorHandler": "PHASE11",
    "CircuitBreaker": "PHASE11",
    "RecoveryStrategy": "PHASE11",

    # Phase 12: Agent组件
    "TokenBudget": "PHASE12",
    "RateLimiter": "PHASE12",
}


def get_debug_level(module_name: str) -> str:
    """获取模块的 debug 层级前缀"""
    level = MODULE_LEVELS.get(module_name, "UNKNOWN")
    return f"[{level}]"


def debug_print(module: str, msg: str, level: str = "INFO"):
    """统一的 debug 打印格式

    Args:
        module: 模块名称
        msg: 消息内容
        level: 日志级别 (INFO, DEBUG, WARN, ERROR)
    """
    prefix = get_debug_level(module)
    print(f"{prefix} [{module}] [{level}] {msg}")


def debug_enter(module: str, func_name: str, *args, **kwargs):
    """追踪函数入口"""
    args_str = ", ".join(str(a)[:50] for a in args[:3])
    kwargs_str = ", ".join(f"{k}={str(v)[:30]}" for k, v in list(kwargs.items())[:3])
    extra = args_str
    if kwargs_str:
        extra = f"{args_str}, {kwargs_str}" if args_str else kwargs_str
    debug_print(module, f"→ {func_name}({extra})")


def debug_exit(module: str, func_name: str, result: Any = None):
    """追踪函数出口"""
    if result is None:
        debug_print(module, f"← {func_name} → None")
    elif isinstance(result, (str, int, float, bool)):
        debug_print(module, f"← {func_name} → {str(result)[:100]}")
    elif isinstance(result, (list, dict)):
        debug_print(module, f"← {func_name} → {type(result).__name__}(len={len(result)})")
    else:
        debug_print(module, f"← {func_name} → {type(result).__name__}")


def debug_call(module: str, operation: str, details: str = ""):
    """追踪模块调用

    Args:
        module: 模块名称
        operation: 操作名称
        details: 详细信息
    """
    msg = f"→ {operation}"
    if details:
        msg += f" | {details}"
    debug_print(module, msg)


def debug_result(module: str, operation: str, result: Any, details: str = ""):
    """追踪模块结果

    Args:
        module: 模块名称
        operation: 操作名称
        result: 结果
        details: 详细信息
    """
    msg = f"← {operation}"
    if details:
        msg += f" | {details}"
    if result is not None:
        if isinstance(result, bool):
            msg += f" → {result}"
        elif isinstance(result, (str, int, float)):
            msg += f" → {str(result)[:50]}"
        elif isinstance(result, (list, dict)):
            msg += f" → {type(result).__name__}(len={len(result)})"
    debug_print(module, msg)


def trace_module(module: str):
    """装饰器：自动追踪函数的入口和出口

    Usage:
        @trace_module("MyModule")
        def my_function(arg1, arg2):
            ...
    """
    def decorator(func: Callable) -> Callable:
        name = func.__name__

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            debug_enter(module, name, *args, **kwargs)
            try:
                result = func(*args, **kwargs)
                debug_exit(module, name, result)
                return result
            except Exception as e:
                debug_print(module, f"← {name} ERROR: {type(e).__name__}: {e}", "ERROR")
                raise

        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            debug_enter(module, name, *args, **kwargs)
            try:
                result = await func(*args, **kwargs)
                debug_exit(module, name, result)
                return result
            except Exception as e:
                debug_print(module, f"← {name} ERROR: {type(e).__name__}: {e}", "ERROR")
                raise

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


def phase_header(phase: str, title: str):
    """打印阶段头部信息

    Usage:
        phase_header("PHASE1", "核心框架 + Agent Loop")
    """
    print(f"\n{'='*60}")
    print(f"[{phase}] {title}")
    print(f"{'='*60}")
