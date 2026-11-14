"""Offline tests for SSRF defenses, robots/sitemap parsing, and page extraction."""

import socket

import httpx
import pytest

from seo_ai_agent.crawler import SiteCrawler
from seo_ai_agent.errors import CrawlError, UnsafeTargetError
from tests.conftest import mock_response, public_resolver

ROOT = "https://example.com/"


def make_crawler(handler, *, resolver=public_resolver, **kwargs):
    return SiteCrawler(transport=httpx.MockTransport(handler), resolver=resolver, **kwargs)


def test_url_validation_rejects_schemes_credentials_and_reserved_hosts():
    crawler = SiteCrawler(resolver=public_resolver)
    for url in ("ftp://example.com", "example.com", "https://user:pass@example.com/"):
        with pytest.raises(UnsafeTargetError):
            crawler._validate_public_url(url)
    for url in (
        "http://localhost/",
        "http://api.localhost/",
        "http://printer.local/",
        "http://service.internal/",
        "http://site.test/",
        "http://site.invalid/",
        "http://hidden.onion/",
    ):
        with pytest.raises(UnsafeTargetError):
            crawler._validate_public_url(url)
    with pytest.raises(UnsafeTargetError, match="non-empty"):
        crawler._validate_public_url("")
    with pytest.raises(UnsafeTargetError, match="malformed"):
        crawler._validate_public_url("https://example.com:bad/")
    crawler.close()


