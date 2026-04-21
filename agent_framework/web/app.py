"""Web UI for Agent Framework using FastAPI"""
import asyncio
from typing import Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import uuid

app = FastAPI(title="Agent Framework Web UI")

# Store active connections
connections: dict[str, WebSocket] = {}
agents: dict[str, dict] = {}


@app.get("/", response_class=HTMLResponse)
async def root():
    """Serve the web UI"""
    html_path = Path(__file__).parent / "ui" / "index.html"
    if html_path.exists():
        return HTMLResponse(content=html_path.read_text(encoding="utf-8"), status_code=200)
    return HTMLResponse(content="<h1>Agent Framework Web UI</h1><p>UI not found</p>", status_code=200)


@app.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    """WebSocket endpoint for real-time agent communication"""
    await websocket.accept()
    connections[client_id] = websocket

    # Auto-create default agent for this client (multiple agents per client)
    from ..core import Agent, AgentConfig
    mode = "simple"
    config = AgentConfig(name="my-agent", mode=mode)
    agent = Agent(name="my-agent", config=config)
    agents[client_id] = {
        "my-agent": {"agent": agent, "name": "my-agent", "mode": mode},
        "_current": "my-agent"
    }
    await websocket.send_json({"type": "agent_created", "name": "my-agent", "mode": mode})

    try:
        while True:
            data = await websocket.receive_json()
            await handle_agent_message(client_id, data, websocket)
    except WebSocketDisconnect:
        del connections[client_id]


async def handle_agent_message(client_id: str, data: dict, websocket: WebSocket):
    """Handle incoming agent messages"""
    action = data.get("action")

    if action == "create_agent":
        from ..core import Agent, AgentConfig
        name = data.get("name", f"agent-{client_id}")
        mode = data.get("mode", "simple")
        if name in agents.get(client_id, {}):
            await websocket.send_json({"type": "error", "message": f"Agent '{name}' already exists"})
            return
        config = AgentConfig(name=name, mode=mode)
        agent = Agent(name=name, config=config)
        if client_id not in agents:
            agents[client_id] = {"_current": name}
        agents[client_id][name] = {"agent": agent, "name": name, "mode": mode}
        agents[client_id]["_current"] = name
        await websocket.send_json({"type": "agent_created", "name": name, "mode": mode})

    elif action == "switch_agent":
        name = data.get("name")
        if client_id not in agents or name not in agents[client_id]:
            await websocket.send_json({"type": "error", "message": f"Agent '{name}' not found"})
            return
        agents[client_id]["_current"] = name
        current_mode = agents[client_id][name]["mode"]
        await websocket.send_json({"type": "agent_switched", "name": name, "mode": current_mode})

    elif action == "delete_agent":
        name = data.get("name")
        if client_id not in agents or name not in agents[client_id]:
            await websocket.send_json({"type": "error", "message": f"Agent '{name}' not found"})
            return
        if name == "my-agent":
            await websocket.send_json({"type": "error", "message": "Cannot delete default my-agent"})
            return
        del agents[client_id][name]
        if agents[client_id]["_current"] == name:
            agents[client_id]["_current"] = "my-agent"
        await websocket.send_json({"type": "agent_deleted", "name": name})
        await websocket.send_json({
            "type": "agent_switched",
            "name": agents[client_id]["_current"],
            "mode": agents[client_id][agents[client_id]["_current"]]["mode"]
        })

    elif action == "think":
        if client_id not in agents or agents[client_id]["_current"] not in agents[client_id]:
            await websocket.send_json({"type": "error", "message": "Agent not found"})
            return
        current_name = agents[client_id]["_current"]
        prompt = data.get("prompt", "")
        has_image = data.get("has_image", False)
        image_data = data.get("image_data")

        agent = agents[client_id][current_name]["agent"]

        # If image is provided, add to agent messages for context, then handle separately
        if has_image and image_data:
            try:
                # Save image info to agent messages for context persistence
                image_msg = {
                    "role": "user",
                    "content": prompt or "描述这张图片",
                    "image_data": image_data  # Store base64 for context
                }
                agent.messages.append(image_msg)
                result = await handle_image_understand(image_data, prompt or "描述这张图片")
                # Add response to agent context
                agent.messages.append({"role": "assistant", "content": result})
                await websocket.send_json({"type": "image_response", "content": result})
            except Exception as e:
                await websocket.send_json({"type": "error", "message": str(e)})
        else:
            try:
                result = await agent.think(prompt)
                await websocket.send_json({"type": "response", "content": result})
            except Exception as e:
                await websocket.send_json({"type": "error", "message": str(e)})

    elif action == "image_understand":
        # Handle image understanding via MiniMax API
        image_data = data.get("image_data", "")
        prompt = data.get("prompt", "描述这张图片")
        try:
            result = await handle_image_understand(image_data, prompt)
            await websocket.send_json({"type": "image_response", "content": result})
        except Exception as e:
            await websocket.send_json({"type": "error", "message": str(e)})

    elif action == "web_search":
        # Handle web search via MiniMax API
        query = data.get("query", "")
        num_results = data.get("num_results", 5)
        try:
            result = await handle_web_search(query, num_results)
            await websocket.send_json({"type": "search_response", "content": result})
        except Exception as e:
            await websocket.send_json({"type": "error", "message": str(e)})

    elif action == "list_agents":
        if client_id in agents:
            agent_list = [
                {"name": name, "mode": info["mode"]}
                for name, info in agents[client_id].items()
                if not name.startswith("_")
            ]
        else:
            agent_list = []
        current = agents[client_id]["_current"] if client_id in agents else None
        await websocket.send_json({"type": "agent_list", "agents": agent_list, "current": current})

    elif action == "change_mode":
        if client_id not in agents or agents[client_id]["_current"] not in agents[client_id]:
            await websocket.send_json({"type": "error", "message": "Agent not found"})
            return
        current_name = agents[client_id]["_current"]
        new_mode = data.get("mode", "simple")
        agents[client_id][current_name]["agent"].config.mode = new_mode
        agents[client_id][current_name]["mode"] = new_mode
        await websocket.send_json({"type": "mode_changed", "mode": new_mode})


