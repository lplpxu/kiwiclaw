"""Task Verification Module

Verifies task completion and quality.
"""

from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from enum import Enum
import re


class CompletionLevel(Enum):
    """How completely the task was completed"""
    NOT_STARTED = 0
    PARTIAL = 1
    MOSTLY_COMPLETE = 2
    COMPLETE = 3
    EXCEEDS_EXPECTATIONS = 4


@dataclass
class QualityScore:
    """Quality score for task completion"""
    overall: float  # 0.0 - 1.0
    correctness: float = 0.0  # 0.0 - 1.0
    completeness: float = 0.0  # 0.0 - 1.0
    efficiency: float = 0.0  # 0.0 - 1.0
    details: Dict[str, Any] = None

    def __post_init__(self):
        if self.details is None:
            self.details = {}

    def to_dict(self) -> dict:
        return {
            "overall": self.overall,
            "correctness": self.correctness,
            "completeness": self.completeness,
            "efficiency": self.efficiency,
            "details": self.details,
        }


@dataclass
class VerificationResult:
    """Result of task verification"""
    task: str
    completed: bool
    completion_level: CompletionLevel
    quality_score: QualityScore
    missing_items: List[str]
    issues: List[str]
    suggestions: List[str]
    verified_at: float = 0

    def to_dict(self) -> dict:
        return {
            "task": self.task,
            "completed": self.completed,
            "completion_level": self.completion_level.value,
            "quality_score": self.quality_score.to_dict(),
            "missing_items": self.missing_items,
            "issues": self.issues,
            "suggestions": self.suggestions,
            "verified_at": self.verified_at,
        }


