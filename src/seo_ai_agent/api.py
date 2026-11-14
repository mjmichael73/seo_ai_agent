"""FastAPI web application exposing the advisory SEO agent."""

from functools import lru_cache
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from seo_ai_agent import __version__
from seo_ai_agent.agent import SeoAuditAgent, create_agent
from seo_ai_agent.config import Settings
from seo_ai_agent.errors import AuditError, UnsafeTargetError
from seo_ai_agent.models import (
    AuditRequest,
    HealthResponse,
    KeywordResearchRequest,
    SearchResult,
    SiteReport,
)
from seo_ai_agent.research import make_search_tool, normalize_search_results

PACKAGE_DIR = Path(__file__).resolve().parent


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load process settings once for the API lifetime."""

    return Settings()


@lru_cache(maxsize=1)
def get_agent() -> SeoAuditAgent:
    """Create a single stateless agent factory; each run gets its own crawler and graph."""

    return create_agent(get_settings())


app = FastAPI(
    title="SEO AI Agent",
    description="A read-only, evidence-based SEO audit assistant.",
    version=__version__,
)
app.mount("/static", StaticFiles(directory=PACKAGE_DIR / "static"), name="static")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    """Serve the single-page browser interface."""

    return FileResponse(PACKAGE_DIR / "templates" / "index.html", media_type="text/html")


@app.get("/healthz", response_model=HealthResponse, tags=["system"])
def health(settings: Annotated[Settings, Depends(get_settings)]) -> HealthResponse:
    """Return liveness and whether an optional model key is configured."""

    return HealthResponse(llm_enabled=settings.llm_enabled, version=__version__)


@app.post("/api/audit", response_model=SiteReport, tags=["audit"])
async def run_audit(
    request: AuditRequest,
    agent: Annotated[SeoAuditAgent, Depends(get_agent)],
) -> SiteReport:
    """Run a bounded public-site audit. The service never applies recommendations."""

    try:
        return await run_in_threadpool(
            agent.run,
            str(request.url),
            max_pages=request.max_pages,
            keyword=request.keyword,
        )
    except UnsafeTargetError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except AuditError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/keyword-research", response_model=list[SearchResult], tags=["research"])
async def keyword_research(
    request: KeywordResearchRequest,
    settings: Annotated[Settings, Depends(get_settings)],
) -> list[SearchResult]:
    """Return qualitative public search results; no API key or ranking data is used."""

    try:
        search_tool = make_search_tool(settings.search_timeout)
        raw_results = await run_in_threadpool(
            search_tool.invoke,
            {"query": request.query, "max_results": request.limit},
        )
        return [SearchResult.model_validate(item) for item in normalize_search_results(raw_results)]
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail="Public keyword research is temporarily unavailable.",
        ) from exc