async def handle_image_understand(image_data: str, prompt: str) -> str:
    """调用MiniMax图片理解API - 直接调用API不经过MCP"""
    import os
    import base64
    import httpx
    from dotenv import load_dotenv
    load_dotenv(override=True)

    minimax_key = os.getenv("MINIMAX_API_KEY", "")
    auth_token = os.getenv("ANTHROPIC_AUTH_TOKEN", "")

    if minimax_key and minimax_key not in ("ANTHROPIC_AUTH_TOKEN", "your_key_here", ""):
        api_key = minimax_key
    else:
        api_key = auth_token

    base_url = os.getenv("MINIMAX_API_HOST") or "https://api.minimaxi.com"

    if not api_key:
        return "错误: 未设置API密钥"

    # 处理图片数据 - 转换为base64 URL
    if image_data.startswith("data:"):
        # data:image/png;base64,iVBORw0KGgo...
        header, b64_data = image_data.split(",", 1)
        image_base64 = b64_data
    else:
        # 已经是base64字符串
        image_base64 = image_data

    # 确保是有效的base64
    try:
        image_bytes = base64.b64decode(image_base64)
    except Exception as e:
        return f"错误: 无效的图片base64数据 ({str(e)})"

    # 构建image_url (data URI)
    image_url = f"data:image/png;base64,{image_base64}"

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{base_url}/v1/coding_plan/vlm",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "prompt": prompt if prompt else "描述这张图片",
                    "image_url": image_url
                },
                timeout=60.0
            )

            if response.status_code != 200:
                return f"错误: API返回 {response.status_code} - {response.text[:200]}"

            result = response.json()
            if "content" in result:
                return result["content"]
            return f"错误: 响应格式异常 - {str(result)[:200]}"

    except httpx.TimeoutException:
        return "错误: API请求超时"
    except Exception as e:
        return f"错误: {str(e)}"


async def handle_web_search(query: str, num_results: int = 5) -> str:
    """调用MiniMax网络搜索API"""
    import os
    import httpx
    from dotenv import load_dotenv
    load_dotenv(override=True)

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


@app.get("/api/status")
async def status():
    """API endpoint for framework status"""
    return {
        "agents": len(agents),
        "connections": len(connections),
        "version": "0.1.0"
    }


@app.get("/api/agents")
async def list_agents():
    """List all active agents"""
    return [{"id": cid, "name": info["name"]} for cid, info in agents.items()]


def mount_static_files():
    """Mount static files if directory exists"""
    ui_path = Path(__file__).parent / "ui"
    if ui_path.exists():
        app.mount("/static", StaticFiles(directory=str(ui_path), encoding="utf-8"), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)