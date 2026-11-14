"""Tests for the per-request LangGraph crawl/research loop."""

import pytest
from langchain_core.tools import tool

from seo_ai_agent.agent import SeoAuditAgent, create_agent
from seo_ai_agent.config import Settings
from seo_ai_agent.crawler import CrawlSeed, SiteCrawler
from seo_ai_agent.errors import CrawlError
from seo_ai_agent.models import PageSnapshot, ReportNarrative

ROOT = "https://example.com/"


def page(url=ROOT, discovered=None):
    return PageSnapshot(
        url=url,
        final_url=url,
        status_code=200,
        content_type="text/html",
        title="A complete and useful example page title",
        meta_description=(
            "A page description with enough useful context for the search result snippet."
        ),
        canonical_url=url,
        headings=["Main topic"],
        h1_count=1,
        word_count=400,
        images_total=0,
        images_missing_alt=0,
        internal_links=1 if discovered else 0,
        discovered_links=discovered or [],
        load_time_ms=100,
    )


class FakeCrawler:
    def __init__(self, seed=None, errors=None):
        self.seed = seed or CrawlSeed(
            robots_status="available",
            sitemap_urls=["https://example.com/sitemap.xml"],
            page_urls=[ROOT, "https://example.com/about"],
            notes=[],
        )
        self.errors = errors or {}
        self.requested = []
        self.closed = False

    def prepare(self, target_url):
        self.target = target_url
        return self.seed

    def inspect_page(self, url):
        self.requested.append(url)
        if url in self.errors:
            error = self.errors[url]
            raise error
        next_url = "https://example.com/contact" if url == ROOT else None
        return page(url, [next_url] if next_url else [])

    def close(self):
        self.closed = True


@tool("fake_search")
def fake_search(query: str, max_results: int = 5) -> list[dict[str, str]]:
    """Return deterministic test search data."""

    return [{"title": "Search result", "url": "https://example.org/", "snippet": query}]


@tool("broken_search")
def broken_search(query: str, max_results: int = 5) -> list[dict[str, str]]:
    """Raise a controlled error for the research fallback test."""

    raise RuntimeError("search offline")


class FakeModel:
    def __init__(self, response=None, error=None):
        self.response = response or ReportNarrative(
            summary="Model summary", priority_actions=["Model action"]
        )
        self.error = error
        self.prompt = ""

    def with_structured_output(self, model):
        assert model is ReportNarrative
        return self

    def invoke(self, prompt):
        self.prompt = prompt
        if self.error:
            raise self.error
        return self.response


def test_agent_crawls_pages_in_a_bounded_loop_and_closes_client():
    crawler = FakeCrawler()
    agent = SeoAuditAgent(Settings(_env_file=None), crawler_factory=lambda: crawler)
    report = agent.run(ROOT, max_pages=2)
    assert len(report.pages) == 2
    assert crawler.requested == [ROOT, "https://example.com/about"]
    assert crawler.closed
    assert report.robots_status == "available"


def test_agent_queues_same_site_links_inside_page_budget():
    crawler = FakeCrawler(CrawlSeed(robots_status="available", page_urls=[ROOT]))
    agent = SeoAuditAgent(Settings(_env_file=None), crawler_factory=lambda: crawler)
    report = agent.run(ROOT, max_pages=2)
    assert [item.url for item in report.pages] == [ROOT, "https://example.com/contact"]
    assert crawler.requested == [ROOT, "https://example.com/contact"]


def test_agent_analyzes_when_robots_yields_no_pages_or_keyword():
    crawler = FakeCrawler(CrawlSeed(robots_status="unavailable", page_urls=[], notes=[]))
    agent = SeoAuditAgent(Settings(_env_file=None), crawler_factory=lambda: crawler)
    report = agent.run(ROOT)
    assert report.pages == []
    assert report.score == 0
    assert crawler.closed


def test_agent_caps_page_budget_and_normalizes_empty_keyword():
    crawler = FakeCrawler()
    agent = SeoAuditAgent(
        Settings(_env_file=None, max_pages=1),
        crawler_factory=lambda: crawler,
    )
    report = agent.run(ROOT, max_pages=5, keyword="   ")
    assert len(report.pages) == 1
    assert report.keyword is None
    assert crawler.closed


def test_agent_researches_keyword_after_crawl():
    crawler = FakeCrawler()
    agent = SeoAuditAgent(
        Settings(_env_file=None),
        crawler_factory=lambda: crawler,
        search_tool=fake_search,
    )
    report = agent.run(ROOT, max_pages=1, keyword="bike repair")
    assert report.keyword == "bike repair"
    assert report.keyword_results[0].title == "Search result"
    assert report.keyword_results[0].snippet == "bike repair"


