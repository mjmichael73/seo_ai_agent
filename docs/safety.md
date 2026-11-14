# Safety and operational notes

## Advisory-only behavior

The crawler uses only HTTP `GET` requests and does not send credentials, cookies, or site forms. It does not modify pages, server settings, redirects, files, or search-console properties. Recommendations must be reviewed by a site owner before implementation.

## URL and crawl controls

- Accept absolute HTTP(S) URLs only; reject URL userinfo, localhost/reserved hostnames, and hosts resolving to non-global IP addresses.
- Validate each redirect and keep redirects, sitemap URLs, and discovered page links on the submitted host (standard HTTP/HTTPS port transitions are allowed).
- Observe `robots.txt` before requesting content. A missing robots file means no declared restrictions; an unreadable robots file stops the crawl conservatively.
- Bound pages (maximum 20 by request and by server setting), redirects, response bytes, and network time. Crawl pages sequentially.
- This is defense in depth, not a substitute for deployment-level egress filtering. DNS rebinding and hostile upstream infrastructure require network controls in high-risk deployments.

## Secrets and deployment

- Keep `.env` local and supply secrets through a secret manager in production. Never include keys in reports, logs, source, or client-side code.
- The optional model key is only used server-side. The web client has no direct model-provider calls.
- The supplied Docker image uses a non-root user, drops Linux capabilities, disallows privilege escalation, and uses a read-only root filesystem with a temporary filesystem for scratch data.
- Do not expose the API publicly without appropriate authentication, rate limiting, request logging policy, and outbound network controls. The default API is intended for a trusted/private deployment.

## Data caveats

DuckDuckGo results are third-party public search snippets, may be incomplete, and are not search rankings, volume data, or a substitute for analytics. The technical score is a local prioritization heuristic and must not be presented as a Google score.
