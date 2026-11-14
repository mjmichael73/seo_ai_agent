"""Deterministic SEO checks and evidence-backed report assembly."""

from __future__ import annotations

import re
from collections.abc import Iterable

from seo_ai_agent.models import Finding, PageSnapshot, SearchResult, SiteReport

_SEVERITY_WEIGHT = {"critical": 25, "high": 15, "medium": 7, "low": 3, "info": 0}
_SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}


def _finding(
    severity: str,
    category: str,
    issue: str,
    evidence: str,
    recommendation: str,
    url: str | None = None,
) -> Finding:
    """Create a normalized report finding."""

    return Finding(
        severity=severity,  # type: ignore[arg-type]
        category=category,
        issue=issue,
        evidence=evidence,
        recommendation=recommendation,
        url=url,
    )


def analyze_site(
    *,
    target_url: str,
    pages: list[PageSnapshot],
    robots_status: str,
    sitemap_urls: list[str],
    notes: list[str],
    keyword: str | None = None,
    keyword_results: Iterable[SearchResult] = (),
) -> SiteReport:
    """Turn crawl facts into prioritized advice; no change is ever applied to a site."""

    findings: list[Finding] = []
    if robots_status == "unavailable":
        findings.append(
            _finding(
                "high",
                "crawlability",
                "Could not confirm crawl rules",
                "robots.txt could not be read, so page crawling stopped safely.",
                (
                    "Check that robots.txt is reachable and returns a valid response "
                    "before auditing pages."
                ),
            )
        )
    elif robots_status == "not_found":
        findings.append(
            _finding(
                "info",
                "crawlability",
                "No robots.txt file was found",
                "The robots.txt endpoint returned HTTP 404.",
                "Add a robots.txt file if you need to document crawl rules or advertise a sitemap.",
            )
        )
    if robots_status in {"available", "not_found"} and not sitemap_urls:
        findings.append(
            _finding(
                "low",
                "discovery",
                "No sitemap was discovered",
                "No readable same-site sitemap was listed or found at the standard location.",
                (
                    "Publish a current XML sitemap and reference it in robots.txt "
                    "to help crawlers discover URLs."
                ),
            )
        )
    if not pages:
        findings.append(
            _finding(
                "high",
                "crawlability",
                "No pages were inspected",
                "The crawler collected no page snapshots within the configured scope.",
                (
                    "Review robots.txt, site availability, and the audit URL, "
                    "then run the audit again."
                ),
            )
        )

    for page in pages:
        if page.status_code >= 500:
            findings.append(
                _finding(
                    "critical",
                    "indexability",
                    "Page returned a server error",
                    f"The page returned HTTP {page.status_code}.",
                    (
                        "Investigate the server response and restore a stable successful status "
                        "for important URLs."
                    ),
                    page.url,
                )
            )
        elif page.status_code >= 400:
            findings.append(
                _finding(
                    "high",
                    "indexability",
                    "Page returned a client error",
                    f"The page returned HTTP {page.status_code}.",
                    (
                        "Repair the URL or redirect it to the closest relevant live page, "
                        "where appropriate."
                    ),
                    page.url,
                )
            )

        if page.content_type and page.content_type not in {"text/html", "application/xhtml+xml"}:
            findings.append(
                _finding(
                    "medium",
                    "content",
                    "Page is not HTML",
                    f"The response content type was {page.content_type}.",
                    (
                        "Confirm that this URL should serve HTML; when searchable, "
                        "provide an HTML landing page."
                    ),
                    page.url,
                )
            )
            continue

        if not page.title:
            findings.append(
                _finding(
                    "high",
                    "on-page metadata",
                    "Title tag is missing or empty",
                    "No non-empty HTML title was found.",
                    (
                        "Add a concise, unique title that accurately describes the page "
                        "and its primary topic."
                    ),
                    page.url,
                )
            )
        elif len(page.title) < 30:
            findings.append(
                _finding(
                    "medium",
                    "on-page metadata",
                    "Title tag may be too short",
                    f"The title contains {len(page.title)} characters.",
                    (
                        "Review whether the title can describe the page more clearly "
                        "without adding irrelevant keywords."
                    ),
                    page.url,
                )
            )
        elif len(page.title) > 60:
            findings.append(
                _finding(
                    "medium",
                    "on-page metadata",
                    "Title tag may be too long",
                    f"The title contains {len(page.title)} characters.",
                    (
                        "Consider a more concise title; search engines may truncate titles "
                        "depending on the result layout."
                    ),
                    page.url,
                )
            )

        if not page.meta_description:
            findings.append(
                _finding(
                    "medium",
                    "on-page metadata",
                    "Meta description is missing or empty",
                    "No non-empty meta description was found.",
                    (
                        "Write a distinct, useful description that summarizes the page "
                        "for prospective visitors."
                    ),
                    page.url,
                )
            )
        elif not 70 <= len(page.meta_description) <= 160:
            findings.append(
                _finding(
                    "low",
                    "on-page metadata",
                    "Meta description length is outside the usual range",
                    f"The description contains {len(page.meta_description)} characters.",
                    (
                        "Review the description for clarity and concision; snippet length varies "
                        "across devices and queries."
                    ),
                    page.url,
                )
            )

        if not page.canonical_url:
            findings.append(
                _finding(
                    "low",
                    "indexability",
                    "Canonical URL is missing",
                    "No rel=canonical link was found.",
                    (
                        "Add a canonical link for duplicate or near-duplicate URL variants; "
                        "verify its target."
                    ),
                    page.url,
                )
            )
        if page.robots_meta and re.search(r"\bnoindex\b", page.robots_meta, flags=re.IGNORECASE):
            findings.append(
                _finding(
                    "high",
                    "indexability",
                    "Page declares noindex",
                    f"The robots meta directive is: {page.robots_meta}.",
                    (
                        "Confirm that excluding this page from search is intentional; "
                        "remove noindex only if it should be indexed."
                    ),
                    page.url,
                )
            )
        if page.h1_count == 0:
            findings.append(
                _finding(
                    "medium",
                    "content structure",
                    "No H1 heading was found",
                    "The page contains zero H1 headings.",
                    "Use a clear primary heading that reflects the visible main topic of the page.",
                    page.url,
                )
            )
        elif page.h1_count > 1:
            findings.append(
                _finding(
                    "low",
                    "content structure",
                    "Multiple H1 headings were found",
                    f"The page contains {page.h1_count} H1 headings.",
                    (
                        "Review the heading hierarchy and use one clear primary heading "
                        "where that improves page structure."
                    ),
                    page.url,
                )
            )
        if page.word_count < 100:
            findings.append(
                _finding(
                    "high",
                    "content",
                    "Very little visible page text was found",
                    f"The page contains about {page.word_count} visible words.",
                    (
                        "Check whether the page provides enough useful, original information "
                        "for its intended search intent."
                    ),
                    page.url,
                )
            )
        elif page.word_count < 300:
            findings.append(
                _finding(
                    "medium",
                    "content",
                    "Page has limited visible text",
                    f"The page contains about {page.word_count} visible words.",
                    (
                        "Consider whether additional useful context would help visitors; "
                        "avoid adding filler solely to increase length."
                    ),
                    page.url,
                )
            )
        if page.images_missing_alt:
            findings.append(
                _finding(
                    "low",
                    "accessibility",
                    "Image alternative text is missing",
                    (
                        f"{page.images_missing_alt} of {page.images_total} images have "
                        "empty or missing alt text."
                    ),
                    (
                        "Provide concise alt text for informative images and empty alt attributes "
                        "for decorative images."
                    ),
                    page.url,
                )
            )
        if page.internal_links == 0:
            findings.append(
                _finding(
                    "low",
                    "internal linking",
                    "No internal links were found",
                    "The page has no detected links to another URL on the same site.",
                    (
                        "Add contextual internal links where they help visitors "
                        "navigate related content."
                    ),
                    page.url,
                )
            )
        if page.load_time_ms > 3_000:
            findings.append(
                _finding(
                    "medium",
                    "performance",
                    "Page response was slow",
                    f"The measured response time was {page.load_time_ms} ms.",
                    (
                        "Measure real-user Core Web Vitals and investigate server, asset, "
                        "and rendering bottlenecks."
                    ),
                    page.url,
                )
            )

    findings.sort(
        key=lambda finding: (_SEVERITY_ORDER[finding.severity], finding.category, finding.url or "")
    )
    average_penalty = sum(_SEVERITY_WEIGHT[finding.severity] for finding in findings) / max(
        1, len(pages)
    )
    score = 0 if not pages else max(0, min(100, 100 - round(average_penalty)))
    if pages:
        summary = (
            f"Inspected {len(pages)} public page(s) and identified {len(findings)} finding(s). "
            f"The heuristic technical SEO score is {score}/100; it is not a Google ranking."
        )
    else:
        summary = (
            "No public pages were inspected. Review crawl access and the audit URL "
            "before drawing conclusions."
        )

    priority_actions: list[str] = []
    for finding in findings:
        if (
            finding.severity in {"critical", "high", "medium"}
            and finding.recommendation not in priority_actions
        ):
            priority_actions.append(finding.recommendation)
        if len(priority_actions) == 3:
            break

    return SiteReport(
        target_url=target_url,
        score=score,
        summary=summary,
        pages=pages,
        findings=findings,
        priority_actions=priority_actions,
        keyword=keyword,
        keyword_results=list(keyword_results),
        robots_status=robots_status,
        sitemap_urls=sitemap_urls,
        notes=notes,
    )
