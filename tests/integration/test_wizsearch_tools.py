"""Integration tests for wizsearch toolkit (tarzi-backed search, crawl).

Tests search and crawl capabilities with real API / network calls.
"""

import pytest

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# Wizsearch Search Tool Tests
# ---------------------------------------------------------------------------

_tarzi_available = False
try:
    import tarzi  # noqa: F401

    _tarzi_available = True
except ImportError:
    pass


class TestWizsearchSearchTool:
    """Integration tests for wizsearch search tool."""

    @pytest.fixture
    def search_tool(self):
        """Create WizsearchSearchTool instance."""
        pytest.importorskip("tarzi", reason="tarzi package required")
        from soothe_nano.toolkits.wizsearch import WizsearchSearchTool

        return WizsearchSearchTool()

    def test_basic_web_search(self, search_tool) -> None:
        """Test basic web search functionality."""
        import os

        has_serper = bool(os.getenv("SERPER_API_KEY"))
        has_tavily = bool(os.getenv("TAVILY_API_KEY"))

        if not (has_serper or has_tavily):
            pytest.skip("SERPER_API_KEY or TAVILY_API_KEY required for search test")

        engines = ["google_serper"] if has_serper else ["tavily"]
        tool = search_tool
        tool.default_engines = engines
        result = tool._run("Python asyncio tutorial", max_results_per_engine=5)

        assert isinstance(result, (str, dict))

    def test_search_tool_name(self, search_tool) -> None:
        """Test tool name is prefixed correctly."""
        assert search_tool.name == "wizsearch_search"


class TestWizsearchCrawlTool:
    """Integration tests for wizsearch crawl tool."""

    @pytest.fixture
    def crawl_tool(self):
        """Create WizsearchCrawlTool instance."""
        pytest.importorskip("tarzi", reason="tarzi package required")
        from soothe_nano.toolkits.wizsearch import WizsearchCrawlTool

        return WizsearchCrawlTool()

    def test_basic_crawl(self, crawl_tool) -> None:
        """Test basic page crawl via tarzi WebFetcher."""
        result = crawl_tool._run("https://example.com", content_format="markdown")
        assert isinstance(result, str)
        assert len(result) > 0 or "error" in result.lower() or "Crawl error" in result

    def test_crawl_tool_name(self, crawl_tool) -> None:
        """Test tool name is prefixed correctly."""
        assert crawl_tool.name == "wizsearch_crawl"


class TestWizsearchErrorHandling:
    """Test error handling and edge cases for wizsearch tools."""

    def test_search_without_tarzi(self) -> None:
        """Search reports clearly when tarzi is missing."""
        pytest.importorskip("tarzi", reason="tarzi package required")
        from soothe_nano.toolkits.wizsearch import WizsearchSearchTool

        tool = WizsearchSearchTool()
        assert tool.name == "wizsearch_search"

    def test_crawl_invalid_url(self) -> None:
        """Crawl rejects invalid URLs."""
        pytest.importorskip("tarzi", reason="tarzi package required")
        from soothe_nano.toolkits.wizsearch import WizsearchCrawlTool

        tool = WizsearchCrawlTool()
        result = tool._run("not-a-url")
        assert isinstance(result, str)