class TaskVerifier:
    """Verifies that tasks have been completed correctly

    Checks completion against:
    - User-provided criteria
    - Implicit requirements
    - Output validation
    """

    def __init__(self, llm_client=None):
        self.llm_client = llm_client

    async def verify(
        self,
        task: str,
        result: str,
        expected_output: str = None,
        context: Dict[str, Any] = None,
    ) -> VerificationResult:
        """Verify task completion

        Args:
            task: The original task description
            result: The agent's output/result
            expected_output: Optional expected output to compare against
            context: Additional context

        Returns:
            VerificationResult with details
        """
        import time

        print(f"[DEBUG verifier] verify() called | task_len={len(task)}, result_len={len(result)}")

        missing = []
        issues = []
        suggestions = []

        # Check for basic completion signals
        result_lower = result.lower()

        # Check if result is empty or too short
        if not result or len(result.strip()) < 10:
            missing.append("Result is empty or too short")
            completion_level = CompletionLevel.NOT_STARTED
        else:
            completion_level = CompletionLevel.PARTIAL

        # Check for common completion indicators
        completion_indicators = [
            "done", "completed", "finished", "ready", "here is", "result",
            "answer", "output", "summary", "implemented", "created"
        ]

        has_indicator = any(ind in result_lower for ind in completion_indicators)

        if has_indicator:
            completion_level = CompletionLevel.MOSTLY_COMPLETE

        # Check for error indicators
        error_indicators = [
            "error", "failed", "exception", "cannot", "unable", "not found",
            "does not exist", "invalid", "timeout"
        ]

        has_error = any(ind in result_lower for ind in error_indicators)
        if has_error:
            issues.append("Result contains error indicators")
            completion_level = max(completion_level.value, CompletionLevel.PARTIAL)

        # Check task-specific completion
        if "search" in task.lower():
            if not any(word in result_lower for word in ["found", "result", "according", "information"]):
                missing.append("Search results not provided")

        if "create" in task.lower() or "make" in task.lower():
            if "created" not in result_lower and "implemented" not in result_lower:
                missing.append("No confirmation of creation/implementation")

        if "find" in task.lower() or "look" in task.lower():
            if not any(word in result_lower for word in ["found", "located", "here"]):
                missing.append("No findings reported")

        # Calculate quality score
        quality = self._calculate_quality(
            task=task,
            result=result,
            completion_level=completion_level,
            issues=issues,
            missing=missing
        )

        # Determine if completed
        completed = (
            completion_level in (CompletionLevel.COMPLETE, CompletionLevel.EXCEEDS_EXPECTATIONS) and
            len(missing) == 0 and
            len(issues) == 0
        )

        # Generate suggestions
        if missing:
            suggestions.append(f"Address missing items: {', '.join(missing[:3])}")
        if issues:
            suggestions.append(f"Fix issues: {', '.join(issues[:3])}")
        if completion_level.value < CompletionLevel.COMPLETE.value:
            suggestions.append("Provide more detailed output")

        return VerificationResult(
            task=task,
            completed=completed,
            completion_level=completion_level,
            quality_score=quality,
            missing_items=missing,
            issues=issues,
            suggestions=suggestions,
            verified_at=time.time(),
        )

    def _calculate_quality(
        self,
        task: str,
        result: str,
        completion_level: CompletionLevel,
        issues: List[str],
        missing: List[str],
    ) -> QualityScore:
        """Calculate quality score for the result"""
        import json

        details = {}

        # Correctness: Based on error indicators
        error_count = len(issues)
        correctness = max(0.0, 1.0 - (error_count * 0.2))
        details["error_count"] = error_count

        # Completeness: Based on completion level and missing items
        completeness = completion_level.value / CompletionLevel.EXCEEDS_EXPECTATIONS.value
        if missing:
            completeness *= max(0.0, 1.0 - (len(missing) * 0.15))
        details["missing_count"] = len(missing)

        # Efficiency: Based on result length vs task complexity
        task_words = len(task.split())
        result_words = len(result.split())
        expected_words = task_words * 10  # Rough estimate

        if result_words < expected_words * 0.5:
            efficiency = 0.5  # Too short
        elif result_words > expected_words * 3:
            efficiency = 0.7  # Could be more concise
        else:
            efficiency = 1.0  # Appropriate length

        details["task_words"] = task_words
        details["result_words"] = result_words

        # Overall: Weighted average
        overall = (correctness * 0.4 + completeness * 0.4 + efficiency * 0.2)

        return QualityScore(
            overall=overall,
            correctness=correctness,
            completeness=completeness,
            efficiency=efficiency,
            details=details,
        )

    def verify_structure(self, result: str, required_sections: List[str]) -> List[str]:
        """Verify that result contains required sections

        Args:
            result: The result text
            result: List of required section names

        Returns:
            List of missing section names
        """
        missing = []
        result_lower = result.lower()

        for section in required_sections:
            if section.lower() not in result_lower:
                missing.append(section)

        return missing

    def verify_format(self, result: str, format_type: str) -> bool:
        """Verify result matches expected format

        Args:
            result: The result text
            format_type: Expected format (json, markdown, plain_text, etc.)

        Returns:
            True if format is correct
        """
        if format_type == "json":
            try:
                import json
                json.loads(result)
                return True
            except:
                return False

        elif format_type == "markdown":
            # Check for markdown indicators
            markdown_indicators = ["#", "##", "- ", "* ", "```", "**"]
            return any(indicator in result for indicator in markdown_indicators)

        elif format_type == "plain_text":
            # Should not contain heavy markup
            return True

        return True

    def extract_criteria(self, task: str) -> List[str]:
        """Extract verification criteria from task description

        Args:
            task: The task description

        Returns:
            List of criteria to check
        """
        criteria = []

        # Extract "should" statements
        should_pattern = r'should\s+(\w+)'
        matches = re.findall(should_pattern, task.lower())
        criteria.extend(matches)

        # Extract "must" statements
        must_pattern = r'must\s+(\w+)'
        matches = re.findall(must_pattern, task.lower())
        criteria.extend(matches)

        # Extract "need" statements
        need_pattern = r'need\s+to\s+(\w+)'
        matches = re.findall(need_pattern, task.lower())
        criteria.extend(matches)

        return list(set(criteria))  # Remove duplicates
