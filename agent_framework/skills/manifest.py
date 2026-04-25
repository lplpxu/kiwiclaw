"""Skill Manifest and Specification

Defines skill metadata and capabilities.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional
from enum import Enum
import json
import time


class SkillTrigger(Enum):
    """How a skill is triggered"""
    MANUAL = "manual"          # Explicit invocation
    PATTERN = "pattern"       # Regex pattern match
    CONTEXT = "context"       # Contextual conditions
    LEARNED = "learned"       # Learned from experience


class SkillStatus(Enum):
    """Skill lifecycle status"""
    DRAFT = "draft"
    ACTIVE = "active"
    IMPROVING = "improving"
    DEPRECATED = "deprecated"


@dataclass
class SkillSpec:
    """Specification for a single skill"""
    name: str
    description: str
    trigger: SkillTrigger = SkillTrigger.MANUAL

    # Pattern for triggered skills
    pattern: str = ""

    # Skill content/code
    code: str = ""
    language: str = "python"

    # Metadata
    version: str = "1.0.0"
    author: str = ""
    tags: List[str] = field(default_factory=list)

    # Usage statistics
    use_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    total_duration_ms: float = 0

    # Learning data
    last_used: float = 0
    last_success: float = 0
    avg_quality: float = 0.0

    # Dependencies
    requires: List[str] = field(default_factory=list)  # Other skills
    provides_context: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "trigger": self.trigger.value,
            "pattern": self.pattern,
            "code": self.code,
            "language": self.language,
            "version": self.version,
            "author": self.author,
            "tags": self.tags,
            "use_count": self.use_count,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "total_duration_ms": self.total_duration_ms,
            "last_used": self.last_used,
            "last_success": self.last_success,
            "avg_quality": self.avg_quality,
            "requires": self.requires,
            "provides_context": self.provides_context,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SkillSpec":
        return cls(
            name=data["name"],
            description=data.get("description", ""),
            trigger=SkillTrigger(data.get("trigger", "manual")),
            pattern=data.get("pattern", ""),
            code=data.get("code", ""),
            language=data.get("language", "python"),
            version=data.get("version", "1.0.0"),
            author=data.get("author", ""),
            tags=data.get("tags", []),
            use_count=data.get("use_count", 0),
            success_count=data.get("success_count", 0),
            failure_count=data.get("failure_count", 0),
            total_duration_ms=data.get("total_duration_ms", 0),
            last_used=data.get("last_used", 0),
            last_success=data.get("last_success", 0),
            avg_quality=data.get("avg_quality", 0.0),
            requires=data.get("requires", []),
            provides_context=data.get("provides_context", []),
        )


@dataclass
class SkillManifest:
    """Manifest for a skill package

    Contains multiple related skills and their relationships.
    """
    name: str
    version: str
    description: str = ""
    skills: List[SkillSpec] = field(default_factory=list)

    # Relationships
    dependencies: List[str] = field(default_factory=list)  # Other manifests
    conflicts: List[str] = field(default_factory=list)  # Incompatible skills

    # Metadata
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    author: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "skills": [s.to_dict() for s in self.skills],
            "dependencies": self.dependencies,
            "conflicts": self.conflicts,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "author": self.author,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SkillManifest":
        return cls(
            name=data["name"],
            version=data["version"],
            description=data.get("description", ""),
            skills=[SkillSpec.from_dict(s) for s in data.get("skills", [])],
            dependencies=data.get("dependencies", []),
            conflicts=data.get("conflicts", []),
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time()),
            author=data.get("author", ""),
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_json(cls, json_str: str) -> "SkillManifest":
        return cls.from_dict(json.loads(json_str))
