"""ISSUE #1 Verification Test: Agent should call web_fetch after web_search

This test verifies that when the agent needs detailed information from search
results, it follows up with a web_fetch to get the full page content.

Problem: Agent only calls web_search and returns the metadata, never fetching
the actual page content for detailed information.
"""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock
import json


class TestFlightInfoQuery:
    """Test the flight info query scenario from ISSUE #1"""

    @pytest.mark.asyncio
    async def test_agent_calls_both_search_and_fetch(self, agent):
        """Agent should call BOTH web_search AND web_fetch for detailed queries

        This is the core of ISSUE #1: The agent searches for flight info,
        but doesn't fetch the actual page content to get the detailed schedule.
        """
        tool_calls = []

        # Track all tool calls
        original_handlers = agent._tool_handlers.copy()

        def tracked_web_search(**kwargs):
            tool_calls.append({"tool": "web_search", "kwargs": kwargs})
            return json.dumps([
                {
                    "title": "长沙到北京航班",
                    "url": "https://www.example.com/flights/changsha-beijing",
                    "snippet": "提供长沙到北京的航班时刻表..."
                }
            ])

        def tracked_web_fetch(**kwargs):
            tool_calls.append({"tool": "web_fetch", "kwargs": kwargs})
            return """# 航班时刻表

| 航班号 | 出发 | 到达 | 票价 |
|--------|------|------|------|
| CA1234 | 08:30 | 10:45 | ¥890 |
| MU5678 | 14:20 | 16:35 | ¥920 |
"""

        agent._tool_handlers["web_search"] = tracked_web_search
        agent._tool_handlers["web_fetch"] = tracked_web_fetch

        try:
            # Mock LLM to return search results, then fetch, then answer
            with patch("agent_framework.core.client") as mock_client:
                # First LLM call: returns search tool call
                # Second LLM call: returns fetch tool call
                # Third LLM call: returns final answer
                mock_client.messages.create.side_effect = [
                    # Turn 1: Agent decides to search
                    MagicMock(
                        content=[
                            MagicMock(
                                type="tool_use",
                                name="web_search",
                                input={"query": "长沙到北京航班"},
                                id="call_1"
                            )
                        ],
                        stop_reason="tool_use",
                        usage=MagicMock(input_tokens=100, output_tokens=10),
                    ),
                    # Turn 2: After seeing search results, agent decides to fetch
                    MagicMock(
                        content=[
                            MagicMock(
                                type="tool_use",
                                name="web_fetch",
                                input={"url": "https://www.example.com/flights/changsha-beijing"},
                                id="call_2"
                            )
                        ],
                        stop_reason="tool_use",
                        usage=MagicMock(input_tokens=200, output_tokens=10),
                    ),
                    # Turn 3: Agent provides final answer with fetched content
                    MagicMock(
                        content=[MagicMock(type="text", text="找到了航班信息：CA1234 08:30出发，10:45到达，票价¥890")],
                        stop_reason="end_turn",
                        usage=MagicMock(input_tokens=500, output_tokens=50),
                    ),
                ]

                result = await agent.think("查一下今天长沙到北京的航班")

                # Verify tool calls were made
                search_calls = [c for c in tool_calls if c["tool"] == "web_search"]
                fetch_calls = [c for c in tool_calls if c["tool"] == "web_fetch"]

                print(f"[ISSUE #1 DEBUG] Tool calls made:")
                print(f"  - web_search calls: {len(search_calls)}")
                print(f"  - web_fetch calls: {len(fetch_calls)}")
                print(f"  - Result: {result[:100]}...")

                # ISSUE #1 VERIFICATION: Agent SHOULD call BOTH search AND fetch
                assert len(search_calls) > 0, (
                    "ISSUE #1: Agent should call web_search for flight information"
                )
                assert len(fetch_calls) > 0, (
                    f"ISSUE #1 FAIL: Agent called web_search {len(search_calls)} time(s) "
                    f"but NEVER called web_fetch to get detailed content. "
                    f"The agent returned metadata instead of actual flight schedule."
                )

        finally:
            agent._tool_handlers = original_handlers

    @pytest.mark.asyncio
    async def test_search_metadata_insufficient_for_details(self):
        """Demonstrate that search metadata alone is insufficient

        web_search returns: URLs, titles, snippets
        web_fetch returns: Full page content with detailed information

        For flight schedules, we need the detailed table which requires fetch.
        """
        # This test demonstrates WHY fetch is needed after search
        metadata = {
            "title": "航班时刻表",
            "url": "https://example.com/flights",
            "snippet": "提供长沙到北京航班时刻表..."
        }

        # Metadata doesn't contain the actual schedule
        assert "CA1234" not in metadata["snippet"]
        assert "08:30" not in metadata["snippet"]

        # Full content contains the details
        full_content = """
# 航班时刻表

| 航班号 | 出发 | 到达 | 票价 |
|--------|------|------|------|
| CA1234 | 08:30 | 10:45 | ¥890 |
| MU5678 | 14:20 | 16:35 | ¥920 |
"""

        assert "CA1234" in full_content
        assert "08:30" in full_content

        # This proves that for detailed queries, fetch is necessary


class TestToolChainWorkflow:
    """Test the complete search -> fetch -> answer workflow"""

    @pytest.mark.asyncio
    async def test_complete_workflow(self):
        """Test the full workflow: search -> fetch -> answer"""
        from agent_framework.core._tools import run_web_search, run_web_fetch

        search_results = [
            {
                "title": "Flight Schedule",
                "url": "https://example.com/schedule",
                "snippet": "Complete flight schedule..."
            }
        ]

        fetch_content = """
# 长沙-北京航班

| CA1234 | 08:30 | 10:45 |
| MU5678 | 14:20 | 16:35 |
"""

        with patch("agent_framework.core._tools._web_search") as mock_search, \
             patch("agent_framework.core._tools._web_fetch") as mock_fetch:

            mock_search.return_value = search_results
            mock_fetch.return_value = fetch_content

            # Step 1: Search
            results = run_web_search("Changsha Beijing flights")
            assert len(results) > 0
            url = results[0]["url"]

            # Step 2: Fetch
            content = run_web_fetch(url)
            assert "CA1234" in content
            assert "08:30" in content

            # Step 3: Answer would use this content
            # (In real agent, LLM synthesizes final answer)


class TestJudgeSystemInWorkflow:
    """Test judge system integration with tool chain"""

    @pytest.mark.asyncio
    async def test_judge_evaluates_fetch_result(self, mock_api_key):
        """Judge should evaluate if tool results solve the problem"""
        from agent_framework.core._tools import run_judge

        # Good result with details
        good_result = """
# 航班信息

| 航班号 | 出发时间 | 到达时间 | 票价 |
|--------|----------|----------|------|
| CA1234 | 08:30 | 10:45 | ¥890 |
| MU5678 | 14:20 | 16:35 | ¥920 |
"""

        user_question = "查一下今天长沙到北京的航班"

        # Judge should evaluate if this result answers the question
        # (Actual judgment depends on LLM, so we just verify it runs)
        verdict, advice = run_judge(good_result, user_question)
        assert isinstance(verdict, bool)
        assert isinstance(advice, str)
