"""LangChain tools backed by the safe site crawler."""

from typing import Any

from langchain_core.tools import BaseTool, tool

from seo_ai_agent.crawler import SiteCrawler


def create_crawler_tools(crawler: SiteCrawler) -> dict[str, BaseTool]:
    """Bind safe crawler operations as LangChain tools for the LangGraph workflow."""

    @tool("inspect_page")
    def inspect_page(url: str) -> dict[str, Any]:
        """Fetch one permitted page and return its on-page SEO evidence as JSON."""

        return crawler.inspect_page(url).model_dump(mode="json")

    return {inspect_page.name: inspect_page}
