# Operations

## Configuration and startup

For local development, copy `.env.example` to `.env` if you need to set optional settings, then run `seo-agent serve` or `docker compose up --build`. Keep secrets out of source control. `GET /healthz` reports liveness and only a boolean model-enabled state.

## Resource defaults

- Request/search timeout: 8 seconds each.
- Response body limit: 2,000,000 bytes per URL.
- Redirect hops: 3.
- Page budget: 20 maximum; an individual audit defaults to 5.
- Search results: 1–10, with 5 used by an audit.

Set `REQUEST_TIMEOUT`, `SEARCH_TIMEOUT`, `MAX_RESPONSE_BYTES`, `MAX_REDIRECTS`, and `MAX_PAGES` in the environment to tune these bounds. `MAX_PAGES` is a server-side cap, not a request to crawl that many pages.

## Troubleshooting

- **No pages inspected:** inspect the audit URL, robots.txt rules, DNS, and public reachability. A non-public URL is intentionally rejected.
- **Keyword research unavailable:** DuckDuckGo may block or rate-limit automated requests; retry later. The technical audit still completes.
- **Model synthesis unavailable:** the deterministic report remains valid; check the server-side OpenAI-compatible key/model/base URL.
- **Container port conflict:** set `WEB_PORT` in `.env`, for example `WEB_PORT=8080`.

## Maintenance

Run `make lint`, `make test`, and `make coverage` before shipping. Tests must remain network-independent. Review dependency updates and rerun the complete suite after changes.
