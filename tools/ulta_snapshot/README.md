# ulta_snapshot

Loader for one ulta.ae (UAE) snapshot, captured by the rung-5 runner under ADR-0006 Amendment 2.
It uses the same loader contract as `sephora_snapshot`.

- Input: `pdp/part-NNNN.jsonl.gz` page records `{at, url, lang, status, engine, egress, proxy_bytes, html, captures}`.
- Parser: the rendered DOM plus JSON-LD (`pi_connector_ulta.dom.parse_pdp_html`) is the primary path.
- The page-loaded JSON is merged only when `ULTA_USE_PAGE_JSON=1` is set, which the coordinator approved on 2026-09-30. It is read only from captures whose https ulta.ae URL passes the snapshot's `robots.txt`, with status 200. `Disallow: /*?` refuses `GET /graphql?query=`. If the snapshot has no robots.txt, no captures are read. Refused captures are never parsed, hashed or stored.
- If the DOM swatches contradict the JSON-LD offer (a degraded render), stock is recorded as `not_observed`, never out of stock.
- `progress.json` counts are kept per language (`{"en": {...}, "ar": {...}}`), and `--finish` closes each language's run with its own counts.
- Missing is data: variants other than the selected one get price `unknown`. Blocked or non-200 pages load nothing, so they are never marked out of stock.
- Replays are idempotent: each part is recorded in a ledger file, and offers use idempotency keys.

```
python -m ulta_snapshot.load <local-dir> <gs://bucket/prefix>            # load new parts
python -m ulta_snapshot.load <local-dir> <gs://bucket/prefix> --finish   # close the run
```

## Proxy secret version

`SECRET_RESOURCE` is pinned to an explicit version:
`projects/productintelligence-beeb3/secrets/pi-proxy-iproyal-ae/versions/4`
(the current credential; `latest` is also accepted but not used).
There is no runtime fallback to the newest enabled version, and the job never calls
`versions.list`. When the credential is rotated, update this pin and the one in
`docs/runbooks/ulta-proxy-test.md` together. A disabled or destroyed version fails before any
request with `secret version not accessible (disabled/destroyed?) — pin an enabled version`.

### Secret JSON schema

The secret payload is one JSON object with **exactly these five keys** (placeholders shown,
never put real values in the repo or a chat):

```json
{
  "host": "PROXY_HOST",
  "port": 12345,
  "username": "PROXY_USERNAME",
  "password": "PROXY_PASSWORD_WITH_COUNTRY_SUFFIX",
  "provider": "iproyal"
}
```

| Key | Type | Rule |
|---|---|---|
| `host` | string | not empty; the proxy host name only, no `http://` and no port |
| `port` | integer | 1-65535 |
| `username` | string | the proxy login |
| `password` | string | the proxy password **including the country-targeting suffix** exactly as the IPRoyal dashboard generates it for AE. Country targeting lives only here. |
| `provider` | string | not empty, e.g. `iproyal` |

Any other key (for example `country`) is rejected. The run then ends at once, before any request,
with `status=stopped_error proxy_bytes=0 challenge=no` and
`detail=` containing `not valid proxy credentials (fields: ['country'])`. The error names only the
offending field names, never a value. Fix the secret by adding a new version, then pin that version
(runbook: `docs/runbooks/ulta-proxy-test.md`).
