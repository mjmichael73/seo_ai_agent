"""Typer CLI output and error path tests."""

import json

from typer.testing import CliRunner

from seo_ai_agent import cli
from seo_ai_agent.errors import AuditError
from seo_ai_agent.models import Finding, SiteReport

runner = CliRunner()


def report_with_findings():
    return SiteReport(
        target_url="https://example.com/",
        score=72,
        summary="An advisory summary.",
        priority_actions=["Add a title", "Review the page text"],
        findings=[
            Finding(
                severity="high",
                category="metadata",
                issue="Title is missing",
                evidence="No title found",
                recommendation="Add a useful title",
                url="https://example.com/",
            )
        ],
        notes=["Robots note"],
    )


class FakeAgent:
    def __init__(self, report=None, error=None):
        self.report = report or report_with_findings()
        self.error = error
        self.calls = []

    def run(self, url, max_pages=5, keyword=None):
        self.calls.append((url, max_pages, keyword))
        if self.error:
            raise self.error
        return self.report


def test_audit_cli_prints_human_report(monkeypatch):
    agent = FakeAgent()
    monkeypatch.setattr(cli, "create_agent", lambda settings: agent)
    result = runner.invoke(
        cli.app, ["audit", "https://example.com", "--max-pages", "4", "--keyword", "topic"]
    )
    assert result.exit_code == 0
    assert "Heuristic score (not a Google ranking): 72/100" in result.stdout
    assert "[HIGH] Title is missing" in result.stdout
    assert "Evidence: No title found" in result.stdout
    assert "Robots note" in result.stdout
    assert agent.calls == [("https://example.com", 4, "topic")]


def test_audit_cli_json_output(monkeypatch):
    agent = FakeAgent()
    monkeypatch.setattr(cli, "create_agent", lambda settings: agent)
    result = runner.invoke(cli.app, ["audit", "https://example.com", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["score"] == 72
    assert payload["findings"][0]["issue"] == "Title is missing"


def test_audit_cli_reports_agent_and_validation_errors(monkeypatch):
    monkeypatch.setattr(
        cli, "create_agent", lambda settings: FakeAgent(error=AuditError("blocked"))
    )
    failed = runner.invoke(cli.app, ["audit", "https://example.com"])
    assert failed.exit_code == 1
    assert "Audit failed: blocked" in failed.stderr
    monkeypatch.setattr(
        cli, "create_agent", lambda settings: FakeAgent(error=ValueError("bad limit"))
    )
    invalid = runner.invoke(cli.app, ["audit", "https://example.com"])
    assert invalid.exit_code == 1
    assert "bad limit" in invalid.stderr


def test_keyword_cli_prints_results_and_json(monkeypatch):
    class FakeTool:
        def invoke(self, inputs):
            return [{"title": "Top page", "url": "https://example.org/", "snippet": "Context"}]

    monkeypatch.setattr(cli, "make_search_tool", lambda timeout: FakeTool())
    human = runner.invoke(cli.app, ["keyword", "example topic"])
    assert human.exit_code == 0
    assert "Top page" in human.stdout
    assert "not rank-tracking" in human.stdout
    machine = runner.invoke(cli.app, ["keyword", "example topic", "--json"])
    assert json.loads(machine.stdout)[0]["url"] == "https://example.org/"


def test_keyword_cli_empty_and_error_paths(monkeypatch):
    class EmptyTool:
        def invoke(self, inputs):
            return []

    monkeypatch.setattr(cli, "make_search_tool", lambda timeout: EmptyTool())
    empty = runner.invoke(cli.app, ["keyword", "example topic"])
    assert empty.exit_code == 0
    assert "No public search results" in empty.stdout

    class BrokenTool:
        def invoke(self, inputs):
            raise RuntimeError("offline")

    monkeypatch.setattr(cli, "make_search_tool", lambda timeout: BrokenTool())
    failed = runner.invoke(cli.app, ["keyword", "example topic"])
    assert failed.exit_code == 1
    assert "Keyword research failed: RuntimeError: offline" in failed.stderr


def test_serve_cli_calls_uvicorn(monkeypatch):
    calls = []
    monkeypatch.setattr(cli.uvicorn, "run", lambda *args, **kwargs: calls.append((args, kwargs)))
    result = runner.invoke(cli.app, ["serve", "--host", "127.0.0.1", "--port", "9000"])
    assert result.exit_code == 0
    assert calls == [
        (("seo_ai_agent.api:app",), {"host": "127.0.0.1", "port": 9000, "reload": False})
    ]


def test_cli_main_invokes_typer(monkeypatch):
    called = []
    monkeypatch.setattr(cli, "app", lambda: called.append(True))
    cli.main()
    assert called == [True]
