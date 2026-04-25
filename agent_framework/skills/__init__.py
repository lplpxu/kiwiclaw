"""Skills Module - Self-Improvement System

Provides skill creation, learning, and execution capabilities.
Inspired by hermes-agent's skill system.
"""

from .manifest import SkillManifest, SkillSpec, SkillTrigger, SkillStatus
from .executor import SkillExecutor, SkillResult, ExecutionResult
from .learner import SkillLearner, LearningResult, LearningStrategy
from .registry import SkillRegistry, get_registry

__all__ = [
    # Manifest
    "SkillManifest",
    "SkillSpec",
    "SkillTrigger",
    "SkillStatus",
    # Executor
    "SkillExecutor",
    "SkillResult",
    "ExecutionResult",
    # Learner
    "SkillLearner",
    "LearningResult",
    "LearningStrategy",
    # Registry
    "SkillRegistry",
    "get_registry",
]
