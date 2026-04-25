"""Skill Learner

Learns from skill execution experience to improve skills over time.
[PHASE7] 技能系统 - SkillLearner
"""

import time
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from enum import Enum

from .manifest import SkillSpec, SkillStatus

# Debug print helper
def _debug(msg: str):
    print(f"[PHASE7] [SkillLearner] {msg}")


class LearningStrategy(Enum):
    """Strategy for learning from experience"""
    NONE = "none"
    ON_SUCCESS = "on_success"       # Learn only from successes
    ON_FAILURE = "on_failure"       # Learn only from failures
    ALWAYS = "always"               # Learn from both


@dataclass
class LearningResult:
    """Result of a learning operation"""
    skill_name: str
    improved: bool
    previous_code: str
    new_code: str
    improvement_notes: str = ""
    quality_before: float = 0.0
    quality_after: float = 0.0


@dataclass
class SkillLearner:
    """Learns from skill execution experience

    Analyzes execution results and modifies skills to improve performance.
    """
    strategy: LearningStrategy = LearningStrategy.ON_FAILURE
    min_quality_threshold: float = 0.3
    max_iterations: int = 3

    # Learning history
    learning_history: List[LearningResult] = field(default_factory=list)

    def learn_from_result(self, skill: SkillSpec, result: Any) -> Optional[LearningResult]:
        """Learn from a skill execution result

        Args:
            skill: The skill that was executed
            result: The execution result

        Returns:
            LearningResult if improvement was made, None otherwise
        """
        if self.strategy == LearningStrategy.NONE:
            return None

        # Determine if we should learn from this result
        should_learn = self._should_learn(result)
        if not should_learn:
            return None

        # Analyze the execution
        analysis = self._analyze_execution(skill, result)
        if not analysis:
            return None

        # Generate improved code
        improved_code = self._improve_code(skill, analysis)
        if not improved_code:
            return None

        # Create learning result
        learning_result = LearningResult(
            skill_name=skill.name,
            improved=True,
            previous_code=skill.code,
            new_code=improved_code,
            improvement_notes=analysis.get("notes", ""),
            quality_before=skill.avg_quality,
            quality_after=skill.avg_quality * 1.1,  # Estimated
        )

        self.learning_history.append(learning_result)
        return learning_result

    def _should_learn(self, result: Any) -> bool:
        """Determine if we should learn from this result"""
        if self.strategy == LearningStrategy.ALWAYS:
            return True

        # Check if result indicates success/failure
        is_success = getattr(result, 'result', None) == "success"
        if self.strategy == LearningStrategy.ON_SUCCESS and is_success:
            return True
        if self.strategy == LearningStrategy.ON_FAILURE and not is_success:
            return True

        return False

    def _analyze_execution(self, skill: SkillSpec, result: Any) -> Optional[Dict[str, Any]]:
        """Analyze execution to find improvement opportunities"""
        if not skill.code:
            return None

        notes = []

        # Check execution time
        duration = getattr(result, 'duration_ms', 0)
        if duration > 5000:
            notes.append(f"Execution took {duration}ms, consider optimizing")

        # Check error rate
        if skill.failure_count > 0:
            failure_rate = skill.failure_count / skill.use_count
            if failure_rate > 0.3:
                notes.append(f"High failure rate: {failure_rate:.1%}")

        # Check output quality
        output = getattr(result, 'output', '')
        if not output and skill.use_count > 3:
            notes.append("No output produced on repeated executions")

        return {"notes": "; ".join(notes)} if notes else None

    def _improve_code(self, skill: SkillSpec, analysis: Dict[str, Any]) -> Optional[str]:
        """Generate improved code based on analysis"""
        # Simple improvement: add error handling if missing
        code = skill.code

        if "error handling" not in code.lower() and "try:" not in code:
            # Try to add basic error handling
            improved = self._add_error_handling(code)
            if improved:
                return improved

        return None

    def _add_error_handling(self, code: str) -> Optional[str]:
        """Add error handling to code"""
        if not code.strip().startswith("async def") and not code.strip().startswith("def"):
            return None

        # Simple approach: wrap in try-except if not present
        if "try:" not in code:
            lines = code.split("\n")
            # Find the function body start
            for i, line in enumerate(lines):
                if line.strip() and not line.strip().startswith("#"):
                    # Assume this is where function body starts
                    indent = len(line) - len(line.lstrip())
                    body_start = i
                    # Find end of function (dedent or next def)
                    body_lines = lines[body_start:]
                    improved_code = "\n".join(lines[:body_start])
                    improved_code += f"\n{' ' * indent}try:\n"
                    for bl in body_lines:
                        improved_code += f"{' ' * (indent + 4)}{bl}\n"
                    improved_code += f"{' ' * indent}except Exception as e:\n"
                    improved_code += f"{' ' * (indent + 4)}result = f'Error: {{e}}'\n"
                    return improved_code

        return None

    def get_learning_stats(self) -> Dict[str, Any]:
        """Get learning statistics"""
        return {
            "total_learning_events": len(self.learning_history),
            "improvements_made": sum(1 for r in self.learning_history if r.improved),
            "strategy": self.strategy.value,
            "min_quality_threshold": self.min_quality_threshold,
        }


# Global learner instance
_learner: Optional[SkillLearner] = None


def get_learner() -> SkillLearner:
    """Get the global skill learner"""
    global _learner
    if _learner is None:
        _learner = SkillLearner()
    return _learner