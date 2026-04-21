"""Tool system for Agent Framework"""
from typing import Any, Callable, Dict, Optional
from dataclasses import dataclass
import inspect
import httpx
import os
from dotenv import load_dotenv
load_dotenv(override=True)


@dataclass
class Tool:
    name: str
    description: str
    input_schema: Dict[str, Any]
    handler: Callable
    enabled: bool = True

    def __call__(self, **kwargs) -> Any:
        return self.handler(**kwargs)


def tool(name: str = None, description: str = "", input_schema: Optional[Dict] = None):
    """Decorator to define a tool"""
    def decorator(func: Callable) -> Tool:
        tool_name = name or func.__name__
        schema = input_schema or _generate_schema(func)
        return Tool(
            name=tool_name,
            description=description or func.__doc__ or "",
            input_schema=schema,
            handler=func
        )
    return decorator


def _generate_schema(func: Callable) -> Dict[str, Any]:
    """Generate input schema from function signature"""
    sig = inspect.signature(func)
    properties = {}
    required = []
    for param_name, param in sig.parameters.items():
        if param_name in ("self", "cls"):
            continue
        param_type = "string"
        if param.annotation in (int, "int"):
            param_type = "integer"
        elif param.annotation in (float, "float"):
            param_type = "number"
        elif param.annotation in (bool, "bool"):
            param_type = "boolean"
        elif param.annotation in (list, "list"):
            param_type = "array"
        elif param.annotation in (dict, "dict", "object"):
            param_type = "object"
        properties[param_name] = {"type": param_type}
        if param.default == inspect.Parameter.empty:
            required.append(param_name)
    return {"type": "object", "properties": properties, "required": required}


class ToolRegistry:
    """Registry for managing tools"""
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._tools = {}
        return cls._instance

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def list_tools(self) -> list[Tool]:
        return list(self._tools.values())

    def unregister(self, name: str) -> bool:
        if name in self._tools:
            del self._tools[name]
            return True
        return False

    def clear(self) -> None:
        self._tools.clear()


async def web_search(query: str, num_results: int = 5) -> str:
    """MiniMax web search - 搜索互联网获取相关信息

    Args:
        query: 搜索关键词
        num_results: 返回结果数量，默认5条
    """
    minimax_key = os.getenv("MINIMAX_API_KEY", "")
    auth_token = os.getenv("ANTHROPIC_AUTH_TOKEN", "")

    if minimax_key and minimax_key not in ("ANTHROPIC_AUTH_TOKEN", "your_key_here", ""):
        api_key = minimax_key
    else:
        api_key = auth_token

    base_url = os.getenv("MINIMAX_API_HOST") or "https://api.minimaxi.com"

    if not api_key:
        return "错误: 未设置API密钥"

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{base_url}/v1/coding_plan/search",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                },
                json={"q": query},
                timeout=30.0
            )

            if response.status_code != 200:
                return f"错误: API返回 {response.status_code} - {response.text[:200]}"

            result = response.json()
            return result

    except httpx.TimeoutException:
        return "错误: 搜索请求超时"
    except Exception as e:
        return f"错误: {str(e)}"


# 注册web_search工具到全局注册表
_registry = ToolRegistry()
_registry.register(Tool(
    name="web_search",
    description="MiniMax web search - 搜索互联网获取相关信息",
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "搜索关键词"},
            "num_results": {"type": "integer", "description": "返回结果数量", "default": 5}
        },
        "required": ["query"]
    },
    handler=web_search
))