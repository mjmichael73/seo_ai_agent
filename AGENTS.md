# Agent and contributor guidance

## Product contract

This is a **read-only, advisory SEO assistant**. It may fetch public HTTP(S) pages and report what it observed. Never add website mutation, form submission, authentication bypass, login/session handling, or automated deployment behavior. Do not claim that heuristics represent Google rankings or guarantee traffic gains.

## Architecture

- Keep interfaces thin: Typer CLI (`src/seo_ai_agent/cli.py`), FastAPI app (`api.py`), and static browser UI call the shared `SeoAuditAgent`.
- Orchestrate work with LangGraph. Page inspection and optional public search are LangChain tools. Keep graph state per audit; do not share crawler clients or mutable state between requests.
- The deterministic analyzer is the source of all reported findings. Optional model output may summarize supplied evidence, but must not invent evidence or apply changes.
- Keep external integrations replaceable/injectable so tests can mock them.

## Safety and resource limits

- Only make `GET` requests; follow robots.txt, stay on the submitted host, and validate every URL/redirect before fetching.
- Never permit private, loopback, link-local, reserved, credential-bearing, or non-HTTP(S) target URLs. Do not expand crawl scope to links on other hosts.
- Preserve hard limits for page count, request timeout, response bytes, redirect hops, and keyword-result count. Handle network failures as report notes where possible.
- Treat HTML, metadata, snippets, and model output as untrusted. Render them as text, never interpolated HTML. Do not log or expose API keys.
- Keep `.env` out of Git; update `.env.example` when adding settings.

## Code quality

- Use type hints, small functions, explicit models, and Python 3.11+ compatible syntax. Docker and CI target Python 3.15.
- Format and lint with Ruff. Keep dependency declarations in `pyproject.toml` and use compatible version ranges.
- Every behavior change needs tests. Network tests should use `httpx.MockTransport` or injected fakes—never depend on live domains or DuckDuckGo.
- Keep full Python line coverage at 100%: `make coverage` must pass.
- Update README/docs when user-facing commands, API shapes, safeguards, or configuration change.

## Useful commands

```bash
make install
make lint
make test
make coverage
make web
make docker-up
```
