"""API Server for Agent Framework

Provides REST API for agent interaction.
[PHASE6] Agent Harness - APIHarness
"""

import asyncio
import json
from typing import Optional, Dict, Any, Callable
from dataclasses import dataclass, field
from enum import Enum
import logging

logger = logging.getLogger(__name__)

# Debug print helper
def _debug(msg: str):
    print(f"[PHASE6] [APIHarness] {msg}")


class APIRoutes(Enum):
    """Available API routes"""
    HEALTH = "/health"
    AGENT_PROMPT = "/api/v1/agent/prompt"
    AGENT_STREAM = "/api/v1/agent/stream"
    AGENT_SESSIONS = "/api/v1/agent/sessions"
    AGENT_SESSION = "/api/v1/agent/sessions/{session_id}"
    TOOLS_LIST = "/api/v1/tools"
    TOOL_EXECUTE = "/api/v1/tools/execute"
    CHANNELS_LIST = "/api/v1/channels"
    CHANNEL_SEND = "/api/v1/channels/{channel}/send"
    ACP_PROMPT = "/api/v1/acp/prompt"
    ACP_SESSIONS = "/api/v1/acp/sessions"
    ACP_SESSION = "/api/v1/acp/sessions/{session_id}"


@dataclass
class APIConfig:
    """Configuration for API server"""
    host: str = "0.0.0.0"
    port: int = 8080
    workers: int = 1
    ssl_cert: str = ""
    ssl_key: str = ""
    cors_enabled: bool = True
    cors_origins: list = field(default_factory=lambda: ["*"])
    rate_limit: int = 100  # Requests per minute
    api_key: str = ""  # Optional API key authentication
    debug: bool = False


class APIResponse:
    """Standard API response"""

    def __init__(
        self,
        success: bool,
        data: Any = None,
        error: str = None,
        status_code: int = 200
    ):
        self.success = success
        self.data = data
        self.error = error
        self.status_code = status_code

    def to_dict(self) -> dict:
        result = {"success": self.success}
        if self.data is not None:
            result["data"] = self.data
        if self.error:
            result["error"] = self.error
        return result

    @classmethod
    def ok(cls, data: Any = None) -> "APIResponse":
        return cls(success=True, data=data)

    @classmethod
    def error(cls, message: str, status_code: int = 400) -> "APIResponse":
        return cls(success=False, error=message, status_code=status_code)


class Request:
    """Represents an API request"""

    def __init__(self, method: str, path: str, headers: Dict[str, str] = None,
                 body: Any = None, query_params: Dict[str, str] = None):
        self.method = method
        self.path = path
        self.headers = headers or {}
        self.body = body
        self.query_params = query_params or {}


class RouteHandler:
    """Handler for a specific route"""

    def __init__(self, path: str, method: str, handler: Callable):
        self.path = path
        self.method = method
        self.handler = handler


