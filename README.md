# SEO AI Agent

An **advisory-only SEO agent** for bounded, read-only website audits. It is available as a command-line tool, a FastAPI JSON API, and a small browser UI. LangGraph orchestrates the crawl/research/analyze loop; LangChain tools perform page inspection and optional public keyword research.

> The agent only makes public `GET` requests. It never edits a website, submits forms, logs in, or changes search settings. Findings are evidence-backed suggestions, not guarantees or Google ranking signals.

## What it checks

- `robots.txt` and same-site XML sitemaps; respects `Disallow` rules before fetching pages.
- HTTP status and response type, title and description, canonical and robots meta directives, heading structure, visible text, image alt text, internal links, and response time.
- Optional keyword context from public DuckDuckGo results through the free `ddgs` library. This is qualitative research, **not** rank tracking or search-volume data.
- A heuristic 0–100 technical score and prioritized recommendations. No SEO score is an official search-engine metric.

The default workflow does not need an LLM key. Deterministic checks still run locally. If an OpenAI-compatible model is configured, LangChain adds a constrained summary using the collected evidence. A local or other OpenAI-compatible inference server can be used through `OPENAI_BASE_URL`.

## Quick start

### Python and CLI

Python **3.15** is used by the Docker image and CI. The package supports Python 3.11+ for local development.

```bash
python3.15 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'

# Audit one public website (defaults to five pages)
seo-agent audit https://example.com

# Include qualitative search context and/or emit machine-readable JSON
seo-agent audit https://example.com --max-pages 8 --keyword 'marseille bike repair'
seo-agent audit https://example.com --json
seo-agent keyword 'marseille bike repair' --limit 5

# Start the web UI and API
seo-agent serve --host 0.0.0.0 --port 8000
```

Open <http://localhost:8000>. The interactive API docs are at <http://localhost:8000/docs> and the liveness endpoint is `/healthz`.

### Docker Compose

```bash
cp .env.example .env       # optional; leave the model key blank for rule-based advice
# Edit .env only if you want an optional model or different resource limits.
docker compose up --build
```

Open <http://localhost:8000>. Stop with `docker compose down`.

### Docker without Compose

```bash
docker build -t seo-ai-agent .
docker run --rm -p 8000:8000 \
  -e OPENAI_API_KEY="${OPENAI_API_KEY:-}" \
  seo-ai-agent
```

The container runs as a non-root user with a read-only root filesystem and listens on `0.0.0.0:8000`.

## Configuration

Copy `.env.example` to `.env` for local use. **Never commit a real `.env` or API key.** Settings may also be passed as environment variables.

| Variable | Default | Purpose |
| --- | --- | --- |
| `OPENAI_API_KEY` | empty | Optional key for an OpenAI-compatible chat model. Without it, deterministic analysis is used. |
| `OPENAI_MODEL` | `gpt-4o-mini` | Model name used only when a key is configured. |
| `OPENAI_BASE_URL` | empty | Optional compatible endpoint (for example, a local inference server). |
| `REQUEST_TIMEOUT` | `8` seconds | Per-request crawl timeout. |
| `SEARCH_TIMEOUT` | `8` seconds | Public keyword-search timeout. |
| `MAX_PAGES` | `20` | Server-side hard cap; a request can ask for fewer pages. |
| `MAX_RESPONSE_BYTES` | `2000000` | Maximum response body read per URL. |
| `MAX_REDIRECTS` | `3` | Maximum safe redirect hops. |
| `WEB_PORT` | `8000` | Host port used by Docker Compose. |

## API

### `POST /api/audit`

```json
{
  "url": "https://example.com",
  "max_pages": 5,
  "keyword": "optional topic"
}
```

Returns a `SiteReport` containing page facts, prioritized findings, notes, and optional keyword results. `max_pages` must be between 1 and 20; the configured `MAX_PAGES` can impose a lower server cap.

### `POST /api/keyword-research`

```json
{
  "query": "marseille bike repair",
  "limit": 5
}
```

Returns public search snippets for qualitative research. Search availability and results are provided by DuckDuckGo and may vary.

Other endpoints: `GET /` (web app), `GET /healthz` (liveness), `GET /docs` (OpenAPI UI). Error responses are returned as JSON. The crawler rejects non-HTTP(S), private/reserved addresses, URL credentials, off-site redirects, and off-site sitemap targets as SSRF safeguards.

## Architecture

```text
CLI / browser UI / JSON API
             │
             ▼
        SeoAuditAgent
             │
             ▼
     bounded LangGraph loop
   prepare → inspect page ↺ → optional research → analyze → optional summary
             │                       │
      LangChain inspect tool    LangChain search tool
             │                       │
       HTTPX + BeautifulSoup   ddgs / DuckDuckGo
             └──────────────┬────────┘
                            ▼
         evidence-backed, advisory SiteReport
```

Each audit constructs its own crawler and graph. The crawl has a hard page limit, response size cap, timeout, redirect limit, same-site scope, and robots check. Deterministic checks are the source of findings; the optional model may only add a short narrative and a few actions. See [docs/architecture.md](docs/architecture.md) and [docs/safety.md](docs/safety.md).

## Development

```bash
make install
make lint
make test
make coverage   # requires 100% measured Python line coverage
```

Tests use mocked HTTP and search responses; they do not crawl live sites. The CI workflow uses Python 3.15, Ruff, and the full-coverage test command. See [AGENTS.md](AGENTS.md) for contributor conventions.

## Free libraries and data sources

- **LangGraph / LangChain Core**: tool-oriented workflow orchestration.
- **FastAPI / Uvicorn / Typer**: API, web serving, and CLI.
- **HTTPX, Beautiful Soup, lxml, `urllib.robotparser`**: public-page fetching, parsing, and crawl-rule handling.
- **`ddgs`**: optional no-key public web search for qualitative keyword context.

The agent does not claim access to Google Search Console, paid rank trackers, search volume, or private analytics. The website owner remains responsible for verifying each recommendation.
