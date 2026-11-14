"""Free, qualitative keyword research using the public DuckDuckGo search interface."""

from typing import Any

from ddgs import DDGS
from langchain_core.tools import BaseTool, tool


def _perform_search(query: str, max_results: int, timeout_seconds: float) -> list[dict[str, str]]:
    """Validate and normalize a bounded DuckDuckGo search request."""

    normalized = query.strip()
    if not normalized:
        raise ValueError("query must contain non-whitespace characters")
    if len(normalized) > 200:
        raise ValueError("query must be 200 characters or fewer")
    if not 1 <= max_results <= 10:
        raise ValueError("max_results must be between 1 and 10")

    results: list[dict[str, str]] = []
    for item in DDGS(timeout=timeout_seconds).text(normalized, max_results=max_results) or []:
        if not isinstance(item, dict):
            continue
        url = str(item.get("href") or item.get("url") or "").strip()
        if not url:
            continue
        results.append(
            {
                "title": str(item.get("title") or "Untitled result").strip(),
                "url": url,
                "snippet": str(item.get("body") or item.get("snippet") or "").strip(),
            }
        )
    return results


@tool("search_web")
def search_web(query: str, max_results: int = 5) -> list[dict[str, str]]:
    """Find public web pages related to a keyword; results are not rank-tracking data."""

    return _perform_search(query, max_results, 8.0)


def make_search_tool(timeout_seconds: float = 8.0) -> BaseTool:
    """Build a LangChain search tool with the configured request timeout."""

    @tool("search_web")
    def configured_search_web(query: str, max_results: int = 5) -> list[dict[str, str]]:
        """Find public web pages related to a keyword; results are not rank-tracking data."""

        return _perform_search(query, max_results, timeout_seconds)

    return configured_search_web


def normalize_search_results(raw_results: Any) -> list[dict[str, str]]:
    """Coerce tool output into report-safe result dictionaries."""

    normalized: list[dict[str, str]] = []
    for item in raw_results or []:
        if isinstance(item, dict) and item.get("url"):
            normalized.append(
                {
                    "title": str(item.get("title") or "Untitled result"),
                    "url": str(item["url"]),
                    "snippet": str(item.get("snippet") or ""),
                }
            )
    return normalized
