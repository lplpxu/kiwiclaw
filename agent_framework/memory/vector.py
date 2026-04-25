"""Vector Store

Provides vector storage for semantic memory retrieval.
[PHASE9] 长期记忆 - VectorStore
"""

from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from enum import Enum
import time
import threading

# Debug print helper
def _debug(msg: str):
    print(f"[PHASE9] [VectorStore] {msg}")


class VectorStoreBackend(Enum):
    """Vector store backend type"""
    IN_MEMORY = "in_memory"
    FAISS = "faiss"
    QDRANT = "qdrant"
    CHROMADB = "chromadb"


@dataclass
class MemoryEntry:
    """A single memory entry"""
    id: str
    content: str
    vector: List[float] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    access_count: int = 0
    last_accessed: float = field(default_factory=time.time)
    importance: float = 1.0  # 0.0 to 1.0

    def access(self) -> None:
        """Record an access to this memory"""
        self.access_count += 1
        self.last_accessed = time.time()


@dataclass
class VectorResult:
    """Result of a vector search"""
    entry: MemoryEntry
    score: float  # Similarity score
    distance: float = 0.0


class VectorStore:
    """Vector store for memory entries

    Provides storage and similarity search for memory vectors.
    Supports multiple backend types.
    """

    def __init__(
        self,
        backend: VectorStoreBackend = VectorStoreBackend.IN_MEMORY,
        dimension: int = 1536,
        **backend_config
    ):
        self.backend = backend
        self.dimension = dimension
        self.backend_config = backend_config
        self._entries: Dict[str, MemoryEntry] = {}
        self._lock = threading.Lock()

    def add(self, entry: MemoryEntry) -> bool:
        """Add an entry to the store

        Args:
            entry: Memory entry to add

        Returns:
            True if added successfully
        """
        _debug(f"→ add(entry_id={entry.id}, content_len={len(entry.content)})")
        with self._lock:
            if entry.vector and len(entry.vector) != self.dimension:
                _debug(f"← add {entry.id} failed: dimension mismatch")
                return False
            self._entries[entry.id] = entry
            _debug(f"← add {entry.id} success, total_entries={len(self._entries)}")
            return True

    def get(self, entry_id: str) -> Optional[MemoryEntry]:
        """Get an entry by ID

        Args:
            entry_id: ID of entry to retrieve

        Returns:
            MemoryEntry if found
        """
        _debug(f"→ get(entry_id={entry_id})")
        with self._lock:
            entry = self._entries.get(entry_id)
            if entry:
                entry.access()
                _debug(f"← get {entry_id} found, access_count={entry.access_count}")
            else:
                _debug(f"← get {entry_id} not found")
            return entry

    def delete(self, entry_id: str) -> bool:
        """Delete an entry

        Args:
            entry_id: ID of entry to delete

        Returns:
            True if deleted
        """
        _debug(f"→ delete(entry_id={entry_id})")
        with self._lock:
            if entry_id in self._entries:
                del self._entries[entry_id]
                _debug(f"← delete {entry_id} success, remaining={len(self._entries)}")
                return True
            _debug(f"← delete {entry_id} not found")
            return False

    def search(
        self,
        query_vector: List[float],
        limit: int = 10,
        min_score: float = 0.0,
        filter_func: Callable[[MemoryEntry], bool] = None,
    ) -> List[VectorResult]:
        """Search for similar entries

        Args:
            query_vector: Vector to search for
            limit: Maximum results to return
            min_score: Minimum similarity score
            filter_func: Optional filter function

        Returns:
            List of VectorResult sorted by score
        """
        with self._lock:
            results = []
            for entry in self._entries.values():
                if filter_func and not filter_func(entry):
                    continue
                if entry.vector:
                    score = self._cosine_similarity(query_vector, entry.vector)
                    if score >= min_score:
                        results.append(VectorResult(
                            entry=entry,
                            score=score,
                            distance=1 - score,
                        ))

            # Sort by score descending
            results.sort(key=lambda r: r.score, reverse=True)
            return results[:limit]

    def search_by_content(
        self,
        query: str,
        limit: int = 10,
    ) -> List[VectorResult]:
        """Search by content (requires embedding function)

        Args:
            query: Text query
            limit: Maximum results

        Returns:
            List of VectorResult
        """
        # Note: In production, this would use an embedding model
        # For now, fall back to keyword matching
        with self._lock:
            query_lower = query.lower()
            results = []
            for entry in self._entries.values():
                if query_lower in entry.content.lower():
                    results.append(VectorResult(
                        entry=entry,
                        score=1.0 if query_lower in entry.content.lower() else 0.5,
                        distance=0.0,
                    ))
            return results[:limit]

    def _cosine_similarity(self, v1: List[float], v2: List[float]) -> float:
        """Calculate cosine similarity between two vectors"""
        if len(v1) != len(v2):
            return 0.0

        dot_product = sum(a * b for a, b in zip(v1, v2))
        mag1 = sum(a * a for a in v1) ** 0.5
        mag2 = sum(b * b for b in v2) ** 0.5

        if mag1 == 0 or mag2 == 0:
            return 0.0

        return dot_product / (mag1 * mag2)

    def count(self) -> int:
        """Get total number of entries"""
        with self._lock:
            return len(self._entries)

    def get_all(self) -> List[MemoryEntry]:
        """Get all entries"""
        with self._lock:
            return list(self._entries.values())

    def clear(self) -> None:
        """Clear all entries"""
        with self._lock:
            self._entries.clear()


# Global vector store
_vector_store: Optional[VectorStore] = None


def get_vector_store() -> VectorStore:
    """Get the global vector store"""
    global _vector_store
    if _vector_store is None:
        _vector_store = VectorStore()
    return _vector_store