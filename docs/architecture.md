# Architecture

## Request lifecycle

Each audit is isolated. The API runs the synchronous crawler in a worker thread; the CLI runs it directly. Both use the same `SeoAuditAgent` and response models.

1. **Prepare** — validate the requested public URL, fetch robots.txt, parse same-site sitemap locations, filter URLs by scope and robots policy.
2. **Crawl loop** — LangGraph takes one pending URL at a time. A LangChain `inspect_page` tool uses the crawler to collect status, response type, metadata, headings, visible word count, image alt coverage, links, and elapsed time. Same-site links may be queued, but the page budget is a hard ceiling.
3. **Optional research** — when a keyword is supplied, a LangChain search tool asks the free `ddgs` library for a small set of public DuckDuckGo results. Search failures become notes rather than audit failures.
4. **Analyze** — deterministic rules map facts to findings, recommendations, and a heuristic score. A score is not an external ranking metric.
5. **Optional synthesis** — if an OpenAI-compatible key is configured, LangChain asks the model for a constrained summary of existing findings. It cannot edit the site; model failure does not discard deterministic results.

## Components

- `crawler.py`: SSRF checks, robots/sitemap handling, bounded HTTP fetches, HTML parsing.
- `crawler_tools.py`: LangChain wrappers around safe crawler operations.
- `agent.py`: per-audit LangGraph and loop control.
- `analysis.py`: deterministic checks and report prioritization.
- `research.py`: no-key qualitative search tool.
- `api.py`, `cli.py`, `static/`: web, API, and command-line entry points.
- `models.py`: Pydantic request, evidence, and response types.

## Boundaries

The agent does not use authenticated analytics, Google Search Console, paid APIs, or persistent browser state. External content is untrusted input. The UI uses `textContent`, and optional LLM prompts explicitly treat supplied page evidence as data rather than instructions. There is no database; reports live only in the current CLI/API response.
