"""Skill Executor

Executes skills and tracks their results.
[PHASE7] 技能系统 - SkillExecutor
"""

import asyncio
import time
import traceback
from typing import Dict, Any, Optional, Callable
from dataclasses import dataclass
from enum import Enum

from .manifest import SkillSpec, SkillStatus

# Debug print helper
def _debug(msg: str):
    print(f"[PHASE7] [SkillExecutor] {msg}")


class ExecutionResult(Enum):
    """Result of skill execution"""
    SUCCESS = "success"
    FAILURE = "failure"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


@dataclass
class SkillResult:
    """Result of executing a skill"""
    skill_name: str
    result: ExecutionResult
    output: str = ""
    error: str = ""
    duration_ms: float = 0
    quality_score: float = 0.0

    # Context
    context_provided: Dict[str, Any] = None
    events: list = None

    def __post_init__(self):
        if self.context_provided is None:
            self.context_provided = {}
        if self.events is None:
            self.events = []

    def to_dict(self) -> dict:
        return {
            "skill_name": self.skill_name,
            "result": self.result.value,
            "output": self.output,
            "error": self.error,
            "duration_ms": self.duration_ms,
            "quality_score": self.quality_score,
            "context_provided": self.context_provided,
            "events": self.events,
        }


class SkillExecutor:
    """Executes skills with proper isolation and tracking

    Manages skill execution lifecycle including:
    - Code validation
    - Execution with timeout
    - Error handling
    - Context management
    - Quality tracking
    """

    def __init__(self, sandbox_mode: str = "none"):
        self.sandbox_mode = sandbox_mode
        self._skill_handlers: Dict[str, Callable] = {}
        self._execution_count = 0

    def register_handler(self, skill_name: str, handler: Callable) -> None:
        """Register a handler for a skill

        Args:
            skill_name: Name of the skill
            handler: Callable that executes the skill
        """
        _debug(f"→ register_handler(skill={skill_name})")
        self._skill_handlers[skill_name] = handler
        _debug(f"← register_handler registered {skill_name}")

    def unregister_handler(self, skill_name: str) -> bool:
        """Unregister a skill handler

        Args:
            skill_name: Name of the skill

        Returns:
            True if handler was removed
        """
        _debug(f"→ unregister_handler(skill={skill_name})")
        if skill_name in self._skill_handlers:
            del self._skill_handlers[skill_name]
            _debug(f"← unregister_handler removed {skill_name}")
            return True
        _debug(f"← unregister_handler {skill_name} not found")
        return False

    async def execute(
        self,
        skill: SkillSpec,
        context: Dict[str, Any] = None,
        timeout_ms: float = 30000,
    ) -> SkillResult:
        """Execute a skill

        Args:
            skill: Skill to execute
            context: Execution context
            timeout_ms: Timeout in milliseconds

        Returns:
            SkillResult with execution details
        """
        _debug(f"→ execute(skill={skill.name}, timeout_ms={timeout_ms})")
        context = context or {}
        start_time = time.time()
        skill.use_count += 1
        skill.last_used = start_time

        events = []
        output = ""
        error = ""

        try:
            # Get handler
            handler = self._skill_handlers.get(skill.name)

            if not handler:
                # Try to execute skill code directly
                if skill.language == "python" and skill.code:
                    output = await self._execute_python_code(skill.code, context, timeout_ms)
                else:
                    raise ValueError(f"No handler for skill: {skill.name}")
            else:
                # Execute handler
                if asyncio.iscoroutinefunction(handler):
                    output = await asyncio.wait_for(
                        handler(context),
                        timeout=timeout_ms / 1000
                    )
                else:
                    output = handler(context)

            # Success
            skill.success_count += 1
            skill.last_success = time.time()
            result = ExecutionResult.SUCCESS

        except asyncio.TimeoutError:
            skill.failure_count += 1
            error = f"Skill execution timed out after {timeout_ms}ms"
            result = ExecutionResult.TIMEOUT
            events.append({"type": "timeout", "message": error})

        except Exception as e:
            skill.failure_count += 1
            error = f"{type(e).__name__}: {str(e)}"
            result = ExecutionResult.FAILURE
            events.append({
                "type": "error",
                "message": error,
                "traceback": traceback.format_exc()
            })

        duration_ms = (time.time() - start_time) * 1000
        skill.total_duration_ms += duration_ms

        # Calculate quality score
        quality_score = self._calculate_quality(skill, result, duration_ms)

        _debug(f"← execute {skill.name} → {result.value} | duration={duration_ms:.1f}ms | quality={quality_score:.2f}")

        return SkillResult(
            skill_name=skill.name,
            result=result,
            output=str(output) if output else "",
            error=error,
            duration_ms=duration_ms,
            quality_score=quality_score,
            context_provided=self._extract_context(skill, output),
            events=events,
        )

    async def _execute_python_code(
        self,
        code: str,
        context: Dict[str, Any],
        timeout_ms: float,
    ) -> str:
        """Execute Python code in a skill

        Args:
            code: Python code to execute
            context: Execution context
            timeout_ms: Timeout

        Returns:
            Output as string
        """
        # Create a safe execution environment
        local_context = {
            "__builtins__": __builtins__,
            "context": context,
            "result": None,
        }

        try:
            # Execute the code
            compiled = compile(code, "<skill>", "exec")
            exec(compiled, local_context)

            result = local_context.get("result")
            return str(result) if result is not None else ""

        except Exception as e:
            raise

    def _calculate_quality(
        self,
        skill: SkillSpec,
        result: ExecutionResult,
        duration_ms: float,
    ) -> float:
        """Calculate quality score for a skill execution

        Considers:
        - Success rate
        - Execution speed
        - Recent performance
        """
        if skill.use_count == 0:
            return 0.5

        # Success rate (40% weight)
        success_rate = skill.success_count / skill.use_count

        # Speed factor (20% weight) - normalize to 0-1
        # Assuming 10s is slow, 100ms is fast
        speed_score = max(0, min(1, 1 - (duration_ms / 10000)))

        # Recency factor (20% weight)
        time_since_last = time.time() - skill.last_used
        recency_score = max(0, min(1, 1 - (time_since_last / 86400)))  # Decay over 24h

        # Previous quality (20% weight)
        prev_quality = skill.avg_quality

        # Weighted average
        quality = (
            success_rate * 0.4 +
            speed_score * 0.2 +
            recency_score * 0.2 +
            prev_quality * 0.2
        )

        # Update running average
        skill.avg_quality = (skill.avg_quality * (skill.use_count - 1) + quality) / skill.use_count

        return quality

    def _extract_context(self, skill: SkillSpec, output: Any) -> Dict[str, Any]:
        """Extract context provided by a skill

        Skills can provide context that other skills or the agent can use.
        """
        if not skill.provides_context:
            return {}

        # If output is a dict, use it as context
        if isinstance(output, dict):
            return {k: v for k in skill.provides_context if k in output}

        return {}

    def get_statistics(self) -> dict:
        """Get execution statistics"""
        total_calls = sum(
            h.use_count for h in self._skill_handlers.values()
            if hasattr(h, 'use_count')
        )

        return {
            "registered_skills": len(self._skill_handlers),
            "total_executions": self._execution_count,
        }
