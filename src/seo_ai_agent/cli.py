"""Typer command-line interface for audits, keyword research, and the web server."""

from __future__ import annotations

import json

import typer
import uvicorn

from seo_ai_agent.agent import create_agent
from seo_ai_agent.config import Settings
from seo_ai_agent.errors import AuditError
from seo_ai_agent.research import make_search_tool

app = typer.Typer(
    name="seo-agent",
    help="Run read-only, evidence-backed SEO audits and keyword research.",
    no_args_is_help=True,
)


def _settings() -> Settings:
    """Return settings lazily so CLI help does not initialize model clients."""

    return Settings()


@app.command("audit")
def audit_command(
    url: str = typer.Argument(..., help="Public HTTP(S) website URL to inspect."),
    max_pages: int = typer.Option(5, min=1, max=20, help="Maximum number of pages to inspect."),
    keyword: str | None = typer.Option(None, help="Optional keyword for free public web research."),
    json_output: bool = typer.Option(False, "--json", help="Print the complete report as JSON."),
) -> None:
    """Audit a public site and print advisory findings."""

    try:
        report = create_agent(_settings()).run(url, max_pages=max_pages, keyword=keyword)
    except (AuditError, ValueError) as exc:
        typer.echo(f"Audit failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    if json_output:
        typer.echo(report.model_dump_json(indent=2))
        return

    typer.echo(f"SEO advisory audit: {report.target_url}")
    typer.echo(f"Heuristic score (not a Google ranking): {report.score}/100")
    typer.echo(report.summary)
    typer.echo(f"Pages inspected: {len(report.pages)} | findings: {len(report.findings)}")
    if report.priority_actions:
        typer.echo("\nPriority actions:")
        for action in report.priority_actions:
            typer.echo(f"  - {action}")
    if report.findings:
        typer.echo("\nFindings:")
        for finding in report.findings:
            location = f" ({finding.url})" if finding.url else ""
            typer.echo(f"  [{finding.severity.upper()}] {finding.issue}{location}")
            typer.echo(f"    Evidence: {finding.evidence}")
            typer.echo(f"    Advice:   {finding.recommendation}")
    for note in report.notes:
        typer.echo(f"Note: {note}")


@app.command("keyword")
def keyword_command(
    query: str = typer.Argument(..., help="Keyword or phrase to research."),
    limit: int = typer.Option(5, min=1, max=10, help="Number of public search results."),
    json_output: bool = typer.Option(False, "--json", help="Print result objects as JSON."),
) -> None:
    """Fetch qualitative search context without paid SEO APIs."""

    try:
        results = make_search_tool(_settings().search_timeout).invoke(
            {"query": query, "max_results": limit}
        )
    except Exception as exc:
        typer.echo(f"Keyword research failed: {type(exc).__name__}: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    if json_output:
        typer.echo(json.dumps(results, ensure_ascii=False, indent=2))
        return
    if not results:
        typer.echo("No public search results were returned.")
        return
    for index, item in enumerate(results, start=1):
        typer.echo(f"{index}. {item['title']}\n   {item['url']}\n   {item['snippet']}\n")
    typer.echo("Search results are qualitative context, not rank-tracking metrics.")


@app.command("serve")
def serve_command(
    host: str = typer.Option("0.0.0.0", help="Interface to bind; use 0.0.0.0 in containers."),
    port: int = typer.Option(8000, min=1, max=65535, help="HTTP port."),
) -> None:
    """Serve the web UI and JSON API using Uvicorn."""

    uvicorn.run("seo_ai_agent.api:app", host=host, port=port, reload=False)


def main() -> None:
    """Console-script entry point."""

    app()


if __name__ == "__main__":  # pragma: no cover
    main()