class APIServer:
    """HTTP API Server for Agent Framework

    Provides REST API endpoints for:
    - Agent prompting
    - Session management
    - Tool execution
    - Channel management
    - ACP integration
    """

    def __init__(self, config: APIConfig = None, agent=None):
        self.config = config or APIConfig()
        self.agent = agent  # AIAgent instance

        self._routes: Dict[str, RouteHandler] = {}
        self._running = False
        self._server = None

        # Register default routes
        self._register_default_routes()

    def _register_default_routes(self) -> None:
        """Register default API routes"""

        # Health check
        self.add_route("GET", "/health", self._handle_health)

        # Agent routes
        self.add_route("POST", "/api/v1/agent/prompt", self._handle_agent_prompt)
        self.add_route("GET", "/api/v1/agent/sessions", self._handle_list_sessions)
        self.add_route("POST", "/api/v1/agent/sessions", self._handle_create_session)
        self.add_route("GET", "/api/v1/agent/sessions/{id}", self._handle_get_session)
        self.add_route("DELETE", "/api/v1/agent/sessions/{id}", self._handle_delete_session)

        # Tools routes
        self.add_route("GET", "/api/v1/tools", self._handle_list_tools)
        self.add_route("POST", "/api/v1/tools/execute", self._handle_execute_tool)

        # ACP routes
        self.add_route("POST", "/api/v1/acp/prompt", self._handle_acp_prompt)
        self.add_route("GET", "/api/v1/acp/sessions", self._handle_acp_list_sessions)
        self.add_route("POST", "/api/v1/acp/sessions", self._handle_acp_create_session)
        self.add_route("GET", "/api/v1/acp/sessions/{id}", self._handle_acp_get_session)
        self.add_route("DELETE", "/api/v1/acp/sessions/{id}", self._handle_acp_delete_session)

    def add_route(self, method: str, path: str, handler: Callable) -> None:
        """Add a route handler

        Args:
            method: HTTP method (GET, POST, etc.)
            path: Route path (can include path parameters like {id})
            handler: Handler function
        """
        key = f"{method}:{path}"
        self._routes[key] = RouteHandler(path, method, handler)

    def _match_route(self, method: str, path: str) -> tuple:
        """Match a request to a route

        Returns:
            Tuple of (handler, path_params) or (None, None)
        """
        key = f"{method}:{path}"
        if key in self._routes:
            return self._routes[key].handler, {}

        # Try to match with path parameters
        for route_key, route in self._routes.items():
            if not route_key.startswith(f"{method}:"):
                continue

            route_path = route_key[len(f"{method}:"):]
            params = self._match_path(route_path, path)

            if params is not None:
                return route.handler, params

        return None, None

    def _match_path(self, route_path: str, request_path: str) -> Optional[Dict[str, str]]:
        """Match a route path to a request path

        Args:
            route_path: Route definition (e.g., /api/v1/agent/sessions/{id})
            request_path: Actual request path

        Returns:
            Dictionary of path parameters or None
        """
        route_parts = route_path.strip("/").split("/")
        request_parts = request_path.strip("/").split("/")

        if len(route_parts) != len(request_parts):
            return None

        params = {}
        for route_part, request_part in zip(route_parts, request_parts):
            if route_part.startswith("{") and route_part.endswith("}"):
                param_name = route_part[1:-1]
                params[param_name] = request_part
            elif route_part != request_part:
                return None

        return params

    async def _handle_health(self, request: Request) -> APIResponse:
        """Health check endpoint"""
        return APIResponse.ok({"status": "healthy", "version": "1.0.0"})

    async def _handle_agent_prompt(self, request: Request) -> APIResponse:
        """Handle agent prompt request"""
        if not self.agent:
            return APIResponse.error("Agent not configured", 500)

        try:
            data = request.body or {}
            prompt = data.get("prompt", "")

            if not prompt:
                return APIResponse.error("prompt is required")

            result = await self.agent.think(prompt)
            return APIResponse.ok({"response": result})

        except Exception as e:
            logger.error(f"Agent prompt error: {e}")
            return APIResponse.error(str(e), 500)

    async def _handle_list_sessions(self, request: Request) -> APIResponse:
        """List agent sessions"""
        return APIResponse.ok({"sessions": []})

    async def _handle_create_session(self, request: Request) -> APIResponse:
        """Create a new session"""
        return APIResponse.ok({"session_id": "new-session"})

    async def _handle_get_session(self, request: Request) -> APIResponse:
        """Get session by ID"""
        return APIResponse.error("Not implemented", 501)

    async def _handle_delete_session(self, request: Request) -> APIResponse:
        """Delete a session"""
        return APIResponse.error("Not implemented", 501)

    async def _handle_list_tools(self, request: Request) -> APIResponse:
        """List available tools"""
        if not self.agent:
            return APIResponse.error("Agent not configured", 500)

        return APIResponse.ok({"tools": self.agent._tools})

    async def _handle_execute_tool(self, request: Request) -> APIResponse:
        """Execute a tool directly"""
        if not self.agent:
            return APIResponse.error("Agent not configured", 500)

        try:
            data = request.body or {}
            tool_name = data.get("tool")
            tool_input = data.get("input", {})

            if not tool_name:
                return APIResponse.error("tool is required")

            handler = self.agent._tool_handlers.get(tool_name)
            if not handler:
                return APIResponse.error(f"Unknown tool: {tool_name}")

            result = handler(**tool_input)
            return APIResponse.ok({"result": result})

        except Exception as e:
            logger.error(f"Tool execution error: {e}")
            return APIResponse.error(str(e), 500)

    # ACP handlers
    async def _handle_acp_prompt(self, request: Request) -> APIResponse:
        """Handle ACP prompt request"""
        return APIResponse.error("ACP not implemented", 501)

    async def _handle_acp_list_sessions(self, request: Request) -> APIResponse:
        """List ACP sessions"""
        return APIResponse.error("ACP not implemented", 501)

    async def _handle_acp_create_session(self, request: Request) -> APIResponse:
        """Create ACP session"""
        return APIResponse.error("ACP not implemented", 501)

    async def _handle_acp_get_session(self, request: Request) -> APIResponse:
        """Get ACP session"""
        return APIResponse.error("ACP not implemented", 501)

    async def _handle_acp_delete_session(self, request: Request) -> APIResponse:
        """Delete ACP session"""
        return APIResponse.error("ACP not implemented", 501)

    async def handle_request(self, method: str, path: str,
                           headers: Dict[str, str] = None,
                           body: Any = None,
                           query_params: Dict[str, str] = None) -> tuple:
        """Handle an incoming request

        Returns:
            Tuple of (status_code, response_body)
        """
        # Find handler
        handler, path_params = self._match_route(method, path)

        if not handler:
            response = APIResponse.error("Not found", 404)
            return response.status_code, response.to_dict()

        # Create request object
        request = Request(
            method=method,
            path=path,
            headers=headers,
            body=body,
            query_params=query_params
        )

        # Inject path params into body
        if path_params and request.body:
            request.body["_path_params"] = path_params

        try:
            # Call handler
            response = await handler(request)
            return response.status_code, response.to_dict()

        except Exception as e:
            logger.error(f"Request handling error: {e}")
            response = APIResponse.error(str(e), 500)
            return response.status_code, response.to_dict()

    async def start(self) -> None:
        """Start the API server"""
        if self._running:
            return

        self._running = True
        logger.info(f"Starting API server on {self.config.host}:{self.config.port}")

        # Note: This is a simplified implementation
        # A full implementation would use aiohttp or similar
        # For now, this serves as a specification

    async def stop(self) -> None:
        """Stop the API server"""
        if not self._running:
            return

        self._running = False
        logger.info("API server stopped")


