"""Bounded public-site crawler and HTML evidence collector.

Only HTTP GET requests are issued. Private, loopback, link-local and reserved IP
addresses are rejected to reduce SSRF risk; redirects and sitemap links stay on
the submitted site. robots.txt rules are observed before page requests.
"""

from __future__ import annotations

import ipaddress
import re
import socket
import time
import xml.etree.ElementTree as ElementTree
from collections.abc import Callable
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup

from seo_ai_agent.errors import CrawlError, UnsafeTargetError
from seo_ai_agent.models import PageSnapshot

_REDIRECT_STATUSES = {301, 302, 303, 307, 308}
_BLOCKED_SUFFIXES = (".localhost", ".local", ".internal", ".test", ".invalid", ".onion")
_MAX_SITEMAPS = 5


@dataclass(frozen=True)
class FetchResult:
    """Limited response data from one final URL after safe redirects."""

    url: str
    status_code: int
    headers: dict[str, str]
    text: str
    elapsed_ms: int


@dataclass
class CrawlSeed:
    """Robots and sitemap information used to seed the graph's crawl loop."""

    robots_status: str
    sitemap_urls: list[str] = field(default_factory=list)
    page_urls: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


class SiteCrawler:
    """A synchronous, testable crawler for a small number of public pages."""

    def __init__(
        self,
        *,
        timeout_seconds: float = 8.0,
        max_response_bytes: int = 2_000_000,
        max_redirects: int = 3,
        user_agent: str = "SeoAIAgent/0.1 (+https://github.com/mjmichael73/seo_ai_agent)",
        transport: httpx.BaseTransport | None = None,
        resolver: Callable[..., list[tuple]] | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if max_response_bytes < 1_024:
            raise ValueError("max_response_bytes must be at least 1024")
        if max_redirects < 0:
            raise ValueError("max_redirects cannot be negative")
        self._timeout_seconds = timeout_seconds
        self._max_response_bytes = max_response_bytes
        self._max_redirects = max_redirects
        self._user_agent = user_agent
        self._resolver = resolver or socket.getaddrinfo
        self._client = httpx.Client(
            timeout=timeout_seconds,
            headers={"User-Agent": user_agent},
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        )
        self._base_host: str | None = None
        self._base_port: int | None = None
        self._robots: RobotFileParser | None = None

    def close(self) -> None:
        """Close the underlying HTTP client."""

        self._client.close()

    def _validate_public_url(self, url: str) -> tuple[str, int, str]:
        """Validate HTTP(S), reject credentials and non-public DNS/IP targets."""

        if not isinstance(url, str) or not url.strip():
            raise UnsafeTargetError("A non-empty public HTTP(S) URL is required.")
        try:
            parsed = urlsplit(url.strip())
            host = parsed.hostname
            explicit_port = parsed.port
        except ValueError as exc:
            raise UnsafeTargetError("The URL is malformed or has an invalid port.") from exc
        scheme = parsed.scheme.lower()
        if scheme not in {"http", "https"} or not parsed.netloc or not host:
            raise UnsafeTargetError("Only absolute HTTP and HTTPS URLs are supported.")
        if parsed.username is not None or parsed.password is not None:
            raise UnsafeTargetError("URLs containing usernames or passwords are not allowed.")

        normalized_host = host.rstrip(".").lower()
        if normalized_host == "localhost" or normalized_host.endswith(_BLOCKED_SUFFIXES):
            raise UnsafeTargetError("Local and reserved hostnames cannot be audited.")
        port = explicit_port or (443 if scheme == "https" else 80)
        try:
            addresses = [ipaddress.ip_address(normalized_host)]
        except ValueError:
            try:
                records = self._resolver(normalized_host, port, type=socket.SOCK_STREAM)
            except OSError as exc:
                raise CrawlError(
                    f"Could not resolve the requested host: {normalized_host}."
                ) from exc
            addresses = []
            for record in records:
                try:
                    address = record[4][0].split("%", 1)[0]
                    addresses.append(ipaddress.ip_address(address))
                except (IndexError, TypeError, ValueError):
                    continue
        if not addresses:
            raise CrawlError(
                f"The requested host did not resolve to an IP address: {normalized_host}."
            )
        if any(not address.is_global for address in addresses):
            raise UnsafeTargetError(
                "URLs resolving to private or non-public IP addresses are not allowed."
            )
        return scheme, port, normalized_host

    @staticmethod
    def _normalize_url(url: str) -> str:
        """Remove fragments and normalize an empty path for stable queue keys."""

        parsed = urlsplit(url.strip())
        return urlunsplit(
            (parsed.scheme.lower(), parsed.netloc, parsed.path or "/", parsed.query, "")
        )

    def _in_scope(self, url: str) -> bool:
        """Whether a URL stays on the submitted host and its standard HTTP(S) ports."""

        if self._base_host is None or self._base_port is None:
            return False
        try:
            parsed = urlsplit(url)
            candidate_port = parsed.port or (443 if parsed.scheme.lower() == "https" else 80)
        except ValueError:
            return False
        host = (parsed.hostname or "").rstrip(".").lower()
        if parsed.scheme.lower() not in {"http", "https"} or parsed.username or parsed.password:
            return False
        if host != self._base_host:
            return False
        return candidate_port == self._base_port or {
            candidate_port,
            self._base_port,
        }.issubset({80, 443})

    def _assert_in_scope(self, url: str) -> None:
        if not self._in_scope(url):
            raise UnsafeTargetError("The crawler is restricted to the submitted site.")

    def _fetch(
        self, url: str, *, accept: str = "text/html,application/xhtml+xml,*/*;q=0.1"
    ) -> FetchResult:
        """Fetch at most the configured bytes and manually validate every redirect."""

        current_url = self._normalize_url(url)
        started = time.perf_counter()
        for redirect_count in range(self._max_redirects + 1):
            self._validate_public_url(current_url)
            if self._base_host is not None:
                self._assert_in_scope(current_url)
            try:
                with self._client.stream(
                    "GET",
                    current_url,
                    headers={"Accept": accept},
                ) as response:
                    status_code = response.status_code
                    if status_code in _REDIRECT_STATUSES:
                        location = response.headers.get("location")
                        if not location:
                            return FetchResult(
                                url=current_url,
                                status_code=status_code,
                                headers=dict(response.headers),
                                text="",
                                elapsed_ms=round((time.perf_counter() - started) * 1000),
                            )
                        if redirect_count >= self._max_redirects:
                            raise CrawlError("The site exceeded the configured redirect limit.")
                        next_url = self._normalize_url(urljoin(current_url, location))
                        self._validate_public_url(next_url)
                        if self._base_host is not None:
                            self._assert_in_scope(next_url)
                        current_url = next_url
                        continue

                    content = bytearray()
                    for chunk in response.iter_bytes():
                        content.extend(chunk)
                        if len(content) > self._max_response_bytes:
                            raise CrawlError("The response exceeded the configured size limit.")
                    text = self._decode_body(bytes(content), response.encoding)
                    return FetchResult(
                        url=current_url,
                        status_code=status_code,
                        headers=dict(response.headers),
                        text=text,
                        elapsed_ms=round((time.perf_counter() - started) * 1000),
                    )
            except (UnsafeTargetError, CrawlError):
                raise
            except httpx.HTTPError as exc:
                raise CrawlError(
                    f"The public page could not be fetched ({type(exc).__name__})."
                ) from exc
        raise CrawlError("The site exceeded the configured redirect limit.")

    @staticmethod
    def _decode_body(content: bytes, encoding: str | None) -> str:
        """Decode response bytes, falling back to UTF-8 for unknown encodings."""

        try:
            return content.decode(encoding or "utf-8", errors="replace")
        except LookupError:
            return content.decode("utf-8", errors="replace")

    def _is_allowed(self, url: str) -> bool:
        """Consult parsed robots rules; no parser means there are no known restrictions."""

        return self._robots is None or self._robots.can_fetch(self._user_agent, url)

    @staticmethod
    def _parse_sitemap(text: str) -> tuple[list[str], list[str]]:
        """Return page URLs and nested sitemap URLs from a bounded XML document."""

        if re.search(r"<!\s*(?:DOCTYPE|ENTITY)\b", text, re.IGNORECASE):
            raise CrawlError("Sitemaps containing DTD or entity declarations are not accepted.")
        try:
            root = ElementTree.fromstring(text)
        except ElementTree.ParseError as exc:
            raise CrawlError("The sitemap XML is malformed.") from exc
        root_name = root.tag.rsplit("}", 1)[-1].lower()
        locations = [
            (element.text or "").strip()
            for element in root.iter()
            if element.tag.rsplit("}", 1)[-1].lower() == "loc" and (element.text or "").strip()
        ]
        if root_name == "sitemapindex":
            return [], locations
        return locations, []

    def _read_sitemaps(
        self, candidates: list[str], notes: list[str]
    ) -> tuple[list[str], list[str]]:
        """Read at most five same-site sitemaps and return their page locations."""

        queued = list(candidates)
        seen: set[str] = set()
        successful: list[str] = []
        page_urls: list[str] = []
        while queued and len(seen) < _MAX_SITEMAPS:
            sitemap_url = self._normalize_url(queued.pop(0))
            if sitemap_url in seen:
                continue
            seen.add(sitemap_url)
            if not self._in_scope(sitemap_url):
                notes.append(f"Skipped sitemap outside the submitted site: {sitemap_url}")
                continue
            if not self._is_allowed(sitemap_url):
                notes.append("Skipped a sitemap disallowed by robots.txt.")
                continue
            try:
                response = self._fetch(sitemap_url, accept="application/xml,text/xml,*/*;q=0.1")
            except (CrawlError, UnsafeTargetError) as exc:
                notes.append(f"Could not read sitemap {sitemap_url}: {exc}")
                continue
            if not 200 <= response.status_code < 300:
                notes.append(f"Sitemap {sitemap_url} returned HTTP {response.status_code}.")
                continue
            try:
                locations, nested_sitemaps = self._parse_sitemap(response.text)
            except CrawlError as exc:
                notes.append(f"Could not parse sitemap {sitemap_url}: {exc}")
                continue
            successful.append(sitemap_url)
            queued.extend(nested_sitemaps)
            for location in locations:
                candidate = self._normalize_url(urljoin(sitemap_url, location))
                if (
                    self._in_scope(candidate)
                    and self._is_allowed(candidate)
                    and candidate not in page_urls
                ):
                    page_urls.append(candidate)
        return successful, page_urls

    def prepare(self, target_url: str) -> CrawlSeed:
        """Read robots.txt and same-site sitemaps to seed the bounded crawl."""

        target = self._normalize_url(target_url)
        scheme, port, host = self._validate_public_url(target)
        self._base_host = host
        self._base_port = port
        self._robots = None
        parsed_target = urlsplit(target)
        origin = f"{scheme}://{parsed_target.netloc}"
        robots_url = urljoin(f"{origin}/", "robots.txt")
        notes: list[str] = []
        robots_status = "unavailable"
        sitemap_candidates: list[str] = []
        try:
            robots_response = self._fetch(robots_url, accept="text/plain,*/*;q=0.1")
            if robots_response.status_code == 404:
                robots_status = "not_found"
                notes.append("No robots.txt was found; pages are treated as allowed.")
            elif 200 <= robots_response.status_code < 300:
                robots_status = "available"
                parser = RobotFileParser()
                parser.set_url(robots_response.url)
                parser.parse(robots_response.text.splitlines())
                self._robots = parser
                for line in robots_response.text.splitlines():
                    if line.strip().lower().startswith("sitemap:"):
                        candidate = self._normalize_url(line.split(":", 1)[1].strip())
                        if self._in_scope(candidate):
                            sitemap_candidates.append(candidate)
                        else:
                            notes.append(f"Skipped sitemap outside the submitted site: {candidate}")
            else:
                notes.append(
                    f"robots.txt returned HTTP {robots_response.status_code}; crawl stopped safely."
                )
        except (CrawlError, UnsafeTargetError) as exc:
            notes.append(f"Could not read robots.txt; crawl stopped safely: {exc}")

        sitemap_urls: list[str] = []
        sitemap_pages: list[str] = []
        if robots_status in {"available", "not_found"} and not sitemap_candidates:
            sitemap_candidates.append(urljoin(f"{origin}/", "sitemap.xml"))
        if robots_status in {"available", "not_found"}:
            sitemap_urls, sitemap_pages = self._read_sitemaps(sitemap_candidates, notes)

        page_urls: list[str] = []
        if robots_status in {"available", "not_found"} and self._is_allowed(target):
            page_urls.append(target)
        elif robots_status in {"available", "not_found"}:
            notes.append("The submitted URL is disallowed by robots.txt and was not fetched.")
        for candidate in sitemap_pages:
            if candidate not in page_urls:
                page_urls.append(candidate)
        return CrawlSeed(
            robots_status=robots_status,
            sitemap_urls=sitemap_urls,
            page_urls=page_urls,
            notes=notes,
        )

    def inspect_page(self, url: str) -> PageSnapshot:
        """Fetch and extract visible on-page metadata and internal link candidates."""

        normalized_url = self._normalize_url(url)
        if self._base_host is None:
            scheme, port, host = self._validate_public_url(normalized_url)
            self._base_host = host
            self._base_port = port
            self._robots = None
        self._assert_in_scope(normalized_url)
        if not self._is_allowed(normalized_url):
            raise CrawlError("The requested page is disallowed by robots.txt.")
        response = self._fetch(normalized_url)
        content_type = (
            response.headers.get("content-type", "").split(";", 1)[0].strip().lower() or None
        )
        soup = (
            BeautifulSoup(response.text, "lxml")
            if content_type in {"text/html", "application/xhtml+xml"}
            else None
        )
        if soup is None:
            return PageSnapshot(
                url=normalized_url,
                final_url=response.url,
                status_code=response.status_code,
                content_type=content_type,
                load_time_ms=response.elapsed_ms,
            )

        for element in soup(["script", "style", "noscript", "template"]):
            element.decompose()
        title_node = soup.find("title")
        title = title_node.get_text(" ", strip=True) if title_node else None
        description = None
        robots_values: list[str] = []
        for meta in soup.find_all("meta"):
            name = str(meta.get("name") or "").strip().lower()
            content = str(meta.get("content") or "").strip()
            if name == "description" and description is None:
                description = content
            if name in {"robots", "googlebot"} and content:
                robots_values.append(content)
        canonical_url = None
        for link in soup.find_all("link", href=True):
            rel = link.get("rel", [])
            rel_tokens = rel.split() if isinstance(rel, str) else rel
            if any(str(token).lower() == "canonical" for token in rel_tokens):
                canonical_url = urljoin(response.url, str(link["href"]))
                break

        headings = [
            heading.get_text(" ", strip=True) for heading in soup.find_all(["h1", "h2", "h3"])
        ]
        visible_text = soup.get_text(" ", strip=True)
        word_count = len(re.findall(r"\b[\w’'-]+\b", visible_text))
        images = soup.find_all("img")
        images_missing_alt = sum(1 for image in images if not str(image.get("alt") or "").strip())
        internal_links: set[str] = set()
        external_links: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            href = str(anchor["href"]).strip()
            candidate = self._normalize_url(urljoin(response.url, href))
            parsed_candidate = urlsplit(candidate)
            if parsed_candidate.scheme.lower() not in {"http", "https"}:
                continue
            if self._in_scope(candidate):
                internal_links.add(candidate)
            else:
                external_links.add(candidate)

        return PageSnapshot(
            url=normalized_url,
            final_url=response.url,
            status_code=response.status_code,
            content_type=content_type,
            title=title,
            meta_description=description,
            canonical_url=canonical_url,
            robots_meta="; ".join(robots_values) or None,
            headings=headings,
            h1_count=sum(1 for heading in soup.find_all("h1")),
            word_count=word_count,
            images_total=len(images),
            images_missing_alt=images_missing_alt,
            internal_links=len(internal_links),
            external_links=len(external_links),
            discovered_links=sorted(internal_links),
            load_time_ms=response.elapsed_ms,
        )