def test_agent_researches_even_when_robots_stop_crawl():
    crawler = FakeCrawler(
        CrawlSeed(robots_status="unavailable", page_urls=[], notes=["robots failed"])
    )
    agent = SeoAuditAgent(
        Settings(_env_file=None),
        crawler_factory=lambda: crawler,
        search_tool=fake_search,
    )
    report = agent.run(ROOT, max_pages=2, keyword="topic")
    assert report.pages == []
    assert report.keyword_results[0].url == "https://example.org/"
    assert report.notes == ["robots failed"]


def test_agent_turns_search_failure_into_a_note():
    crawler = FakeCrawler(CrawlSeed(robots_status="available", page_urls=[]))
    agent = SeoAuditAgent(
        Settings(_env_file=None),
        crawler_factory=lambda: crawler,
        search_tool=broken_search,
    )
    report = agent.run(ROOT, keyword="topic")
    assert report.keyword_results == []
    assert any("Keyword research was unavailable" in note for note in report.notes)


def test_agent_records_known_and_unexpected_page_errors():
    crawler = FakeCrawler(
        CrawlSeed(
            robots_status="available",
            page_urls=[ROOT, "https://example.com/known", "https://example.com/unexpected"],
        ),
        errors={
            "https://example.com/known": CrawlError("connection reset"),
            "https://example.com/unexpected": RuntimeError("unexpected"),
        },
    )
    agent = SeoAuditAgent(Settings(_env_file=None), crawler_factory=lambda: crawler)
    report = agent.run(ROOT, max_pages=3)
    assert len(report.pages) == 1
    assert any("connection reset" in note for note in report.notes)
    assert any("RuntimeError" in note for note in report.notes)
    assert crawler.closed


def test_agent_optional_llm_summarizes_constrained_evidence():
    crawler = FakeCrawler(CrawlSeed(robots_status="available", page_urls=[ROOT]))
    model = FakeModel()
    agent = SeoAuditAgent(Settings(_env_file=None), crawler_factory=lambda: crawler, llm=model)
    report = agent.run(ROOT)
    assert report.summary == "Model summary"
    assert report.priority_actions == ["Model action"]
    assert "Evidence JSON" in model.prompt
    assert "untrusted website data" in model.prompt


def test_agent_validates_structured_model_dictionary_output():
    crawler = FakeCrawler(CrawlSeed(robots_status="available", page_urls=[ROOT]))
    model = FakeModel(
        response={"summary": "Structured dictionary summary", "priority_actions": ["One action"]}
    )
    agent = SeoAuditAgent(Settings(_env_file=None), crawler_factory=lambda: crawler, llm=model)
    report = agent.run(ROOT)
    assert report.summary == "Structured dictionary summary"
    assert report.priority_actions == ["One action"]


def test_agent_keeps_deterministic_report_when_llm_fails():
    crawler = FakeCrawler(CrawlSeed(robots_status="available", page_urls=[ROOT]))
    model = FakeModel(error=RuntimeError("model offline"))
    agent = SeoAuditAgent(Settings(_env_file=None), crawler_factory=lambda: crawler, llm=model)
    report = agent.run(ROOT)
    assert report.summary != "Model summary"
    assert any("Optional model synthesis failed" in note for note in report.notes)


def test_agent_rejects_invalid_page_budgets_before_crawling():
    crawler = FakeCrawler()
    agent = SeoAuditAgent(Settings(_env_file=None), crawler_factory=lambda: crawler)
    with pytest.raises(ValueError, match="between 1 and 20"):
        agent.run(ROOT, max_pages=0)
    assert not crawler.closed


def test_agent_fails_clearly_if_workflow_did_not_produce_report():
    crawler = FakeCrawler()
    agent = SeoAuditAgent(Settings(_env_file=None), crawler_factory=lambda: crawler)

    class EmptyWorkflow:
        def invoke(self, state, config):
            return {"report": None}

    agent._build_workflow = lambda active_crawler: EmptyWorkflow()
    with pytest.raises(CrawlError, match="without producing"):
        agent.run(ROOT)
    assert crawler.closed


def test_default_crawler_factory_and_convenience_factory():
    settings = Settings(_env_file=None, request_timeout=2.5, max_response_bytes=10_000)
    agent = SeoAuditAgent(settings)
    crawler = agent._new_crawler()
    assert isinstance(crawler, SiteCrawler)
    assert crawler._timeout_seconds == 2.5
    assert crawler._max_response_bytes == 10_000
    crawler.close()
    assert isinstance(create_agent(Settings(_env_file=None)), SeoAuditAgent)