class SimpleAPIServer:
    """Simplified API server using aiohttp

    This is a more complete implementation for production use.
    """

    def __init__(self, config: APIConfig = None, agent=None):
        self.config = config or APIConfig()
        self.agent = agent
        self.app = None
        self._runner = None

    async def _setup_routes(self) -> None:
        """Setup aiohttp routes"""
        from aiohttp import web

        self.app = web.Application()

        # CORS middleware
        if self.config.cors_enabled:
            self.app.middlewares.append(self._cors_middleware)

        # Add routes
        self.app.router.add_get("/health", self._handle_health)
        self.app.router.add_post("/api/v1/agent/prompt", self._handle_agent_prompt)
        self.app.router.add_get("/api/v1/tools", self._handle_list_tools)
        self.app.router.add_post("/api/v1/tools/execute", self._handle_execute_tool)

    async def _cors_middleware(self, app, handler):
        """CORS middleware"""
        from aiohttp import web

        async def middleware(request):
            if request.method == "OPTIONS":
                response = web.Response()
            else:
                response = await handler(request)

            origin = request.headers.get("Origin", "*")
            if origin in self.config.cors_origins or "*" in self.config.cors_origins:
                response.headers["Access-Control-Allow-Origin"] = origin
                response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
                response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"

            return response

        return middleware

    async def _handle_health(self, request):
        """Health check"""
        from aiohttp import web
        return web.json_response({"status": "healthy", "version": "1.0.0"})

    async def _handle_agent_prompt(self, request):
        """Handle agent prompt"""
        from aiohttp import web

        if not self.agent:
            return web.json_response({"error": "Agent not configured"}, status=500)

        try:
            data = await request.json()
            prompt = data.get("prompt", "")

            if not prompt:
                return web.json_response({"error": "prompt is required"}, status=400)

            result = await self.agent.think(prompt)
            return web.json_response({"response": result})

        except Exception as e:
            logger.error(f"Agent prompt error: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def _handle_list_tools(self, request):
        """List tools"""
        from aiohttp import web

        if not self.agent:
            return web.json_response({"error": "Agent not configured"}, status=500)

        return web.json_response({"tools": self.agent._tools})

    async def _handle_execute_tool(self, request):
        """Execute tool"""
        from aiohttp import web

        if not self.agent:
            return web.json_response({"error": "Agent not configured"}, status=500)

        try:
            data = await request.json()
            tool_name = data.get("tool")
            tool_input = data.get("input", {})

            if not tool_name:
                return web.json_response({"error": "tool is required"}, status=400)

            handler = self.agent._tool_handlers.get(tool_name)
            if not handler:
                return web.json_response({"error": f"Unknown tool: {tool_name}"}, status=404)

            result = handler(**tool_input)
            return web.json_response({"result": str(result)})

        except Exception as e:
            logger.error(f"Tool execution error: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def start(self) -> None:
        """Start the server"""
        from aiohttp import web

        await self._setup_routes()

        self._runner = web.AppRunner(self.app)
        await self._runner.setup()

        site = web.TCPSite(self._runner, self.config.host, self.config.port)
        await site.start()

        logger.info(f"API server started on {self.config.host}:{self.config.port}")

    async def stop(self) -> None:
        """Stop the server"""
        if self._runner:
            await self._runner.cleanup()
            self._runner = None
        logger.info("API server stopped")
