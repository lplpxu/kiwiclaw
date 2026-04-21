"""MiniMax tokenplan MCP服务器 - 图片理解与网络搜索"""
import asyncio
import json
import sys
from typing import Any, Dict, List
from dataclasses import dataclass
from pathlib import Path

MCP_VERSION = "0.1.0"


@dataclass
class MiniMaxTool:
    name: str
    description: str
    input_schema: Dict[str, Any]


class MiniMaxTokenplanMCPServer:
    """MiniMax tokenplan MCP服务器 - 支持图片理解和网络搜索"""

    def __init__(self):
        self.name = "minimax-tokenplan"
        self.tools = [
            MiniMaxTool(
                name="image_understand",
                description="理解图片内容，识别物体、场景、文字等",
                input_schema={
                    "type": "object",
                    "properties": {
                        "image_url": {"type": "string", "description": "图片URL或base64数据"},
                        "question": {"type": "string", "description": "关于图片的问题"}
                    },
                    "required": ["image_url"]
                }
            ),
            MiniMaxTool(
                name="web_search",
                description="搜索互联网获取相关信息",
                input_schema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "搜索关键词"},
                        "num_results": {"type": "integer", "description": "返回结果数量", "default": 5}
                    },
                    "required": ["query"]
                }
            ),
            MiniMaxTool(
                name="web_fetch",
                description="获取网页内容",
                input_schema={
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "网页URL"}
                    },
                    "required": ["url"]
                }
            )
        ]

    def get_manifest(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "version": MCP_VERSION,
            "tools": [
                {"name": t.name, "description": t.description, "input_schema": t.input_schema}
                for t in self.tools
            ]
        }

    async def handle_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        method = request.get("method", "")
        params = request.get("params", {})

        if method == "initialize":
            return {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": self.name, "version": MCP_VERSION}
            }

        elif method == "tools/list":
            return {"tools": [
                {"name": t.name, "description": t.description, "input_schema": t.input_schema}
                for t in self.tools
            ]}

        elif method == "tools/call":
            tool_name = params.get("name")
            arguments = params.get("arguments", {})

            if tool_name == "image_understand":
                result = await self._image_understand(arguments)
            elif tool_name == "web_search":
                result = await self._web_search(arguments)
            elif tool_name == "web_fetch":
                result = await self._web_fetch(arguments)
            else:
                result = {"error": f"Unknown tool: {tool_name}"}

            return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]}

        return {"error": f"Unknown method: {method}"}

    async def _image_understand(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """调用MiniMax图片理解API"""
        import os
        import httpx
        from dotenv import load_dotenv
        load_dotenv(override=True)

        # Use MINIMAX_API_KEY if set, otherwise fall back to ANTHROPIC_AUTH_TOKEN
        minimax_key = os.getenv("MINIMAX_API_KEY", "")
        auth_token = os.getenv("ANTHROPIC_AUTH_TOKEN", "")
        api_key = minimax_key if minimax_key and minimax_key != "ANTHROPIC_AUTH_TOKEN" else auth_token

        base_url = os.getenv("MINIMAX_API_HOST") or "https://api.minimaxi.com"
        image_url = args.get("image_url", "")
        question = args.get("question", "描述这张图片")

        if not api_key:
            return {"error": "MINIMAX_API_KEY not set", "image_url": image_url, "question": question}

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{base_url}/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": "MiniMax-M2.7",
                        "messages": [{
                            "role": "user",
                            "content": [
                                {"type": "text", "text": question},
                                {"type": "image_url", "image_url": {"url": image_url}}
                            ]
                        }],
                        "max_tokens": 1000
                    },
                    timeout=60.0
                )

                if response.status_code != 200:
                    return {"error": f"HTTP {response.status_code}", "detail": response.text[:200]}

                result = response.json()
                if "choices" in result and len(result["choices"]) > 0:
                    return {"content": result["choices"][0]["message"]["content"]}
                return result

        except Exception as e:
            return {"error": str(e), "image_url": image_url, "question": question}

    async def _web_search(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """网络搜索"""
        query = args.get("query", "")
        num_results = args.get("num_results", 5)

        try:
            import httpx
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    "https://www.google.com/search",
                    params={"q": query, "num": num_results},
                    timeout=10.0,
                    headers={"User-Agent": "Mozilla/5.0"}
                )
                return {"results": response.text[:2000], "query": query}
        except Exception as e:
            return {"error": str(e), "query": query}

    async def _web_fetch(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """获取网页内容"""
        url = args.get("url", "")

        try:
            import httpx
            async with httpx.AsyncClient() as client:
                response = await client.get(url, timeout=15.0)
                return {"content": response.text[:5000], "url": url}
        except Exception as e:
            return {"error": str(e), "url": url}


async def main():
    """stdio模式运行MCP服务器"""
    server = MiniMaxTokenplanMCPServer()

    # 处理初始化
    init_line = await asyncio.get_event_loop().run_in_executor(None, sys.stdin.readline)
    if init_line:
        try:
            init_request = json.loads(init_line)
            init_response = await server.handle_request(init_request)
            print(json.dumps(init_response), flush=True)
        except json.JSONDecodeError:
            pass

    # 处理工具调用
    while True:
        try:
            line = await asyncio.get_event_loop().run_in_executor(None, sys.stdin.readline)
            if not line:
                break

            request = json.loads(line)
            response = await server.handle_request(request)
            print(json.dumps(response), flush=True)
        except json.JSONDecodeError:
            continue
        except Exception:
            break


if __name__ == "__main__":
    asyncio.run(main())