"""Skill Registry

Global registry for managing skills.
[PHASE7] 技能系统 - SkillRegistry
"""

from typing import Dict, List, Optional, Callable, Any
import threading

from .manifest import SkillManifest, SkillSpec, SkillTrigger

# Debug print helper
def _debug(msg: str):
    print(f"[PHASE7] [SkillRegistry] {msg}")


class SkillRegistry:
    """Global skill registry

    Provides centralized access to all available skills.
    Thread-safe registration and lookup.
    """

    def __init__(self):
        self._skills: Dict[str, SkillSpec] = {}
        self._manifests: Dict[str, SkillManifest] = {}
        self._lock = threading.Lock()

    def register(self, skill: SkillSpec) -> None:
        """Register a skill

        Args:
            skill: Skill specification to register
        """
        with self._lock:
            self._skills[skill.name] = skill

    def unregister(self, skill_name: str) -> bool:
        """Unregister a skill

        Args:
            skill_name: Name of skill to remove

        Returns:
            True if skill was removed
        """
        with self._lock:
            if skill_name in self._skills:
                del self._skills[skill_name]
                return True
            return False

    def get(self, skill_name: str) -> Optional[SkillSpec]:
        """Get a skill by name

        Args:
            skill_name: Name of skill to retrieve

        Returns:
            SkillSpec if found, None otherwise
        """
        with self._lock:
            return self._skills.get(skill_name)

    def list(self, trigger: SkillTrigger = None) -> List[SkillSpec]:
        """List all skills, optionally filtered by trigger

        Args:
            trigger: Optional trigger type to filter by

        Returns:
            List of matching skills
        """
        with self._lock:
            if trigger is None:
                return list(self._skills.values())
            return [s for s in self._skills.values() if s.trigger == trigger]

    def search(self, query: str) -> List[SkillSpec]:
        """Search skills by name or description

        Args:
            query: Search query string

        Returns:
            List of matching skills
        """
        with self._lock:
            query_lower = query.lower()
            return [
                s for s in self._skills.values()
                if query_lower in s.name.lower() or query_lower in s.description.lower()
            ]

    def register_manifest(self, manifest: SkillManifest) -> None:
        """Register all skills from a manifest

        Args:
            manifest: Manifest containing skills to register
        """
        with self._lock:
            self._manifests[manifest.name] = manifest
            for skill in manifest.skills:
                self._skills[skill.name] = skill

    def get_manifest(self, name: str) -> Optional[SkillManifest]:
        """Get a manifest by name

        Args:
            name: Manifest name

        Returns:
            SkillManifest if found
        """
        with self._lock:
            return self._manifests.get(name)

    def list_manifests(self) -> List[SkillManifest]:
        """List all registered manifests

        Returns:
            List of manifests
        """
        with self._lock:
            return list(self._manifests.values())

    def find_by_pattern(self, text: str) -> List[SkillSpec]:
        """Find skills that match a text pattern

        Args:
            text: Text to match against skill patterns

        Returns:
            List of matching skills
        """
        import re
        with self._lock:
            matches = []
            for skill in self._skills.values():
                if skill.pattern and skill.trigger == SkillTrigger.PATTERN:
                    try:
                        if re.search(skill.pattern, text):
                            matches.append(skill)
                    except re.error:
                        continue
            return matches

    def find_by_tag(self, tag: str) -> List[SkillSpec]:
        """Find skills with a specific tag

        Args:
            tag: Tag to search for

        Returns:
            List of skills with the tag
        """
        with self._lock:
            return [s for s in self._skills.values() if tag in s.tags]

    def get_statistics(self) -> Dict[str, Any]:
        """Get registry statistics

        Returns:
            Dictionary of statistics
        """
        with self._lock:
            total_uses = sum(s.use_count for s in self._skills.values())
            total_success = sum(s.success_count for s in self._skills.values())
            return {
                "total_skills": len(self._skills),
                "total_manifests": len(self._manifests),
                "total_uses": total_uses,
                "total_successes": total_success,
                "success_rate": total_success / total_uses if total_uses > 0 else 0,
            }

    def clear(self) -> None:
        """Clear all skills and manifests"""
        with self._lock:
            self._skills.clear()
            self._manifests.clear()


# Global registry instance
_registry: Optional[SkillRegistry] = None


def get_registry() -> SkillRegistry:
    """Get the global skill registry"""
    global _registry
    if _registry is None:
        _registry = SkillRegistry()
    return _registry