"""Shared pytest fixtures for agent framework tests"""

import pytest
import sys
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add agent_framework to path
agent_framework_path = Path(__file__).parent.parent / "agent_framework"
sys.path.insert(0, str(agent_framework_path))


@pytest.fixture
def mock_api_key(monkeypatch):
    """Mock API key for testing without real API calls"""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-for-testing")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "test-key-for-testing")
    return "test-key-for-testing"


@pytest.fixture
def agent_config():
    """Create a test agent configuration"""
    from agent_framework.config.settings import AgentConfig

    return AgentConfig(
        name="test-agent",
        model="claude-sonnet-4-20250514",
        mode="simple",
        permission_mode="danger_full_access",
    )


@pytest.fixture
def mock_client():
    """Create a mock Anthropic client"""
    mock = MagicMock()
    mock.messages.create.return_value = MagicMock(
        content=[MagicMock(type="text", text="Test response")],
        stop_reason="end_turn",
        usage=MagicMock(input_tokens=100, output_tokens=50),
    )
    return mock


@pytest.fixture
def agent(agent_config, mock_api_key):
    """Create an Agent instance for testing"""
    from agent_framework.core import Agent

    # Mock the client to avoid real API calls
    with patch("agent_framework.core.client") as mock_client:
        mock_client.messages.create.return_value = MagicMock(
            content=[MagicMock(type="text", text="Test response")],
            stop_reason="end_turn",
            usage=MagicMock(input_tokens=100, output_tokens=50),
        )
        agent = Agent(name="test", config=agent_config)
        yield agent


@pytest.fixture
def tool_tracker():
    """Track tool calls during agent execution"""
    class ToolTracker:
        def __init__(self):
            self.calls = []
            self.original_handlers = {}

        def track(self, agent, tool_name, handler):
            """Track calls to a specific tool"""
            self.original_handlers[tool_name] = agent._tool_handlers.get(tool_name)
            self.calls = []

            def tracked_handler(**kwargs):
                self.calls.append({"tool": tool_name, "kwargs": kwargs})
                if self.original_handlers.get(tool_name):
                    return self.original_handlers[tool_name](**kwargs)
                return f"Mock {tool_name}"

            agent._tool_handlers[tool_name] = tracked_handler

        def restore(self, agent):
            """Restore original handlers"""
            for tool_name, handler in self.original_handlers.items():
                if handler:
                    agent._tool_handlers[tool_name] = handler

        def get_calls(self, tool_name=None):
            """Get calls for a specific tool or all calls"""
            if tool_name:
                return [c for c in self.calls if c["tool"] == tool_name]
            return self.calls

    return ToolTracker()


@pytest.fixture
def state_manager():
    """Create a fresh state manager for testing"""
    from agent_framework.core.state import StateManager, AgentState

    return StateManager(initial_state=AgentState())


@pytest.fixture
def mock_tracing():
    """Create a mock tracing instance"""
    from unittest.mock import MagicMock

    mock = MagicMock()
    mock.start_span.return_value = MagicMock(
        set_attribute=MagicMock(),
        record_exception=MagicMock(),
        finish=MagicMock(),
    )
    return mock


@pytest.fixture
async def hook_runner():
    """Get the global hook runner"""
    from agent_framework.observability.hooks import get_hook_runner

    runner = get_hook_runner()
    runner.clear_all_hooks()
    return runner


@pytest.fixture
def sample_search_results():
    """Sample web search results for testing"""
    return [
        {
            "title": "长沙到北京航班查询",
            "url": "https://example.com/flights/changsha-beijing",
            "snippet": "提供长沙到北京航班时刻表和价格查询",
        },
        {
            "title": "北京首都国际机场",
            "url": "https://example.com/beijing-airport",
            "snippet": "北京首都国际机场航班信息",
        },
    ]


@pytest.fixture
def sample_fetch_content():
    """Sample web fetch content for testing"""
    return """
# 长沙黄花国际机场 - 北京首都国际机场

## 航班时刻表

| 航班号 | 出发时间 | 到达时间 | 机型 | 票价 |
|--------|----------|----------|------|------|
| CA1234 | 08:30 | 10:45 | B737 | ¥890 |
| MU5678 | 14:20 | 16:35 | A320 | ¥920 |
| CZ9876 | 19:45 | 22:00 | B757 | ¥950 |

## 相关城市天气
- 长沙: 多云转晴, 18-26°C
- 北京: 晴, 15-24°C
"""
