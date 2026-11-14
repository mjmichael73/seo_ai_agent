"""Tests for the free public-search LangChain tool."""

import pytest

from seo_ai_agent import research
from seo_ai_agent.research import make_search_tool, normalize_search_results, search_web


def test_search_web_normalizes_public_results(monkeypatch):
    calls = {}

    class FakeDDGS:
        def __init__(self, timeout):
            calls["timeout"] = timeout

        def text(self, query, max_results):
            calls["query"] = query
            calls["max_results"] = max_results
            return [
                {"title": " Result ", "href": "https://example.com/", "body": " Snippet "},
                {"url": "https://example.org/", "snippet": "Other"},
                {"title": "Missing URL"},
                "not a mapping",
            ]

    monkeypatch.setattr(research, "DDGS", FakeDDGS)
    results = search_web.invoke({"query": "  useful topic ", "max_results": 2})
    assert calls == {"timeout": 8.0, "query": "useful topic", "max_results": 2}
    assert results == [
        {"title": "Result", "url": "https://example.com/", "snippet": "Snippet"},
        {"title": "Untitled result", "url": "https://example.org/", "snippet": "Other"},
    ]


def test_search_web_validation_and_empty_results():
    with pytest.raises(ValueError, match="non-whitespace"):
        search_web.invoke({"query": "   "})
    with pytest.raises(ValueError, match="200 characters"):
        search_web.invoke({"query": "x" * 201})
    with pytest.raises(ValueError, match="max_results"):
        search_web.invoke({"query": "valid query", "max_results": 0})
    with pytest.raises(ValueError, match="max_results"):
        search_web.invoke({"query": "valid query", "max_results": 11})


def test_configured_tool_uses_timeout_and_handles_no_results(monkeypatch):
    timeouts = []

    class FakeDDGS:
        def __init__(self, timeout):
            timeouts.append(timeout)

        def text(self, query, max_results):
            return None

    monkeypatch.setattr(research, "DDGS", FakeDDGS)
    assert make_search_tool(timeout_seconds=3.5).invoke({"query": "topic"}) == []
    assert timeouts == [3.5]


def test_normalize_search_results_filters_bad_values():
    assert normalize_search_results(None) == []
    assert normalize_search_results(
        [
            {"url": "https://example.com", "title": "Title", "snippet": "Text"},
            {"url": "https://example.org"},
            {"title": "No URL"},
            "invalid",
        ]
    ) == [
        {"title": "Title", "url": "https://example.com", "snippet": "Text"},
        {"title": "Untitled result", "url": "https://example.org", "snippet": ""},
    ]
