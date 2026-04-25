"""Memory Decay

Manages memory lifecycle and decay over time.
[PHASE9] 长期记忆 - MemoryDecay
"""

from typing import Dict, List, Optional, Callable
from dataclasses import dataclass
from enum import Enum
import time
import threading

# Debug print helper
def _debug(msg: str):
    print(f"[PHASE9] [MemoryDecay] {msg}")


class DecayStrategy(Enum):
    """Memory decay strategy"""
    NONE = "none"
    LINEAR = "linear"
    EXPONENTIAL = "exponential"
    ADAPTIVE = "adaptive"


@dataclass
class DecayConfig:
    """Configuration for memory decay"""
    strategy: DecayStrategy = DecayStrategy.EXPONENTIAL
    base_decay_rate: float = 0.01  # Per day
    min_importance: float = 0.1    # Delete below this
    decay_check_interval: float = 3600.0  # seconds
    max_age_days: float = 365.0    # Max age before auto-delete


class MemoryDecay:
    """Manages memory decay and cleanup

    Implements various decay strategies to manage
    memory importance over time and remove stale memories.
    """

    def __init__(
        self,
        vector_store=None,
        config: DecayConfig = None,
    ):
        self.vector_store = vector_store
        self.config = config or DecayConfig()
        self._decay_hooks: List[Callable] = []
        self._last_decay_time: float = 0
        self._lock = threading.Lock()

    def register_decay_hook(self, hook: Callable[[str], None]) -> None:
        """Register a hook to call when memory decays

        Args:
            hook: Callable that takes entry_id
        """
        self._decay_hooks.append(hook)

    def calculate_importance(
        self,
        entry,
        current_time: float = None
    ) -> float:
        """Calculate current importance of an entry

        Args:
            entry: Memory entry
            current_time: Current timestamp (uses time.time() if None)

        Returns:
            Importance score (0.0 to 1.0)
        """
        if current_time is None:
            current_time = time.time()

        initial_importance = entry.metadata.get("importance", entry.importance)
        age_days = (current_time - entry.created_at) / 86400

        if self.config.strategy == DecayStrategy.NONE:
            return initial_importance

        elif self.config.strategy == DecayStrategy.LINEAR:
            # Linear decay: importance = initial - rate * age
            decay = self.config.base_decay_rate * age_days
            return max(self.config.min_importance, initial_importance - decay)

        elif self.config.strategy == DecayStrategy.EXPONENTIAL:
            # Exponential decay: importance = initial * e^(-rate * age)
            import math
            decay = math.exp(-self.config.base_decay_rate * age_days)
            return max(self.config.min_importance, initial_importance * decay)

        elif self.config.strategy == DecayStrategy.ADAPTIVE:
            # Adaptive: consider access frequency
            import math
            access_bonus = min(1.0, entry.access_count / 10)
            base_decay = math.exp(-self.config.base_decay_rate * age_days)
            return max(
                self.config.min_importance,
                (initial_importance * base_decay) + (access_bonus * 0.1)
            )

        return initial_importance

    def should_delete(self, entry, current_time: float = None) -> bool:
        """Determine if entry should be deleted

        Args:
            entry: Memory entry
            current_time: Current timestamp

        Returns:
            True if entry should be deleted
        """
        if current_time is None:
            current_time = time.time()

        # Check max age
        age_days = (current_time - entry.created_at) / 86400
        if age_days > self.config.max_age_days:
            return True

        # Check importance threshold
        importance = self.calculate_importance(entry, current_time)
        if importance < self.config.min_importance:
            return True

        return False

    def run_decay(self) -> List[str]:
        """Run decay process and return IDs of deleted entries

        Returns:
            List of deleted entry IDs
        """
        with self._lock:
            self._last_decay_time = time.time()
            deleted_ids: List[str] = []

            if not self.vector_store:
                return deleted_ids

            for entry in self.vector_store.get_all():
                if self.should_delete(entry):
                    self.vector_store.delete(entry.id)
                    deleted_ids.append(entry.id)

                    # Call decay hooks
                    for hook in self._decay_hooks:
                        try:
                            hook(entry.id)
                        except Exception:
                            pass

            return deleted_ids

    def boost_importance(self, entry_id: str, boost: float = 0.1) -> bool:
        """Boost importance of an entry

        Args:
            entry_id: ID of entry to boost
            boost: Amount to boost

        Returns:
            True if successful
        """
        if not self.vector_store:
            return False

        entry = self.vector_store.get(entry_id)
        if not entry:
            return False

        current = entry.metadata.get("importance", entry.importance)
        entry.metadata["importance"] = min(1.0, current + boost)
        return True

    def get_decay_stats(self) -> Dict:
        """Get decay statistics

        Returns:
            Dictionary of stats
        """
        return {
            "strategy": self.config.strategy.value,
            "base_decay_rate": self.config.base_decay_rate,
            "min_importance": self.config.min_importance,
            "max_age_days": self.config.max_age_days,
            "last_decay_time": self._last_decay_time,
            "registered_hooks": len(self._decay_hooks),
        }


# Global decay manager
_decay: Optional[MemoryDecay] = None


def get_decay() -> MemoryDecay:
    """Get the global memory decay manager"""
    global _decay
    if _decay is None:
        _decay = MemoryDecay()
    return _decay