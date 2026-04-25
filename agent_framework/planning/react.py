"""ReAct (Reasoning + Acting) Implementation

Implements the ReAct paradigm for agent reasoning and acting.
[PHASE8] 规划推理 - ReActLoop
"""

from typing import List, Dict, Any, Optional, Callable
from dataclasses import dataclass, field
from enum import Enum
import time

# Debug print helper
def _debug(msg: str):
    print(f"[PHASE8] [ReActLoop] {msg}")


class ReActStepType(Enum):
    """Types of steps in ReAct"""
    THINK = "think"
    ACT = "act"
    OBSERVE = "observe"
    ANSWER = "answer"


@dataclass
class ReActStep:
    """A single step in the ReAct reasoning process"""
    step_type: ReActStepType
    content: str
    tool_name: str = ""
    tool_input: Dict[str, Any] = field(default_factory=dict)
    tool_output: str = ""
    timestamp: float = field(default_factory=time.time)
    error: str = ""


@dataclass
class ReActResult:
    """Result of a ReAct execution"""
    success: bool
    final_answer: str
    steps: List[ReActStep]
    total_steps: int
    total_time: float
    tool_calls: int
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "final_answer": self.final_answer,
            "steps": [
                {
                    "type": s.step_type.value,
                    "content": s.content,
                    "tool": s.tool_name,
                    "output": s.tool_output,
                    "error": s.error,
                }
                for s in self.steps
            ],
            "total_steps": self.total_steps,
            "total_time": self.total_time,
            "tool_calls": self.tool_calls,
            "error": self.error,
        }


class ReActAgent:
    """ReAct (Reasoning + Acting) Agent

    Implements the ReAct paradigm where the agent:
    1. Thinks about the current state
    2. Decides on an action
    3. Executes the action
    4. Observes the result
    5. Repeats until task is complete
    """

    def __init__(
        self,
        llm_client,  # LLM client for reasoning
        tool_executor,  # Tool executor
        max_iterations: int = 10,
        max_tool_calls: int = 50,
    ):
        self.llm_client = llm_client
        self.tool_executor = tool_executor
        self.max_iterations = max_iterations
        self.max_tool_calls = max_tool_calls

        # System prompt for ReAct reasoning (formatted with limits)
        self.system_prompt = """你是一个 ReAct 代理，逐步推理。

## 核心循环
1. **Think**: 分析问题，制定下一步行动
2. **Act**: 使用工具执行行动
3. **Observe**: 观察工具返回结果
4. **Answer**: 结果满意时给出最终答案

## JSON 输出格式
```json
{"type": "think", "content": "分析..."}
{"type": "act", "tool": "tool_name", "input": {...}, "reasoning": "为什么这样做"}
{"type": "answer", "content": "最终答案"}
```

## 规则
- 迭代最多 {max_iterations} 次
- 工具调用最多 {max_tool_calls} 次
- 失败后诊断原因再换策略
- 达到限制时返回最佳结果

## 工具使用原则
- 优先使用 read_file/bash 工具获取信息
- 不要依赖猜测或记忆
- 验证每一步的结果再继续
- 复杂任务分解为多个步骤

## 结束条件
- 工具结果 pass → 返回 answer
- 工具结果 fail → 诊断原因，换策略重试
- 达到最大迭代 → 返回当前最佳结果""".format(
            max_iterations=max_iterations,
            max_tool_calls=max_tool_calls
        )

    async def run(self, task: str, context: Dict[str, Any] = None) -> ReActResult:
        """Run the ReAct agent on a task

        Args:
            task: The task to perform
            context: Additional context information

        Returns:
            ReActResult with the execution trace and final answer
        """
        start_time = time.time()
        steps: List[ReActStep] = []
        tool_call_count = 0
        context = context or {}

        # Build initial messages
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": f"Task: {task}\n\nContext: {context}"},
        ]

        iteration = 0
        while iteration < self.max_iterations:
            iteration += 1

            # Get LLM response
            response = await self._get_llm_response(messages)

            # Parse response
            step = self._parse_response(response)
            steps.append(step)

            # Add to messages
            messages.append({"role": "assistant", "content": response})

            # Process based on step type
            if step.step_type == ReActStepType.THINK:
                # Just continue to next iteration
                continue

            elif step.step_type == ReActStepType.ACT:
                if tool_call_count >= self.max_tool_calls:
                    steps.append(ReActStep(
                        step_type=ReActStepType.ANSWER,
                        content="Maximum tool calls reached. Please try a simpler approach."
                    ))
                    break

                # Execute tool
                try:
                    tool_output = await self._execute_tool(step.tool_name, step.tool_input)
                    step.tool_output = tool_output

                    # Add observation
                    observe_step = ReActStep(
                        step_type=ReActStepType.OBSERVE,
                        content=f"Tool output: {tool_output[:500]}...",
                        tool_name=step.tool_name,
                    )
                    steps.append(observe_step)
                    messages.append({
                        "role": "user",
                        "content": f"Observation: {tool_output}"
                    })

                    tool_call_count += 1

                except Exception as e:
                    step.error = str(e)
                    messages.append({
                        "role": "user",
                        "content": f"Error: {str(e)}"
                    })

            elif step.step_type == ReActStepType.ANSWER:
                # Task completed
                break

        # Build final result
        total_time = time.time() - start_time
        final_answer = self._get_final_answer(steps)

        return ReActResult(
            success=bool(final_answer) and tool_call_count < self.max_tool_calls,
            final_answer=final_answer,
            steps=steps,
            total_steps=len(steps),
            total_time=total_time,
            tool_calls=tool_call_count,
        )

    async def _get_llm_response(self, messages: List[Dict]) -> str:
        """Get response from LLM

        This is a simplified implementation.
        In practice, this would call the actual LLM.
        """
        # For now, use a simple implementation that echoes the input
        # In practice, this would use the actual LLM client
        return '{"type": "answer", "content": "Task completed."}'

    def _parse_response(self, response: str) -> ReActStep:
        """Parse LLM response into a ReActStep"""
        import json

        try:
            data = json.loads(response)
            step_type = ReActStepType(data.get("type", "think"))

            if step_type == ReActStepType.ACT:
                return ReActStep(
                    step_type=step_type,
                    content=data.get("reasoning", ""),
                    tool_name=data.get("tool", ""),
                    tool_input=data.get("input", {}),
                )
            else:
                return ReActStep(
                    step_type=step_type,
                    content=data.get("content", ""),
                )

        except (json.JSONDecodeError, KeyError):
            # Default to think step if parsing fails
            return ReActStep(
                step_type=ReActStepType.THINK,
                content=response[:200],
            )

    async def _execute_tool(self, tool_name: str, tool_input: Dict[str, Any]) -> str:
        """Execute a tool and return the output"""
        if hasattr(self.tool_executor, "execute"):
            result = await self.tool_executor.execute(tool_name, tool_input)
            return str(result)
        elif hasattr(self.tool_executor, tool_name):
            func = getattr(self.tool_executor, tool_name)
            if asyncio.iscoroutinefunction(func):
                result = await func(**tool_input)
            else:
                result = func(**tool_input)
            return str(result)
        else:
            raise ValueError(f"Unknown tool: {tool_name}")


def _get_final_answer(self, steps: List[ReActStep]) -> str:
    """Extract the final answer from steps"""
    for step in reversed(steps):
        if step.step_type == ReActStepType.ANSWER:
            return step.content
    return ""


# Add asyncio import for async tool execution
import asyncio
