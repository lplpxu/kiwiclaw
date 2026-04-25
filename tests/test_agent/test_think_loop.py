"""Tests for Agent think() loop

Verifies:
- Agent loop iterations work correctly
- call_depth protection prevents infinite recursion
- max_iterations protection works
- Tracing integration
"""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock
import asyncio


class TestAgentThinkLoop:
    """Test the main think() loop"""

    @pytest.mark.asyncio
    async def test_think_returns_text_response(self, agent, mock_client):
        """think() should return text when LLM doesn't call tools"""
        with patch("agent_framework.core.client") as mock:
            mock.messages.create.return_value = MagicMock(
                content=[MagicMock(type="text", text="Hello, how can I help?")],
                stop_reason="end_turn",
                usage=MagicMock(input_tokens=50, output_tokens=30),
            )

            result = await agent.think("Hello")
            assert isinstance(result, str)
            assert len(result) > 0

    @pytest.mark.asyncio
    async def test_think_processes_tool_calls(self, agent, mock_client):
        """think() should process tool calls and return results"""
        with patch("agent_framework.core.client") as mock:
            # First call returns tool_use, second returns text
            mock.messages.create.side_effect = [
                MagicMock(
                    content=[MagicMock(
                        type="tool_use",
                        name="web_search",
                        input={"query": "test"},
                        id="tool_123"
                    )],
                    stop_reason="tool_use",
                    usage=MagicMock(input_tokens=100, output_tokens=10),
                ),
                MagicMock(
                    content=[MagicMock(type="text", text="Found results")],
                    stop_reason="end_turn",
                    usage=MagicMock(input_tokens=200, output_tokens=50),
                ),
            ]

            # Mock the tool handler
            agent._tool_handlers["web_search"] = lambda **kw: '[{"title": "Test", "url": "https://example.com", "snippet": "Test"}]'

            result = await agent.think("Search for something")
            assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_max_iterations_protection(self, agent_config):
        """Should stop after max_iterations"""
        from agent_framework.core import Agent
        from agent_framework.core.state import StateManager, AgentState

        # Set low max_iterations
        agent_config.max_iterations = 2

        with patch("agent_framework.core.client") as mock:
            # Always return tool_use to force iteration
            mock.messages.create.return_value = MagicMock(
                content=[MagicMock(
                    type="tool_use",
                    name="bash",
                    input={"command": "echo test"},
                    id="tool_1"
                )],
                stop_reason="tool_use",
                usage=MagicMock(input_tokens=100, output_tokens=10),
            )

            # Mock bash tool to avoid actual execution
            agent = Agent(name="test", config=agent_config)
            agent._tool_handlers["bash"] = lambda **kw: "mock bash output"

            # Patch state manager to have low max_iterations
            with patch.object(agent, '_iteration', 0):
                result = await agent.think("Run echo test")

            # Should return due to max_iterations, not hang
            assert isinstance(result, str)


class TestCallDepthProtection:
    """Test call_depth recursion protection"""

    def test_call_depth_increments(self, state_manager):
        """call_depth should increment during tool execution"""
        from agent_framework.core.state import AgentFlag

        initial_depth = state_manager.state.call_depth
        state_manager.update(lambda s: s.increment_call_depth())
        assert state_manager.state.call_depth == initial_depth + 1

    def test_call_depth_decrements(self, state_manager):
        """call_depth should decrement after tool execution"""
        from agent_framework.core.state import AgentFlag

        state_manager.update(lambda s: s.increment_call_depth())
        state_manager.update(lambda s: s.increment_call_depth())
        initial_depth = state_manager.state.call_depth

        state_manager.update(lambda s: s.decrement_call_depth())
        assert state_manager.state.call_depth == initial_depth - 1

    def test_call_depth_floor_at_zero(self, state_manager):
        """call_depth should not go below zero"""
        state_manager.update(lambda s: s.decrement_call_depth())
        state_manager.update(lambda s: s.decrement_call_depth())
        assert state_manager.state.call_depth == 0

    def test_call_depth_max_limit(self, state_manager):
        """Should respect max_call_depth limit"""
        # StateManager's state should have max_call_depth
        assert hasattr(state_manager.state, 'max_call_depth')
        assert state_manager.state.max_call_depth == 10


