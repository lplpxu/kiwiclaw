"""Anthropic Messages API transport.

Provides format conversion and normalization for Anthropic's Messages API.
This transport owns format conversion and normalization — NOT client lifecycle.
"""

from typing import Any, Dict, List, Optional

from .base import ProviderTransport
from .types import NormalizedResponse, ToolCall, Usage, build_tool_call, map_finish_reason


class AnthropicTransport(ProviderTransport):
    """Transport for api_mode='anthropic_messages'.

    Converts OpenAI-format messages and tools to Anthropic's native format,
    then normalizes responses back to the shared NormalizedResponse type.
    """

    # Anthropic stop_reason -> OpenAI finish_reason mapping
    STOP_REASON_MAP = {
        "end_turn": "stop",
        "tool_use": "tool_calls",
        "max_tokens": "length",
        "stop_sequence": "stop",
        "refusal": "content_filter",
        "model_context_window_exceeded": "length",
    }

    @property
    def api_mode(self) -> str:
        return "anthropic_messages"

    def convert_messages(self, messages: List[Dict[str, Any]], **kwargs) -> tuple:
        """Convert OpenAI messages to Anthropic (system, messages) tuple.

        kwargs:
            base_url: Optional[str] — affects thinking signature handling.
        """
        system_messages = []
        converted_messages = []

        for msg in messages:
            role = msg.get("role")
            content = msg.get("content", "")

            if role == "system":
                system_messages.append({"role": "system", "content": content})
            elif role == "user":
                converted_messages.append({"role": "user", "content": content})
            elif role == "assistant":
                converted_messages.append({"role": "assistant", "content": content})
            elif role == "tool":
                converted_messages.append({
                    "role": "user",
                    "content": [
                        {"type": "tool_result", "tool_use_id": msg.get("tool_call_id"), "content": content}
                    ]
                })
            else:
                converted_messages.append({"role": role, "content": content})

        # Combine system messages into single system prompt
        system_prompt = None
        if system_messages:
            system_prompt = "\n\n".join(m["content"] for m in system_messages if m.get("content"))

        return system_prompt, converted_messages

    def convert_tools(self, tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Convert OpenAI tool schemas to Anthropic input_schema format."""
        anthropic_tools = []

        for tool in tools:
            name = tool.get("name", "")
            description = tool.get("description", "")
            parameters = tool.get("parameters", {})

            anthropic_tools.append({
                "name": name,
                "description": description,
                "input_schema": parameters,
            })

        return anthropic_tools

    def build_kwargs(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        **params,
    ) -> Dict[str, Any]:
        """Build Anthropic messages.create() kwargs.

        Calls convert_messages and convert_tools internally.

        params (all optional):
            max_tokens: int
            thinking_config: dict | None
            tool_choice: str | None
            system: str | None
        """
        system_prompt, converted_messages = self.convert_messages(messages, **params)

        # Use explicit system param if provided, otherwise use converted
        if params.get("system"):
            system = params["system"]
        elif system_prompt:
            system = system_prompt
        else:
            system = None

        kwargs: Dict[str, Any] = {
            "model": model,
            "messages": converted_messages,
        }

        if system:
            kwargs["system"] = system

        if tools:
            kwargs["tools"] = self.convert_tools(tools)

        # Max tokens - required for Anthropic
        max_tokens = params.get("max_tokens", 8192)
        kwargs["max_tokens"] = max_tokens

        # Optional reasoning config
        if params.get("thinking_config"):
            kwargs["thinking"] = params["thinking_config"]

        # Tool choice
        if params.get("tool_choice"):
            kwargs["tool_choice"] = {"type": "tool", "name": params["tool_choice"]}

        return kwargs

    def normalize_response(self, response: Any, **kwargs) -> NormalizedResponse:
        """Normalize Anthropic response to NormalizedResponse.

        kwargs:
            strip_tool_prefix: bool — strip 'mcp_mcp_' prefixes from tool names.
        """
        if response is None:
            return NormalizedResponse(
                content=None,
                tool_calls=None,
                finish_reason="stop",
                reasoning=None,
                usage=None,
                provider_data=None,
            )

        # Extract content
        content = None
        tool_calls: Optional[List[ToolCall]] = []
        reasoning = None

        for block in response.get("content", []):
            block_type = block.get("type")

            if block_type == "text":
                content = block.get("text", "")
            elif block_type == "thinking":
                reasoning = block.get("thinking", "")
            elif block_type == "tool_use":
                tool_name = block.get("name", "")
                tool_input = block.get("input", {})

                # Strip prefix if requested
                strip_prefix = kwargs.get("strip_tool_prefix", False)
                if strip_prefix and tool_name.startswith("mcp_mcp_"):
                    tool_name = tool_name[8:]

                tool_calls.append(build_tool_call(
                    id=block.get("id"),
                    name=tool_name,
                    arguments=tool_input,
                ))

        # Extract usage
        usage_data = response.get("usage", {})
        usage = Usage(
            prompt_tokens=usage_data.get("input_tokens", 0),
            completion_tokens=usage_data.get("output_tokens", 0),
            total_tokens=usage_data.get("input_tokens", 0) + usage_data.get("output_tokens", 0),
            cached_tokens=0,
        )

        # Extract finish reason
        raw_reason = response.get("stop_reason", "stop")
        finish_reason = self.map_finish_reason(raw_reason)

        # Provider data for protocol-aware code
        provider_data = {
            "reasoning_details": response.get("thinking", []),
            "raw_response": response,
        }

        return NormalizedResponse(
            content=content,
            tool_calls=tool_calls if tool_calls else None,
            finish_reason=finish_reason,
            reasoning=reasoning,
            usage=usage,
            provider_data=provider_data,
        )

    def validate_response(self, response: Any) -> bool:
        """Check Anthropic response structure is valid."""
        if response is None:
            return False
        content_blocks = response.get("content")
        if not isinstance(content_blocks, list):
            return False
        if not content_blocks:
            return False
        return True

    def extract_cache_stats(self, response: Any) -> Optional[Dict[str, int]]:
        """Extract Anthropic cache_read and cache_creation token counts."""
        if response is None:
            return None

        usage = response.get("usage", {})
        if not usage:
            return None

        cached = usage.get("cache_read_input_tokens", 0) or 0
        written = usage.get("cache_creation_input_tokens", 0) or 0

        if cached or written:
            return {"cached_tokens": cached, "creation_tokens": written}
        return None

    def map_finish_reason(self, raw_reason: str) -> str:
        """Map Anthropic stop_reason to OpenAI finish_reason."""
        return map_finish_reason(raw_reason, self.STOP_REASON_MAP)


# Auto-register on import
from . import register_transport

register_transport("anthropic_messages", AnthropicTransport)
