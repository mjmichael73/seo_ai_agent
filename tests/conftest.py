"""Shared offline fixtures for all test modules."""

import socket

import httpx
import pytest

PUBLIC_IP = "93.184.216.34"


def public_resolver(host: str, port: int, **kwargs: object) -> list[tuple]:
    """Resolve all test hostnames to a reserved test-independent public address."""

    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (PUBLIC_IP, port))]


def mock_response(
    request: httpx.Request,
    *,
    status: int = 200,
    body: str | bytes = "",
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    """Construct an HTTPX response attached to the mocked request."""

    response_headers = headers or {"content-type": "text/html; charset=utf-8"}
    return httpx.Response(status, content=body, headers=response_headers, request=request)


@pytest.fixture
def public_resolver_fixture():
    """Expose a stable public DNS resolver to crawler tests."""

    return public_resolver
