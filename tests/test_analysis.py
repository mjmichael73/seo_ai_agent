"""Tests for deterministic SEO rules and report assembly."""

from seo_ai_agent.analysis import analyze_site
from seo_ai_agent.models import PageSnapshot, SearchResult


def good_page(**overrides):
    values = {
        "url": "https://example.com/",
        "final_url": "https://example.com/",
        "status_code": 200,
        "content_type": "text/html",
        "title": "A thoughtful and descriptive page title for search",
        "meta_description": (
            "A useful summary of the page for visitors and searchers to understand "
            "what they can find here."
        ),
        "canonical_url": "https://example.com/",
        "robots_meta": "index,follow",
        "headings": ["Primary topic"],
        "h1_count": 1,
        "word_count": 420,
        "images_total": 1,
        "images_missing_alt": 0,
        "internal_links": 2,
        "external_links": 1,
        "discovered_links": ["https://example.com/about"],
        "load_time_ms": 900,
    }
    values.update(overrides)
    return PageSnapshot(**values)


def test_analyze_site_reports_healthy_page_without_findings():
    report = analyze_site(
        target_url="https://example.com/",
        pages=[good_page()],
        robots_status="available",
        sitemap_urls=["https://example.com/sitemap.xml"],
        notes=[],
    )
    assert report.score == 100
    assert report.findings == []
    assert report.priority_actions == []
    assert "1 public page" in report.summary
    assert report.keyword_results == []


def test_analyze_site_handles_robots_and_no_pages():
    unavailable = analyze_site(
        target_url="https://example.com/",
        pages=[],
        robots_status="unavailable",
        sitemap_urls=[],
        notes=["network issue"],
    )
    assert unavailable.score == 0
    assert len(unavailable.findings) == 2
    assert "No public pages" in unavailable.summary
    missing = analyze_site(
        target_url="https://example.com/",
        pages=[],
        robots_status="not_found",
        sitemap_urls=[],
        notes=[],
    )
    assert {finding.severity for finding in missing.findings} == {"info", "low", "high"}


def test_analyze_site_flags_page_metadata_and_content_issues():
    page = good_page(
        status_code=404,
        title="Short",
        meta_description="tiny",
        canonical_url=None,
        robots_meta="NOINDEX,follow",
        h1_count=0,
        word_count=45,
        images_total=3,
        images_missing_alt=2,
        internal_links=0,
        load_time_ms=3_400,
    )
    report = analyze_site(
        target_url=page.url,
        pages=[page],
        robots_status="available",
        sitemap_urls=["https://example.com/sitemap.xml"],
        notes=[],
    )
    issues = {finding.issue for finding in report.findings}
    assert "Page returned a client error" in issues
    assert "Title tag may be too short" in issues
    assert "Meta description length is outside the usual range" in issues
    assert "Canonical URL is missing" in issues
    assert "Page declares noindex" in issues
    assert "No H1 heading was found" in issues
    assert "Very little visible page text was found" in issues
    assert "Image alternative text is missing" in issues
    assert "No internal links were found" in issues
    assert "Page response was slow" in issues
    assert 0 <= report.score < 100
    assert len(report.priority_actions) == 3
    assert all(
        finding.url == page.url for finding in report.findings if finding.category != "discovery"
    )


def test_analyze_site_flags_server_error_long_title_multiple_h1_and_limited_text():
    page = good_page(
        status_code=503,
        title="A" * 70,
        meta_description="",
        h1_count=2,
        word_count=150,
    )
    report = analyze_site(
        target_url=page.url,
        pages=[page],
        robots_status="unknown",
        sitemap_urls=[],
        notes=[],
    )
    issues = {finding.issue for finding in report.findings}
    assert "Page returned a server error" in issues
    assert "Title tag may be too long" in issues
    assert "Meta description is missing or empty" in issues
    assert "Multiple H1 headings were found" in issues
    assert "Page has limited visible text" in issues
    assert "No sitemap was discovered" not in issues


def test_analyze_site_handles_non_html_and_low_priority_findings():
    page = good_page(
        content_type="application/pdf",
        status_code=200,
    )
    report = analyze_site(
        target_url=page.url,
        pages=[page],
        robots_status="not_found",
        sitemap_urls=[],
        notes=[],
        keyword="topic",
        keyword_results=[SearchResult(title="Result", url="https://example.org/", snippet="Text")],
    )
    issues = {finding.issue for finding in report.findings}
    assert "Page is not HTML" in issues
    assert "No robots.txt file was found" in issues
    assert "No sitemap was discovered" in issues
    assert len(report.keyword_results) == 1
    assert report.keyword == "topic"
    assert not any(finding.category == "on-page metadata" for finding in report.findings)


def test_priority_actions_are_unique_and_score_is_bounded():
    pages = [
        good_page(
            url=f"https://example.com/{index}", title=None, meta_description=None, word_count=0
        )
        for index in range(4)
    ]
    report = analyze_site(
        target_url="https://example.com/",
        pages=pages,
        robots_status="available",
        sitemap_urls=["https://example.com/sitemap.xml"],
        notes=[],
    )
    assert len(report.priority_actions) <= 3
    assert len(set(report.priority_actions)) == len(report.priority_actions)
    assert 0 <= report.score < 100
