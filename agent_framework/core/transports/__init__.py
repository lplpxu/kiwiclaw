"""Transport Module - LLM Provider Adapters

Provides unified interface for multiple LLM providers.
Inspired by hermes-agent/agent/transports/
"""

from .base import (
    ProviderTransport,
    TransportRegistry,
    get_transport,
    register_transport,
    list_transports,
    has_transport,
)
from .types import NormalizedResponse, ToolCall, Usage, build_tool_call, map_finish_reason

__all__ = [
    # ABC
    "ProviderTransport",
    # Registry functions
    "register_transport",
    "get_transport",
    "list_transports",
    "has_transport",
    "TransportRegistry",
    # Types
    "NormalizedResponse",
    "ToolCall",
    "Usage",
    # Helpers
    "build_tool_call",
    "map_finish_reason",
]

# Auto-import transports to trigger registration
from . import anthropic  # noqa: F401
from . import openai  # noqa: F401
