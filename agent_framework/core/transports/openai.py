"""OpenAI Chat Completions transport.

Provides format conversion and normalization for OpenAI's Chat Completions API.
This is mostly a pass-through since OpenAI already uses the format we normalize to.
"""

from typing import Any, Dict, List, Optional

from .base import ProviderTransport
from .types import NormalizedResponse, ToolCall, Usage, build_tool_call, map_finish_reason


class OpenAITransport(ProviderTransport):
    """Transport for api_mode='chat_completions' (OpenAI-compatible).

    OpenAI's format is already close to our normalized format,
    so this is mostly a pass-through with minimal conversion.
    """

    # OpenAI finish reasons that map to our normalized set
    STOP_REASON_MAP = {
        "stop": "stop",
        "length": "length",
        "tool_calls": "tool_calls",
        "content_filter": "content_filter",
        "function_call": "tool_calls",
    }

    @property
    def api_mode(self) -> str:
        return "chat_completions"

    def convert_messages(self, messages: List[Dict[str, Any]], **kwargs) -> List[Dict[str, Any]]:
        """OpenAI uses standard format, minimal conversion needed.

        Just validates and passes through.
        """
        return messages

    def convert_tools(self, tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """OpenAI tool format is already standard, pass through."""
        return tools

    def build_kwargs(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        **params,
    ) -> Dict[str, Any]:
        """Build OpenAI chat completions kwargs."""
        kwargs: Dict[str, Any] = {
            "model": model,
            "messages": messages,
        }

        if tools:
            kwargs["tools"] = tools

        # Optional params
        if params.get("temperature"):
            kwargs["temperature"] = params["temperature"]
        if params.get("max_tokens"):
            kwargs["max_tokens"] = params["max_tokens"]
        if params.get("top_p"):
            kwargs["top_p"] = params["top_p"]
        if params.get("stop"):
            kwargs["stop"] = params["stop"]
        if params.get("stream"):
            kwargs["stream"] = params["stream"]

        return kwargs

    def normalize_response(self, response: Any, **kwargs) -> NormalizedResponse:
        """Normalize OpenAI response to NormalizedResponse."""
        if response is None:
            return NormalizedResponse(
                content=None,
                tool_calls=None,
                finish_reason="stop",
                reasoning=None,
                usage=None,
                provider_data=None,
            )

        # Extract message
        message = response.get("choices", [{}])[0].get("message", {})

        content = message.get("content")
        tool_calls: Optional[List[ToolCall]] = None

        raw_tool_calls = message.get("tool_calls", [])
        if raw_tool_calls:
            tool_calls = []
            for tc in raw_tool_calls:
                function = tc.get("function", {})
                tool_calls.append(build_tool_call(
                    id=tc.get("id"),
                    name=function.get("name", ""),
                    arguments=function.get("arguments", "{}"),
                ))

        # Extract usage
        usage_data = response.get("usage", {})
        usage = Usage(
            prompt_tokens=usage_data.get("prompt_tokens", 0),
            completion_tokens=usage_data.get("completion_tokens", 0),
            total_tokens=usage_data.get("total_tokens", 0),
            cached_tokens=0,
        )

        # Extract finish reason
        raw_reason = response.get("choices", [{}]).get(0, {}).get("finish_reason", "stop")
        finish_reason = self.map_finish_reason(raw_reason)

        return NormalizedResponse(
            content=content,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            reasoning=None,  # OpenAI doesn't have native thinking block in chat completions
            usage=usage,
            provider_data={"raw_response": response},
        )

    def validate_response(self, response: Any) -> bool:
        """Check OpenAI response structure is valid."""
        if response is None:
            return False
        if not response.get("choices"):
            return False
        return True

    def extract_cache_stats(self, response: Any) -> Optional[Dict[str, int]]:
        """OpenAI doesn't expose cache stats in the same way."""
        return None

    def map_finish_reason(self, raw_reason: str) -> str:
        """Map OpenAI stop reason to normalized finish_reason."""
        return map_finish_reason(raw_reason, self.STOP_REASON_MAP)


# Auto-register on import
from . import register_transport

register_transport("chat_completions", OpenAITransport)
