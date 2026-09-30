# ulta_snapshot

Loader for one ulta.ae (UAE) snapshot, captured by the rung-5 runner under ADR-0006 Amendment 2.
It uses the same loader contract as `sephora_snapshot`.

- Input: `pdp/part-NNNN.jsonl.gz` page records `{at, url, lang, status, engine, egress, proxy_bytes, html, captures}`.
- Parser: the rendered DOM plus JSON-LD (`pi_connector_ulta.dom.parse_pdp_html`) is the primary path.
- The page-loaded `/graphql` JSON is merged only when `ULTA_USE_PAGE_JSON=1`. That flag stays off until the coordinator confirms it.
- Missing is data: variants other than the selected one get price `unknown`. Blocked or non-200 pages load nothing, so they are never marked out of stock.
- Replays are idempotent: each part is recorded in a ledger file, and offers use idempotency keys.

```
python -m ulta_snapshot.load <local-dir> <gs://bucket/prefix>            # load new parts
python -m ulta_snapshot.load <local-dir> <gs://bucket/prefix> --finish   # close the run
```