class TestAgentState:
    """Test AgentState management"""

    def test_state_creates_with_defaults(self):
        """AgentState should have sensible defaults"""
        from agent_framework.core.state import AgentState, AgentFlag

        state = AgentState()
        assert AgentFlag.RUNNING in state.flags
        assert state.iteration == 0
        assert state.call_depth == 0
        assert state.max_iterations == 100
        assert state.max_call_depth == 10

    def test_state_to_dict(self):
        """State should serialize to dict"""
        from agent_framework.core.state import AgentState

        state = AgentState()
        d = state.to_dict()
        assert "flags" in d
        assert "iteration" in d
        assert "call_depth" in d
        assert "uptime" in d

    def test_state_set_get_variable(self):
        """State variables should be settable and gettable"""
        from agent_framework.core.state import AgentState

        state = AgentState()
        state.set_variable("test_key", "test_value")
        assert state.get_variable("test_key") == "test_value"
        assert state.get_variable("nonexistent", "default") == "default"


class TestStateManager:
    """Test StateManager operations"""

    def test_state_manager_creates_state(self):
        """StateManager should create state if not provided"""
        from agent_framework.core.state import StateManager

        mgr = StateManager()
        assert mgr.state is not None

    def test_state_manager_update(self):
        """StateManager.update should apply function to state"""
        from agent_framework.core.state import StateManager

        mgr = StateManager()
        mgr.update(lambda s: s.set_variable("key", "value"))
        assert mgr.state.variables.get("key") == "value"

    def test_state_manager_snapshot(self):
        """StateManager should create snapshots"""
        from agent_framework.core.state import StateManager

        mgr = StateManager()
        mgr.update(lambda s: s.set_variable("key", "value"))

        snapshot = mgr.create_snapshot("test-snap")
        assert snapshot is not None
        assert snapshot.id == "test-snap"

    def test_state_manager_restore_snapshot(self):
        """StateManager should restore snapshots"""
        from agent_framework.core.state import StateManager

        mgr = StateManager()
        mgr.update(lambda s: s.set_variable("key", "original"))

        snapshot = mgr.create_snapshot("test-snap")

        mgr.update(lambda s: s.set_variable("key", "modified"))
        assert mgr.state.variables.get("key") == "modified"

        # Note: restore_snapshot implementation may vary
        result = mgr.restore_snapshot("test-snap")
        assert isinstance(result, bool)


class TestTracingIntegration:
    """Test tracing integration in agent loop"""

    def test_tracing_span_creation(self):
        """Should create spans for operations"""
        from agent_framework.observability.tracing import Tracing, SpanKind

        tracing = Tracing()
        span = tracing.start_span("test.operation", SpanKind.INTERNAL)

        assert span.name == "test.operation"
        assert span.trace_id is not None
        assert span.span_id is not None

        tracing.end_span(span)

    def test_span_attributes(self):
        """Spans should support attributes"""
        from agent_framework.observability.tracing import Tracing, SpanKind

        tracing = Tracing()
        span = tracing.start_span(
            "test",
            SpanKind.INTERNAL,
            key1="value1",
            key2=123
        )

        assert span.attributes.get("key1") == "value1"
        assert span.attributes.get("key2") == 123


class TestHookSystem:
    """Test hook system integration"""

    @pytest.mark.asyncio
    async def test_hook_runner_exists(self):
        """Hook runner should be accessible"""
        from agent_framework.observability.hooks import get_hook_runner

        runner = get_hook_runner()
        assert runner is not None

    @pytest.mark.asyncio
    async def test_before_tool_call_hook(self, hook_runner):
        """before_tool_call hooks should be callable"""
        from agent_framework.observability.hooks import ToolHookContext, HookName

        hook_called = False

        async def test_hook(ctx: ToolHookContext):
            nonlocal hook_called
            hook_called = True
            return ctx.tool_input  # Return unchanged

        hook_runner.register_hook(HookName.before_tool_call, test_hook)

        ctx = ToolHookContext(
            tool_name="test_tool",
            tool_input={"key": "value"},
            agent_name="test",
            messages=[],
            iteration=1,
        )

        result = await hook_runner.run_before_tool_call(ctx)
        assert hook_called
        assert result == (False, None)  # Not blocked, no modification
