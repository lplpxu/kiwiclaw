"""Semantic Search

Provides semantic search capabilities for memory.
[PHASE9] 长期记忆 - SemanticSearch
"""

from typing import Dict, List, Optional, Any
from dataclasses import dataclass
import time

from .vector import VectorStore, MemoryEntry, VectorResult

# Debug print helper
def _debug(msg: str):
    print(f"[PHASE9] [SemanticSearch] {msg}")


@dataclass
class SearchResult:
    """Result of a semantic search"""
    entry: MemoryEntry
    score: float
    highlights: List[str]
    query: str


class SemanticSearch:
    """Semantic search for memory

    Provides natural language search over memory entries.
    """

    def __init__(
        self,
        vector_store: VectorStore = None,
        embedding_model: str = "default",
    ):
        self.vector_store = vector_store or VectorStore()
        self.embedding_model = embedding_model
        self._search_history: List[Dict[str, Any]] = []

    def search(
        self,
        query: str,
        limit: int = 10,
        min_score: float = 0.5,
        time_range: tuple = None,
    ) -> List[SearchResult]:
        """Search memory semantically

        Args:
            query: Natural language query
            limit: Maximum results
            min_score: Minimum relevance score
            time_range: Optional (start_time, end_time) tuple

        Returns:
            List of SearchResult
        """
        _debug(f"→ search(query='{query[:50]}...', limit={limit}, min_score={min_score})")
        # Filter function for time range
        filter_func = None
        if time_range:
            start_time, end_time = time_range
            filter_func = lambda e: start_time <= e.created_at <= end_time

        # Search by content (in production, would use embeddings)
        vector_results = self.vector_store.search_by_content(query, limit)

        results = []
        for vr in vector_results:
            if vr.score >= min_score:
                if filter_func and not filter_func(vr.entry):
                    continue
                highlights = self._extract_highlights(vr.entry.content, query)
                results.append(SearchResult(
                    entry=vr.entry,
                    score=vr.score,
                    highlights=highlights,
                    query=query,
                ))

        # Record search
        self._search_history.append({
            "query": query,
            "results_count": len(results),
            "timestamp": time.time(),
        })

        return results

    def search_by_vector(
        self,
        vector: List[float],
        limit: int = 10,
        min_score: float = 0.5,
    ) -> List[SearchResult]:
        """Search by vector similarity

        Args:
            vector: Query vector
            limit: Maximum results
            min_score: Minimum score

        Returns:
            List of SearchResult
        """
        vector_results = self.vector_store.search(vector, limit, min_score)

        results = []
        for vr in vector_results:
            highlights = [vr.entry.content[:200]]
            results.append(SearchResult(
                entry=vr.entry,
                score=vr.score,
                highlights=highlights,
                query="",
            ))

        return results

    def _extract_highlights(self, content: str, query: str) -> List[str]:
        """Extract highlighted snippets from content"""
        query_lower = query.lower()
        content_lower = content.lower()

        highlights = []
        words = query.split()

        # Find sentences containing query words
        sentences = content.split(".")
        for sentence in sentences:
            sentence_lower = sentence.lower()
            if any(word.lower() in sentence_lower for word in words):
                highlights.append(sentence.strip())

        return highlights[:3]  # Limit to 3 highlights

    def get_search_stats(self) -> Dict[str, Any]:
        """Get search statistics"""
        return {
            "total_searches": len(self._search_history),
            "embedding_model": self.embedding_model,
            "vector_store_size": self.vector_store.count(),
        }


# Global semantic search
_semantic_search: Optional[SemanticSearch] = None


def get_semantic_search() -> SemanticSearch:
    """Get the global semantic search"""
    global _semantic_search
    if _semantic_search is None:
        _semantic_search = SemanticSearch()
    return _semantic_search