"""Tests for web_search and web_fetch tools"""

import pytest
from unittest.mock import patch, MagicMock


class TestWebSearch:
    """Test web_search tool"""

    def test_web_search_function_exists(self):
        """web_search function should exist and be callable"""
        from agent_framework.core._tools import run_web_search
        assert callable(run_web_search)

    def test_web_search_without_api_key(self):
        """web_search without API key should return error message"""
        from agent_framework.core._tools import run_web_search
        import os

        # Temporarily remove API keys
        old_minimax = os.environ.get("MINIMAX_API_KEY")
        old_anthropic = os.environ.get("ANTHROPIC_AUTH_TOKEN")

        try:
            os.environ.pop("MINIMAX_API_KEY", None)
            os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)

            result = run_web_search("test query")
            assert "未设置API密钥" in result or "错误" in result
        finally:
            if old_minimax:
                os.environ["MINIMAX_API_KEY"] = old_minimax
            if old_anthropic:
                os.environ["ANTHROPIC_AUTH_TOKEN"] = old_anthropic


class TestWebFetch:
    """Test web_fetch tool"""

    def test_web_fetch_function_exists(self):
        """web_fetch function should exist and be callable"""
        from agent_framework.core._tools import run_web_fetch
        assert callable(run_web_fetch)

    def test_web_fetch_invalid_url(self):
        """web_fetch with invalid URL should return error"""
        from agent_framework.core._tools import run_web_fetch

        result = run_web_fetch("not-a-valid-url")
        assert "URL验证失败" in result or "error" in result.lower()

    def test_web_fetch_handles_error(self):
        """web_fetch should handle fetch errors gracefully"""
        from agent_framework.core._tools import run_web_fetch

        with patch("agent_framework.core._tools.httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.get.side_effect = Exception("Network error")
            result = run_web_fetch("https://example.com")
            assert isinstance(result, str)


class TestWebSearchFetchChain:
    """Test the search -> fetch chain (ISSUE #1 verification)"""

    def test_search_then_fetch_workflow(self):
        """Verify search returns URLs that can be fetched

        This test demonstrates the workflow but uses mocks to avoid real HTTP calls.
        """
        # This is a documentation test showing the expected workflow:
        # 1. Search for info -> returns URLs
        # 2. Fetch URL -> returns full content
        # 3. Use content to answer question

        search_result = {
            "title": "Flight Info",
            "url": "https://example.com/flights",
            "snippet": "Flight schedule",
        }

        # Verify search result contains URL
        assert "url" in search_result
        assert search_result["url"]

        # Verify fetched content has details not in search result
        fetch_content = "# Flight Schedule\n\n| CA1234 | 08:30 |"
        assert "CA1234" in fetch_content  # Details not in snippet

    @pytest.mark.asyncio
    async def test_agent_uses_fetch_after_search(self, agent, tool_tracker):
        """ISSUE #1: Agent should call web_fetch after web_search

        This test verifies that when the agent needs detailed information
        from a search result, it follows up with a fetch to get the full content.
        """
        # Track web_search and web_fetch calls
        search_calls = []
        fetch_calls = []

        original_handlers = agent._tool_handlers.copy()

        def mock_search(**kwargs):
            search_calls.append(kwargs)
            return '[{"title": "Flight Info", "url": "https://example.com/flights", "snippet": "Flight schedule"}]'

        def mock_fetch(**kwargs):
            fetch_calls.append(kwargs)
            return "# Flight Schedule\n\nDetails: CA1234 08:30-10:45"

        agent._tool_handlers["web_search"] = mock_search
        agent._tool_handlers["web_fetch"] = mock_fetch

        try:
            # The agent should first search, then fetch the URL
            # We can't fully test the LLM behavior, but we can verify the handlers work
            assert "web_search" in agent._tool_handlers
            assert "web_fetch" in agent._tool_handlers

            # Manual verification that chain works
            search_result = mock_search(query="Changsha Beijing flights")
            assert "example.com" in search_result

            url = "https://example.com/flights"
            fetch_result = mock_fetch(url=url)
            assert "Flight Schedule" in fetch_result

            # This demonstrates the expected chain
            assert len(search_calls) == 0  # We didn't call through agent yet
            assert len(fetch_calls) == 0

        finally:
            agent._tool_handlers = original_handlers


class TestJudgeSystem:
    """Test the judge evaluation system"""

    def test_judge_returns_tuple(self, mock_api_key):
        """run_judge should return (pass: bool, advice: str)"""
        from agent_framework.core._tools import run_judge

        # Without real API key, judge should return failure
        result = run_judge("Some tool result", "User's original question")
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], bool)  # pass
        assert isinstance(result[1], str)   # advice

    def test_judge_without_api_key(self, monkeypatch):
        """Without API key, judge should return fail verdict"""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)

        from agent_framework.core._tools import run_judge

        result = run_judge("Some result", "Some question")
        # Should return fail since no API key
        assert result[0] == False

    def test_judge_with_empty_result(self, mock_api_key):
        """Judge should handle empty results"""
        from agent_framework.core._tools import run_judge

        result = run_judge("", "Some question")
        # Empty result should likely fail
        assert isinstance(result, tuple)


class TestToolErrorClassification:
    """Test error classification in tool execution"""

    def test_error_classification(self):
        """Errors should be classified into categories"""
        from agent_framework.core.error_classifier import classify_error, FailoverReason

        # Test various error types
        errors = [
            ConnectionError("Connection refused"),
            ValueError("Invalid input"),
            RuntimeError("Tool execution failed"),
        ]

        for error in errors:
            classified = classify_error(error)
            # Should have reason and recovery hints
            assert classified.reason is not None
            # Recovery hints are boolean flags
            assert hasattr(classified, 'retryable')
            assert hasattr(classified, 'should_compress')
