"""Configuration and Pydantic request/response model tests."""

import pytest
from pydantic import SecretStr, ValidationError

from seo_ai_agent.config import Settings
from seo_ai_agent.llm import build_llm
from seo_ai_agent.models import (
    AuditRequest,
    Finding,
    HealthResponse,
    KeywordResearchRequest,
    PageSnapshot,
    ReportNarrative,
    SearchResult,
    SiteReport,
)


def test_settings_defaults_and_empty_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    settings = Settings(_env_file=None)
    assert settings.app_name == "SEO AI Agent"
    assert settings.openai_model == "gpt-4o-mini"
    assert settings.max_pages == 20
    assert not settings.llm_enabled
    assert build_llm(settings) is None


def test_settings_loads_aliases_and_secret(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "not-a-real-key")
    monkeypatch.setenv("OPENAI_MODEL", "local-model")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://127.0.0.1:11434/v1")
    settings = Settings(_env_file=None)
    assert settings.openai_api_key == SecretStr("not-a-real-key")
    assert settings.openai_model == "local-model"
    assert settings.llm_enabled


def test_settings_reject_invalid_limits():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, max_pages=21)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, request_timeout=0)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, max_response_bytes=100)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, max_redirects=-1)


def test_build_llm_passes_optional_base_url(monkeypatch):
    captured = {}

    class FakeChatOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr("seo_ai_agent.llm.ChatOpenAI", FakeChatOpenAI)
    settings = Settings(
        _env_file=None,
        openai_api_key=SecretStr("secret"),
        openai_model="test-model",
        openai_base_url="https://model.example/v1",
    )
    model = build_llm(settings)
    assert isinstance(model, FakeChatOpenAI)
    assert captured == {
        "model": "test-model",
        "api_key": "secret",
        "temperature": 0,
        "base_url": "https://model.example/v1",
    }


def test_build_llm_omits_empty_base_url(monkeypatch):
    captured = {}

    class FakeChatOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr("seo_ai_agent.llm.ChatOpenAI", FakeChatOpenAI)
    settings = Settings(_env_file=None, openai_api_key=SecretStr("secret"))
    build_llm(settings)
    assert "base_url" not in captured


def test_audit_request_normalizes_keyword_and_url():
    request = AuditRequest(url="https://example.com", keyword="  SEO advice  ")
    assert str(request.url) == "https://example.com/"
    assert request.keyword == "SEO advice"
    assert request.max_pages == 5


def test_audit_request_rejects_blank_keyword_extras_and_invalid_limits():
    assert AuditRequest(url="https://example.com", keyword=None).keyword is None
    with pytest.raises(ValidationError):
        AuditRequest(url="https://example.com", keyword="   ")
    with pytest.raises(ValidationError):
        AuditRequest(url="ftp://example.com")
    with pytest.raises(ValidationError):
        AuditRequest(url="https://example.com", surprise=True)
    with pytest.raises(ValidationError):
        AuditRequest(url="https://example.com", max_pages=0)


def test_keyword_request_normalizes_and_validates():
    request = KeywordResearchRequest(query="  marseille SEO  ", limit=3)
    assert request.query == "marseille SEO"
    assert request.limit == 3
    with pytest.raises(ValidationError):
        KeywordResearchRequest(query="   ")
    with pytest.raises(ValidationError):
        KeywordResearchRequest(query="x")
    with pytest.raises(ValidationError):
        KeywordResearchRequest(query="valid query", limit=11)


def test_output_models_validate_and_supply_defaults():
    page = PageSnapshot(
        url="https://example.com/",
        final_url="https://example.com/",
        status_code=200,
    )
    finding = Finding(
        severity="low",
        category="test",
        issue="Example",
        evidence="Observed",
        recommendation="Review",
    )
    report = SiteReport(target_url="https://example.com/", score=100, summary="All good")
    narrative = ReportNarrative(summary="A concise summary.")
    result = SearchResult(title="Title", url="https://example.com/result")
    health = HealthResponse(llm_enabled=False, version="test")
    assert page.headings == []
    assert page.discovered_links == []
    assert finding.url is None
    assert report.generated_at.tzinfo is not None
    assert report.priority_actions == []
    assert narrative.priority_actions == []
    assert result.snippet == ""
    assert health.status == "ok"
    with pytest.raises(ValidationError):
        ReportNarrative(summary="", priority_actions=["a", "b", "c", "d"])
