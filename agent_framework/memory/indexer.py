"""Memory Indexer

Automatically indexes new memories and manages memory organization.
[PHASE9] 长期记忆 - MemoryIndexer
"""

from typing import Dict, List, Optional, Set
from dataclasses import dataclass, field
import time
import threading

from .vector import VectorStore, MemoryEntry

# Debug print helper
def _debug(msg: str):
    print(f"[PHASE9] [MemoryIndexer] {msg}")


@dataclass
class IndexConfig:
    """Configuration for memory indexing"""
    auto_index: bool = True
    index_interval: float = 60.0  # seconds
    max_entries_before_index: int = 100
    min_importance_for_index: float = 0.3


class MemoryIndexer:
    """Indexes new memories and maintains searchability

    Automatically processes new memory entries to keep
    the memory system organized and searchable.
    """

    def __init__(
        self,
        vector_store: VectorStore = None,
        config: IndexConfig = None,
    ):
        self.vector_store = vector_store or VectorStore()
        self.config = config or IndexConfig()
        self._index: Dict[str, Set[str]] = {}  # keyword -> entry IDs
        self._tags: Dict[str, Set[str]] = {}    # tag -> entry IDs
        self._categories: Dict[str, Set[str]] = {}  # category -> entry IDs
        self._pending_entries: List[str] = []  # Entry IDs pending indexing
        self._lock = threading.Lock()
        self._last_index_time: float = 0

    def add_entry(self, entry: MemoryEntry) -> None:
        """Add a new entry for indexing

        Args:
            entry: Memory entry to index
        """
        with self._lock:
            self._pending_entries.append(entry.id)

            # Auto-index if threshold reached
            if self.config.auto_index:
                if len(self._pending_entries) >= self.config.max_entries_before_index:
                    self._run_indexing()

    def index_entry(self, entry: MemoryEntry) -> None:
        """Index a single entry

        Args:
            entry: Entry to index
        """
        # Index keywords
        self._index_keywords(entry)

        # Index tags
        for tag in entry.metadata.get("tags", []):
            self._add_to_index(self._tags, tag, entry.id)

        # Index category
        category = entry.metadata.get("category")
        if category:
            self._add_to_index(self._categories, category, entry.id)

    def _index_keywords(self, entry: MemoryEntry) -> None:
        """Extract and index keywords from content"""
        words = entry.content.lower().split()
        stop_words = {"the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "of", "with", "by"}

        for word in words:
            # Clean word
            word = "".join(c for c in word if c.isalnum())
            if len(word) > 2 and word not in stop_words:
                self._add_to_index(self._index, word, entry.id)

    def _add_to_index(self, index: Dict[str, Set[str]], key: str, entry_id: str) -> None:
        """Add entry to an index"""
        if key not in index:
            index[key] = set()
        index[key].add(entry_id)

    def _run_indexing(self) -> None:
        """Run indexing on pending entries"""
        self._last_index_time = time.time()

        while self._pending_entries:
            entry_id = self._pending_entries.pop(0)
            entry = self.vector_store.get(entry_id)
            if entry:
                self.index_entry(entry)

    def search_index(self, keyword: str) -> List[str]:
        """Search entries by keyword

        Args:
            keyword: Keyword to search

        Returns:
            List of entry IDs
        """
        with self._lock:
            return list(self._index.get(keyword.lower(), set()))

    def search_by_tag(self, tag: str) -> List[str]:
        """Search entries by tag

        Args:
            tag: Tag to search

        Returns:
            List of entry IDs
        """
        with self._lock:
            return list(self._tags.get(tag, set()))

    def search_by_category(self, category: str) -> List[str]:
        """Search entries by category

        Args:
            category: Category to search

        Returns:
            List of entry IDs
        """
        with self._lock:
            return list(self._categories.get(category, set()))

    def get_related_entries(self, entry_id: str, limit: int = 5) -> List[str]:
        """Get entries related to a given entry

        Args:
            entry_id: Source entry ID
            limit: Maximum results

        Returns:
            List of related entry IDs
        """
        with self._lock:
            entry = self.vector_store.get(entry_id)
            if not entry:
                return []

            related_ids: Set[str] = set()

            # Find by shared keywords
            words = entry.content.lower().split()
            for word in words:
                word = "".join(c for c in word if c.isalnum())
                if len(word) > 2:
                    related_ids.update(self._index.get(word, set()))

            # Remove self
            related_ids.discard(entry_id)

            return list(related_ids)[:limit]

    def force_index(self) -> int:
        """Force indexing of all pending entries

        Returns:
            Number of entries indexed
        """
        with self._lock:
            self._run_indexing()
            return len(self._pending_entries)

    def get_stats(self) -> Dict[str, int]:
        """Get indexing statistics"""
        with self._lock:
            return {
                "indexed_keywords": len(self._index),
                "indexed_tags": len(self._tags),
                "indexed_categories": len(self._categories),
                "pending_entries": len(self._pending_entries),
                "last_index_time": self._last_index_time,
            }


# Global indexer
_indexer: Optional[MemoryIndexer] = None


def get_indexer() -> MemoryIndexer:
    """Get the global memory indexer"""
    global _indexer
    if _indexer is None:
        _indexer = MemoryIndexer()
    return _indexer