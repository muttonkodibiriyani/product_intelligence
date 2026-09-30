# pi_fetch: runbook

The polite fetch layer (ADR-0003 as amended by ADR-0006). Connectors never fetch; the runner
calls `pi_fetch.ladder.Fetcher`.

## robots.txt

- Read once per host before its first request, paced like any other request, over the same
  egress.
- Matched per RFC 9309: `*` wildcards, a `$` end anchor, merged user-agent groups, the longest
  match wins, Allow wins ties. Paths and patterns are percent-encoding normalised (UTF-8,
  upper-case hex). A UTF-8 BOM is stripped. Groups are chosen by the product token of our
  User-Agent (`Mozilla`), or `FetchPolicy.robots_agent` when set, else `*`. A group that has only an empty `Disallow:` falls back to `*`
  (fails closed).
- Mode per source, set in `FetchPolicy.robots_modes`:
  - `obey` is the default.
  - `tag_only` records the tag but fetches anyway. It is only for Sephora (ADR-0005). Never set it
    for another source without an ADR.
- In `obey` mode, the robots.txt fetch status decides what happens:

  | robots.txt response | Effect on the host's URLs |
  |---|---|
  | 2xx text | Rules applied; a disallowed URL raises `RobotsRefusedError` and nothing is sent |
  | 2xx HTML page | **All refused**: treated as unreadable (a soft 404, block or challenge page) |
  | 404 / 410 | No robots.txt: all allowed (RFC 9309) |
  | 401 / 403 / 429 | **All refused.** Stricter than the RFC: we are blocked or throttled and stop |
  | Any other 4xx (400, 418, ...) | **All refused.** Stricter than the RFC (fail closed) |
  | 5xx or unreachable | **All refused** |

- The runner records a refused URL as `not_observed`, never as out of stock or removed.
- If a whole host is refused because its robots.txt answered 401/403/429/5xx, report it as a
  blocked source. Do not switch transport, engine or egress to read robots.txt some other way
  unless the coordinator or owner decides so explicitly.

## Blocks and rate limits

`BlockVerdict.kind` is one of three values:

- `challenge`: a challenge page or header, at any status.
- `blocked`: a 401/403, a vendor-hinted 503, or an empty payload.
- `rate_limited`: a 429 without a challenge.

Only `challenge` and `blocked` mark a source blocked (`BlockVerdict.marks_source_blocked`). That
feeds the Proxy Decision Report and the API-route refusal. A 429 backs the host off: 60 s,
doubling, honouring `Retry-After`, capped at 1 h with a `backoff_capped` warning. Nothing is
ever solved or retried.