def test_url_validation_rejects_private_ip_dns_and_resolution_errors():
    crawler = SiteCrawler(resolver=public_resolver)
    for url in ("http://127.0.0.1/", "http://10.0.0.1/", "http://[::1]/", "http://169.254.1.1/"):
        with pytest.raises(UnsafeTargetError):
            crawler._validate_public_url(url)

    def private_resolver(host, port, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.9", port))]

    private_crawler = SiteCrawler(resolver=private_resolver)
    with pytest.raises(UnsafeTargetError, match="non-public"):
        private_crawler._validate_public_url("https://private.example/")

    def broken_resolver(host, port, **kwargs):
        raise socket.gaierror("no DNS")

    broken_crawler = SiteCrawler(resolver=broken_resolver)
    with pytest.raises(CrawlError, match="Could not resolve"):
        broken_crawler._validate_public_url("https://unknown.example/")
    with pytest.raises(CrawlError, match="did not resolve"):
        SiteCrawler(resolver=lambda *args, **kwargs: [])._validate_public_url(
            "https://empty.example/"
        )
    malformed = SiteCrawler(
        resolver=lambda *args, **kwargs: [(), (socket.AF_INET, 2, 6, "", ("invalid", 443))]
    )
    with pytest.raises(CrawlError, match="did not resolve"):
        malformed._validate_public_url("https://malformed.example/")
    malformed.close()
    for item in (crawler, private_crawler, broken_crawler):
        item.close()


def test_constructor_rejects_invalid_resource_limits():
    with pytest.raises(ValueError, match="positive"):
        SiteCrawler(timeout_seconds=0)
    with pytest.raises(ValueError, match="at least 1024"):
        SiteCrawler(max_response_bytes=100)
    with pytest.raises(ValueError, match="cannot be negative"):
        SiteCrawler(max_redirects=-1)


def test_prepare_reads_robots_sitemap_index_and_filters_scope():
    requests = []
    sitemap_index = (
        '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        "<sitemap><loc>https://example.com/pages.xml</loc></sitemap></sitemapindex>"
    )
    nested_index = "<sitemapindex><sitemap><loc>https://elsewhere.example/child.xml</loc></sitemap></sitemapindex>"
    url_map = {
        "/robots.txt": (
            200,
            "User-agent: *\nAllow: /\nSitemap: https://example.com/index.xml\n"
            "Sitemap: https://example.com/index.xml\nSitemap: https://example.com/nested.xml\n",
            {"content-type": "text/plain"},
        ),
        "/index.xml": (200, sitemap_index, {"content-type": "application/xml"}),
        "/nested.xml": (200, nested_index, {"content-type": "application/xml"}),
        "/pages.xml": (
            200,
            "<urlset><url><loc>https://example.com/about</loc></url>"
            "<url><loc>https://elsewhere.example/page</loc></url></urlset>",
            {"content-type": "application/xml"},
        ),
    }

    def handler(request):
        requests.append(request.url.path)
        status, body, headers = url_map[request.url.path]
        return mock_response(request, status=status, body=body, headers=headers)

    crawler = make_crawler(handler)
    seed = crawler.prepare(ROOT)
    assert seed.robots_status == "available"
    assert seed.sitemap_urls == [
        "https://example.com/index.xml",
        "https://example.com/nested.xml",
        "https://example.com/pages.xml",
    ]
    assert seed.page_urls == [ROOT, "https://example.com/about"]
    assert any("outside the submitted site" in note for note in seed.notes)
    assert "/robots.txt" in requests
    crawler.close()


def test_prepare_uses_default_sitemap_when_robots_missing():
    requested = []

    def handler(request):
        requested.append(request.url.path)
        if request.url.path == "/robots.txt":
            return mock_response(
                request, status=404, body="missing", headers={"content-type": "text/plain"}
            )
        return mock_response(
            request, status=404, body="missing", headers={"content-type": "text/xml"}
        )

    crawler = make_crawler(handler)
    seed = crawler.prepare(ROOT)
    assert seed.robots_status == "not_found"
    assert seed.page_urls == [ROOT]
    assert seed.sitemap_urls == []
    assert "/sitemap.xml" in requested
    assert any("No robots.txt" in note for note in seed.notes)
    crawler.close()


def test_prepare_uses_default_sitemap_when_robots_has_no_declaration():
    requested = []

    def handler(request):
        requested.append(request.url.path)
        if request.url.path == "/robots.txt":
            return mock_response(
                request,
                body="User-agent: *\nAllow: /\n",
                headers={"content-type": "text/plain"},
            )
        return mock_response(
            request, status=404, body="", headers={"content-type": "application/xml"}
        )

    crawler = make_crawler(handler)
    seed = crawler.prepare(ROOT)
    assert seed.robots_status == "available"
    assert seed.page_urls == [ROOT]
    assert "/sitemap.xml" in requested
    crawler.close()


def test_sitemap_queue_skips_duplicates_external_nested_maps_and_network_errors():
    def handler(request):
        if request.url.path == "/robots.txt":
            return mock_response(
                request,
                body=(
                    "User-agent: *\nAllow: /\n"
                    "Sitemap: https://example.com/nested.xml\n"
                    "Sitemap: https://example.com/bad.xml\n"
                    "Sitemap: https://example.com/bad.xml\n"
                    "Sitemap: https://example.com/error.xml\n"
                ),
                headers={"content-type": "text/plain"},
            )
        if request.url.path == "/nested.xml":
            body = (
                "<sitemapindex><sitemap><loc>https://elsewhere.example/child.xml</loc>"
                "</sitemap></sitemapindex>"
            )
            return mock_response(request, body=body, headers={"content-type": "application/xml"})
        if request.url.path == "/bad.xml":
            return mock_response(
                request, status=404, body="", headers={"content-type": "application/xml"}
            )
        if request.url.path == "/error.xml":
            raise httpx.ConnectError("offline", request=request)
        raise AssertionError(f"Unexpected fetch: {request.url}")

    crawler = make_crawler(handler)
    seed = crawler.prepare(ROOT)
    assert seed.sitemap_urls == ["https://example.com/nested.xml"]
    assert seed.page_urls == [ROOT]
    assert any("outside the submitted site" in note for note in seed.notes)
    assert any("returned HTTP 404" in note for note in seed.notes)
    assert any("Could not read sitemap" in note for note in seed.notes)
    crawler.close()


def test_prepare_obeys_disallow_and_does_not_fetch_disallowed_sitemap():
    requested = []

    def handler(request):
        requested.append(request.url.path)
        return mock_response(
            request,
            body="User-agent: *\nDisallow: /\nSitemap: https://example.com/sitemap.xml\n",
            headers={"content-type": "text/plain"},
        )

    crawler = make_crawler(handler)
    seed = crawler.prepare(ROOT)
    assert seed.robots_status == "available"
    assert seed.page_urls == []
    assert seed.sitemap_urls == []
    assert requested == ["/robots.txt"]
    assert any("disallowed" in note for note in seed.notes)
    with pytest.raises(CrawlError, match="disallowed"):
        crawler.inspect_page(ROOT)
    crawler.close()


def test_prepare_stops_safely_for_unavailable_robots_and_network_error():
    def unavailable(request):
        return mock_response(
            request, status=503, body="unavailable", headers={"content-type": "text/plain"}
        )

    crawler = make_crawler(unavailable)
    seed = crawler.prepare(ROOT)
    assert seed.robots_status == "unavailable"
    assert seed.page_urls == []
    assert any("crawl stopped safely" in note for note in seed.notes)
    crawler.close()

    def disconnected(request):
        raise httpx.ConnectError("offline", request=request)

    crawler = make_crawler(disconnected)
    seed = crawler.prepare(ROOT)
    assert seed.robots_status == "unavailable"
    assert seed.page_urls == []
    assert any("Could not read robots.txt" in note for note in seed.notes)
    crawler.close()


def test_sitemap_errors_and_rules_are_reported_without_crashing():
    sitemap_index = (
        "User-agent: *\nAllow: /\nDisallow: /blocked.xml\n"
        "Sitemap: https://other.example/index.xml\n"
        "Sitemap: https://example.com/bad.xml\nSitemap: https://example.com/missing.xml\n"
        "Sitemap: https://example.com/blocked.xml"
    )

    def handler(request):
        if request.url.path == "/robots.txt":
            return mock_response(
                request, body=sitemap_index, headers={"content-type": "text/plain"}
            )
        if request.url.path == "/bad.xml":
            return mock_response(
                request, status=200, body="<urlset>", headers={"content-type": "application/xml"}
            )
        return mock_response(
            request, status=404, body="missing", headers={"content-type": "application/xml"}
        )

    crawler = make_crawler(handler)
    seed = crawler.prepare(ROOT)
    assert seed.robots_status == "available"
    assert seed.sitemap_urls == []
    assert seed.page_urls == [ROOT]
    assert any("outside the submitted site" in note for note in seed.notes)
    assert any("malformed" in note for note in seed.notes)
    assert any("returned HTTP 404" in note for note in seed.notes)
    crawler.close()


def test_sitemap_parser_handles_namespaces_index_and_unsafe_xml():
    pages, nested = SiteCrawler._parse_sitemap(
        '<sitemapindex xmlns="urn:test"><sitemap><loc>https://example.com/a.xml</loc></sitemap></sitemapindex>'
    )
    assert pages == []
    assert nested == ["https://example.com/a.xml"]
    pages, nested = SiteCrawler._parse_sitemap(
        '<urlset xmlns="urn:test"><url><loc>https://example.com/</loc></url></urlset>'
    )
    assert pages == ["https://example.com/"]
    assert nested == []
    with pytest.raises(CrawlError, match="DTD or entity"):
        SiteCrawler._parse_sitemap('<!DOCTYPE x [<!ENTITY e "x">]><urlset/>')
    with pytest.raises(CrawlError, match="malformed"):
        SiteCrawler._parse_sitemap("not xml")


def test_fetch_follows_same_host_redirect_and_falls_back_for_unknown_charset():
    requests = []

    def handler(request):
        requests.append(str(request.url))
        if request.url.path == "/robots.txt":
            return mock_response(
                request,
                status=302,
                headers={"location": "https://example.com/robots-final.txt"},
            )
        if request.url.path == "/robots-final.txt":
            return mock_response(
                request, status=404, body="", headers={"content-type": "text/plain"}
            )
        return mock_response(
            request,
            body=b"<html><title>caf\xe9 page</title></html>",
            headers={"content-type": "text/html; charset=does-not-exist"},
        )

    crawler = make_crawler(handler)
    crawler.prepare("http://example.com/")
    page = crawler.inspect_page("http://example.com/hello")
    assert page.title == "caf� page"
    assert SiteCrawler._decode_body(b"word", "unknown-encoding") == "word"
    assert requests[:2] == ["http://example.com/robots.txt", "https://example.com/robots-final.txt"]
    crawler.close()


def test_fetch_rejects_offsite_redirect_and_redirect_limit():
    def offsite(request):
        if request.url.path == "/robots.txt":
            return mock_response(request, status=302, headers={"location": "https://evil.example/"})
        return mock_response(request)

    crawler = make_crawler(offsite)
    seed = crawler.prepare(ROOT)
    assert seed.robots_status == "unavailable"
    assert seed.page_urls == []
    assert any("submitted site" in note for note in seed.notes)
    crawler.close()

    def endless(request):
        return mock_response(request, status=302, headers={"location": "/again"})

    crawler = make_crawler(endless, max_redirects=1)
    with pytest.raises(CrawlError, match="redirect limit"):
        crawler._fetch(ROOT)
    crawler.close()


def test_fetch_defensive_redirect_fallback_and_inspect_without_prepare():
    crawler = make_crawler(lambda request: mock_response(request))
    crawler._max_redirects = -1
    with pytest.raises(CrawlError, match="redirect limit"):
        crawler._fetch(ROOT)
    crawler.close()

    crawler = make_crawler(
        lambda request: mock_response(
            request,
            body="<html><head><title>Direct page</title></head><body>Words</body></html>",
        )
    )
    page = crawler.inspect_page(ROOT)
    assert page.title == "Direct page"
    assert crawler._base_host == "example.com"
    assert crawler._base_port == 443
    crawler.close()


def test_fetch_handles_missing_redirect_location_size_limit_and_network_errors():
    def missing_location(request):
        return mock_response(request, status=302, headers={"content-type": "text/plain"})

    crawler = make_crawler(missing_location)
    result = crawler._fetch(ROOT)
    assert result.status_code == 302
    assert result.text == ""
    crawler.close()

    def oversized(request):
        return mock_response(request, body="x" * 1_100)

    crawler = make_crawler(oversized, max_response_bytes=1_024)
    with pytest.raises(CrawlError, match="size limit"):
        crawler._fetch(ROOT)
    crawler.close()

    def disconnected(request):
        raise httpx.ConnectError("offline", request=request)

    crawler = make_crawler(disconnected)
    with pytest.raises(CrawlError, match="could not be fetched"):
        crawler._fetch(ROOT)
    crawler.close()


def test_inspect_page_extracts_html_facts_and_links():
    html = """<!doctype html><html><head>
      <title>  An example title </title>
      <meta name="description" content="A page description">
      <meta name="robots" content="index,follow">
      <meta name="googlebot" content="max-image-preview:large">
      <link rel="canonical" href="/canonical">
      <script>ignored script words</script><style>ignored style words</style>
      </head><body><h1>Main</h1><h2>Sub heading</h2>
      <p>Visible words should be counted here.</p><img src="a.png" alt="A image">
      <img src="b.png" alt="  "><a href="/about">About</a>
      <a href="https://example.com/contact#section">Contact</a>
      <a href="https://elsewhere.example/path">External</a>
      <a href="mailto:a@example.com">Mail</a><a href="javascript:void(0)">JS</a>
      </body></html>"""

    def handler(request):
        if request.url.path == "/robots.txt":
            return mock_response(
                request,
                body="User-agent: *\nAllow: /\n",
                headers={"content-type": "text/plain"},
            )
        return mock_response(request, body=html)

    crawler = make_crawler(handler)
    crawler.prepare(ROOT)
    page = crawler.inspect_page(ROOT)
    assert page.title == "An example title"
    assert page.meta_description == "A page description"
    assert page.canonical_url == "https://example.com/canonical"
    assert page.robots_meta == "index,follow; max-image-preview:large"
    assert page.h1_count == 1
    assert page.headings == ["Main", "Sub heading"]
    assert page.word_count > 0
    assert page.images_total == 2
    assert page.images_missing_alt == 1
    assert page.internal_links == 2
    assert page.external_links == 1
    assert page.discovered_links == ["https://example.com/about", "https://example.com/contact"]
    crawler.close()


def test_inspect_page_non_html_http_status_and_bad_scope():
    def handler(request):
        if request.url.path == "/robots.txt":
            return mock_response(
                request, status=404, body="", headers={"content-type": "text/plain"}
            )
        if request.url.path == "/sitemap.xml":
            return mock_response(request, status=404, body="", headers={"content-type": "text/xml"})
        return mock_response(
            request,
            status=404,
            body="not html",
            headers={"content-type": "application/pdf"},
        )

    crawler = make_crawler(handler)
    crawler.prepare(ROOT)
    page = crawler.inspect_page("https://example.com/document.pdf")
    assert page.status_code == 404
    assert page.content_type == "application/pdf"
    assert page.title is None
    with pytest.raises(UnsafeTargetError, match="submitted site"):
        crawler.inspect_page("https://other.example/")
    crawler.close()


def test_in_scope_rejects_bad_schemes_and_bad_ports():
    crawler = SiteCrawler(resolver=public_resolver)
    assert not crawler._in_scope(ROOT)
    crawler._base_host = "example.com"
    crawler._base_port = 443
    assert crawler._in_scope("http://example.com/")
    assert not crawler._in_scope("ftp://example.com/")
    assert not crawler._in_scope("https://example.com:444/")
    assert not crawler._in_scope("https://user@example.com/")
    assert not crawler._in_scope("https://example.org/")
    assert not crawler._in_scope("https://example.com:bad/")
    crawler.close()
