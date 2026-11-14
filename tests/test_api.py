"""FastAPI endpoint and browser asset tests with dependency overrides."""

from fastapi.testclient import TestClient

from seo_ai_agent import api
from seo_ai_agent.config import Settings
from seo_ai_agent.errors import AuditError, UnsafeTargetError
from seo_ai_agent.models import SiteReport


class FakeAgent:
    def __init__(self, error=None):
        self.error = error
        self.calls = []

    def run(self, url, max_pages=5, keyword=None):
        self.calls.append((url, max_pages, keyword))
        if self.error:
            raise self.error
        return SiteReport(
            target_url=url,
            score=88,
            summary="Evidence-backed test report",
            keyword=keyword,
        )


class FakeTool:
    def __init__(self, result=None, error=None):
        self.result = result or []
        self.error = error
        self.calls = []

    def invoke(self, inputs):
        self.calls.append(inputs)
        if self.error:
            raise self.error
        return self.result


def make_client(agent=None, settings=None):
    api.get_settings.cache_clear()
    api.get_agent.cache_clear()
    api.app.dependency_overrides.clear()
    api.app.dependency_overrides[api.get_settings] = lambda: settings or Settings(_env_file=None)
    if agent is not None:
        api.app.dependency_overrides[api.get_agent] = lambda: agent
    return TestClient(api.app)


def test_index_static_and_health_endpoints():
    client = make_client()
    index = client.get("/")
    css = client.get("/static/app.css")
    health = client.get("/healthz")
    assert index.status_code == 200
    assert "Evidence first" in index.text
    assert css.status_code == 200
    assert "--green" in css.text
    assert health.json() == {"status": "ok", "llm_enabled": False, "version": "0.1.0"}
    client.close()
    api.app.dependency_overrides.clear()


def test_health_reflects_model_configuration_without_exposing_key():
    settings = Settings(_env_file=None, openai_api_key="secret-value")
    client = make_client(settings=settings)
    response = client.get("/healthz")
    assert response.json()["llm_enabled"] is True
    assert "secret-value" not in response.text
    client.close()
    api.app.dependency_overrides.clear()


def test_audit_endpoint_returns_report_and_passes_parameters():
    agent = FakeAgent()
    client = make_client(agent)
    response = client.post(
        "/api/audit",
        json={"url": "https://example.com", "max_pages": 3, "keyword": " topic "},
    )
    assert response.status_code == 200
    assert response.json()["score"] == 88
    assert response.json()["keyword"] == "topic"
    assert agent.calls == [("https://example.com/", 3, "topic")]
    client.close()
    api.app.dependency_overrides.clear()


def test_audit_endpoint_maps_safe_url_and_network_errors():
    for error, expected in (
        (UnsafeTargetError("private host"), 400),
        (AuditError("site unavailable"), 502),
    ):
        client = make_client(FakeAgent(error=error))
        response = client.post("/api/audit", json={"url": "https://example.com"})
        assert response.status_code == expected
        assert response.json()["detail"] == str(error)
        client.close()
        api.app.dependency_overrides.clear()


def test_audit_endpoint_validates_request_shape():
    client = make_client(FakeAgent())
    bad_url = client.post("/api/audit", json={"url": "file:///etc/passwd"})
    bad_pages = client.post("/api/audit", json={"url": "https://example.com", "max_pages": 21})
    assert bad_url.status_code == 422
    assert bad_pages.status_code == 422
    client.close()
    api.app.dependency_overrides.clear()


def test_keyword_endpoint_returns_results(monkeypatch):
    tool = FakeTool(
        result=[{"title": "A result", "url": "https://example.org/", "snippet": "Search context"}]
    )
    monkeypatch.setattr(api, "make_search_tool", lambda timeout: tool)
    client = make_client()
    response = client.post("/api/keyword-research", json={"query": " useful query ", "limit": 1})
    assert response.status_code == 200
    assert response.json() == [
        {"title": "A result", "url": "https://example.org/", "snippet": "Search context"}
    ]
    assert tool.calls == [{"query": "useful query", "max_results": 1}]
    client.close()
    api.app.dependency_overrides.clear()


def test_keyword_endpoint_filters_invalid_results_and_maps_failures(monkeypatch):
    monkeypatch.setattr(
        api, "make_search_tool", lambda timeout: FakeTool(result=["bad", {"title": "No URL"}])
    )
    client = make_client()
    assert client.post("/api/keyword-research", json={"query": "query"}).json() == []
    client.close()
    api.app.dependency_overrides.clear()

    monkeypatch.setattr(
        api, "make_search_tool", lambda timeout: FakeTool(error=RuntimeError("offline"))
    )
    client = make_client()
    response = client.post("/api/keyword-research", json={"query": "query"})
    assert response.status_code == 502
    assert response.json()["detail"] == "Public keyword research is temporarily unavailable."
    client.close()
    api.app.dependency_overrides.clear()


def test_get_settings_and_agent_factories(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    api.get_settings.cache_clear()
    api.get_agent.cache_clear()
    settings = api.get_settings()
    agent = api.get_agent()
    assert isinstance(settings, Settings)
    assert agent.settings is settings
    api.get_settings.cache_clear()
    api.get_agent.cache_clear()
