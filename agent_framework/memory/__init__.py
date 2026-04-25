"""Memory Module - Long-term Memory System

Provides vector storage, semantic search, and memory management.
"""

from .vector import VectorStore, MemoryEntry, VectorResult, get_vector_store
from .search import SemanticSearch, SearchResult, get_semantic_search
from .indexer import MemoryIndexer
from .decay import MemoryDecay, DecayStrategy

__all__ = [
    "VectorStore",
    "MemoryEntry",
    "VectorResult",
    "SemanticSearch",
    "SearchResult",
    "MemoryIndexer",
    "MemoryDecay",
    "DecayStrategy",
    "get_vector_store",
    "get_semantic_search",
]