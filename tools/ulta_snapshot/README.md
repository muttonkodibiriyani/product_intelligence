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
`projects/productintelligence-beeb3/secrets/pi-proxy-iproyal-ae/versions/1`.
There is no runtime fallback to the newest enabled version, and the job never calls
`versions.list`. When the credential is rotated, update this pin and the one in
`docs/runbooks/ulta-proxy-test.md` together. A disabled or destroyed version fails before any
request with `secret version not accessible (disabled/destroyed?) — pin an enabled version`.
