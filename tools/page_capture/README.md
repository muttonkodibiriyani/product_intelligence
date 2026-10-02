# page_capture — plan-driven raw page and picture capture

Cloud Run job (also runs locally) that fetches the URLs of a **plan**, keeps every body exactly as
served, downloads the product pictures the plan names, and writes everything to GCS under the
ADR-0006 raw-capture rules. Standalone: `httpx` + `google-cloud-storage` + `defusedxml`, no
`pi_fetch`, no browser, no TLS impersonation. Direct by default; the owner-capped residential
proxy can be switched on for named page hosts only, under the rules in "Proxy rules" below.
Pictures are always fetched directly.

Ordinary-access rules the job enforces itself:

- `robots.txt` of every host (page hosts and image hosts alike) is read once, through the same
  client and User-Agent, before the host's first request. RFC 9309 matching (`*`, `$`, longest
  match wins, `Allow` wins a tie, the group is picked by UA product token, else `*`).
  404/410 → nothing restricted. Any other non-200, a transport error, or a 200 that is really an
  HTML page → robots **unavailable** and every URL on that host is refused (`robots_unavailable`).
  `Crawl-delay` is honoured when it is larger than the pace.
- One paced GET per URL (per host, uniform jitter up to 60 %), fresh cookie jar every request,
  30 s timeout, **no retries**.
- Redirects are followed one hop at a time, at most 5. Every hop is a new request to its host:
  the target host's `robots.txt` is read (fail-closed) and the target path checked, a stopped
  host is not entered, the hop is paced on the target host, and it uses the target host's own
  route (direct unless that host is itself in `PROXY_HOSTS`). A refused hop is recorded with the
  target as `final_url` and the state `robots_disallowed`, `robots_unavailable` or
  `skipped_host_stopped`; `redirects` carries the hop count. `robots.txt` redirects are followed
  as RFC 9309 asks.
- Stop rules per host (other hosts continue): challenge marker or 401/403 → `blocked`; 429 → back
  off 60 s, doubling to 900 s, two in a row → `rate_limited`; ten consecutive transport errors →
  stopped. Every remaining item on a stopped host is recorded `skipped_host_stopped`.
  Markers: `sephora_snapshot.extract.CHALLENGE_MARKERS` plus `bm-verify`, `/_sec/verify`,
  `validateCaptcha`, `api-services-support@amazon.com`, `Pardon Our Interruption`; a marker
  counts when it is in the first 20 KB and (status ≠ 200 or body < 60 KB). XML/image 200s are
  not marker-scanned.
- Past `CUTOFF` the rest is recorded `skipped_cutoff`; SIGTERM flushes and writes `status.json`.

## Environment

| Variable | Meaning |
| --- | --- |
| `BUCKET` | GCS bucket name, or `file:<dir>` for a local run |
| `PREFIX` | object prefix for this run, e.g. `pages/faces/2026-10-02T08` |
| `PLAN` | `gs://bucket/plan.json[.gz]` or a local path |
| `CUTOFF` | ISO-8601 with offset; required |
| `PACE` | seconds between requests per host; floor 1.0; default 1.5 |
| `IMAGE_PACE` | same for image hosts; floor 0.5; default 1.0 |
| `IMAGES` | `1` (default) fetch the plan's pictures, `0` skip them |
| `LIMIT` | items per task after sharding; `0` = all |
| `EGRESS` | label recorded in the manifest (e.g. `cloud-run-me-central1`) |
| `UA` | User-Agent; default stock Chrome 140 desktop. Never a spoofed TLS profile |
| `GIT_SHA` | recorded in the manifest |
| `CLOUD_RUN_TASK_INDEX` / `CLOUD_RUN_TASK_COUNT` | sharding: item *i* belongs to task *i mod count*; with more than one task every task writes its own names (`pages/part-t1-0000.jsonl.gz`, `progress.t1.json`, `manifest.t1.json`, …) so tasks never overwrite each other |
| `PROXY_HOSTS` | comma list of page hosts fetched through the residential proxy; empty = no proxy |
| `PROXY_SECRET` | Secret Manager version resource holding the proxy endpoint JSON; required with `PROXY_HOSTS` |
| `PROXY_BYTE_CAP` | wire bytes this run may move through the proxy, if smaller than what the ledger has left; default and ceiling 1 800 000 000 |
| `PROXY_LEDGER` | `gs://bucket/name.json` of the **shared** proxy ledger; required with `PROXY_HOSTS` |

## Proxy rules

The proxy is a paid, owner-capped resource (1.8 GB in total) and is used only for a shop that
has refused the direct route from both Europe and the Cloud Run region (recon evidence in the
bucket). The rules the code enforces:

- Only hosts named in `PROXY_HOSTS` go through the proxy, and only hosts of the shops the owner
  put in scope for task 01a0fc6d may be named (`proxy.ALLOWED_HOSTS`, ADR-0006 Amendment 4);
  anything else is refused at start. Robots.txt for those hosts is read through the proxy too
  (same route, same answer the shop gives that route).
- Pictures and every other host always go direct, whatever `PROXY_HOSTS` says. A proxied host
  that redirects to another host leaves the proxy: the hop uses the target host's route.
- A sharded job (`CLOUD_RUN_TASK_COUNT` > 1) is refused the proxy.
- The spend is kept in **one shared ledger** (`PROXY_LEDGER`), not per process. The ledger is a
  JSON object `{"provider", "cap_bytes", "used_bytes", "runs": {"<prefix>": bytes}, "updated"}`
  created by hand, once, with the balance already consumed (the ulta.ae snapshots) entered in
  `used_bytes`. Every proxied response is added to it with a compare-and-swap on the object's
  generation and retried from the other writer's figures on a lost race, so two runs can never
  each spend the whole balance. A run's own cap is `min(PROXY_BYTE_CAP, cap_bytes - used_bytes)`
  at start (`run_cap` in the manifest). No ledger, an unreadable ledger or an exhausted one means
  the run refuses to start.
- Credentials are read from Secret Manager at run time with the job's own service account.
  Nothing in git, the image, the manifest or the logs carries them: the manifest records the
  secret's *resource name* only, and `ProxyEndpoint`'s repr hides the username and password.
- Every proxied response is charged at its compressed wire size plus 1 000 bytes of request
  overhead. When the run's cap is reached the proxied hosts stop with the state `proxy_cap` and
  the run continues for everything else; `progress.json` and `status.json` carry `proxy_bytes`,
  `status.json` also `proxy_run_cap` and `proxy_ledger_remaining`.
- Stop rules are unchanged: the first 401/403 or challenge page on a proxied host stops that
  host. The proxy is a different exit address, not a way around a refusal.

## Plan format

An item's `kind` is `html`, `json` or `xml` for a page, or `images` for a pictures-only pass:
the page is not fetched again, only the item's `images` are (used after a page run, with the
picture links read from the stored pages).


```json
{"source": "faces", "retailer": "faces", "version": 1,
 "default_headers": {"X-Requested-With": "XMLHttpRequest"},
 "items": [
  {"id": "faces-abc-en", "url": "https://www.faces.ae/en/p/x.html", "locale": "en-AE",
   "kind": "html", "ref": {"sku": "123"}, "images": ["https://cdn.example/x.jpg"],
   "headers": {"Accept": "text/html"}}
 ]}
```

`kind` ∈ `html | json | xml` and drives `Accept`; `locale` (`xx-RR`) drives `Accept-Language`
(`ar-AE,ar;q=0.9,en;q=0.8` for Arabic). Item ids must be unique; URLs must be http(s).

## Output layout (`gs://BUCKET/PREFIX/`)

| Object | Content |
| --- | --- |
| `manifest.json` | source, retailer, plan object + sha256, item counts, shard, egress, UA, paces, cutoff, Python/httpx versions, git sha |
| `pages/part-NNNN.jsonl.gz` | `{id,url,final_url,locale,kind,at,status,ms,bytes,sha256,content_type,raw,ref,state[,reason]}` (100 records per part) |
| `raw/<sha256>.<html\|json\|xml\|txt>.gz` | every 2xx **and** 4xx/5xx body (blocks keep their evidence) |
| `images/part-NNNN.jsonl.gz` | `{item_id,url,final_url,at,status,bytes,sha256,content_type,object,state[,reason]}` |
| `images/<sha256>.<jpg\|png\|webp\|gif\|avif\|svg\|bin>` | picture bytes, deduplicated by URL within a run (`state: duplicate` points at the first copy) |
| `errors/part-NNNN.jsonl.gz` | every block/challenge/429 with the first 2000 chars of the body |
| `robots.json` | per host: robots URL, status, verdict state, rule count, crawl-delay, raw object |
| `progress.json` | rewritten on every part flush and every 50 items |
| `status.json` | once at the end: `state: finished`, `outcome` ∈ `complete \| cutoff \| error`, per-host stop reason and URL, counts |

Page states: `ok | http_error | blocked | rate_limited | transport_error | robots_disallowed |
robots_unavailable | skipped_cutoff | skipped_host_stopped`. Image states add `duplicate`.
The process exits 1 only on an internal error (recorded in `status.json`).

## Plan builders

```
python -m page_capture.plans ksa-radar <products.csv> <out-dir>
python -m page_capture.plans sitemap <source> <retailer> <sitemap-list-file> <regex> <out.json> [RR]
```

`ksa-radar` writes one plan per retailer from the KSA price-radar `products.csv`: the English
page (with the row's pictures) plus the Arabic twin where the platform has a locale path
(`plans.AR_RULES`): Alshaya `/en/`→`/ar/`, Landmark and Zara `/sa/en/`→`/sa/ar/`, Charles &
Keith `/sa-en/`→`/sa-ar/`, Mamas & Papas `en.`→`ar.`, Nike / M&S / Nayomi / Aldo `/en/`→`/ar/`,
Shopify stores without a locale prefix (Milano, Steve Madden) `/products/`→`/ar/products/`.
URLs are deduplicated; `ref` carries retailer, source_product_id, item, item_label, name and the
radar row id(s). `sitemap` reads **already downloaded** sitemap XML (plain or gzipped) or URL
lists named one per line in the list file, keeps every `<loc>` matching the regex (named group
`lang` sets the locale), and never fetches anything.

### Arabic twin verification (2 Oct 2026, from the tm8 host, one request per retailer, pace 3 s)

| Retailer | Derived Arabic URL | Result | Decision |
| --- | --- | --- | --- |
| aldo | `/en/` → `/ar/` | **404** | no Arabic path known; English only (`None`) |
| american_eagle | `/en/` → `/ar/` | 200, Arabic title | kept |
| centrepoint | `/sa/en/` → `/sa/ar/` | 403 Cloudflare challenge from this host (host stopped) | kept, unverified |
| charles_keith | `/sa-en/` → `/sa-ar/` | 200 after redirect to `/sa/…`, `lang=ar dir=rtl` | rule changed to `/sa-en/` → `/sa/` |
| cos | `/en/` → `/ar/` | 200, Arabic title | kept |
| foot_locker | `/en/` → `/ar/` | 200, Arabic title | kept |
| mamas_papas | `en.` → `ar.` subdomain | `ar.mamasandpapas.com.sa` does not resolve (robots unavailable) | English only (`None`) |
| marks_spencer | `/en/` → `/ar/` | 200, `lang=ar dir=rtl` | kept |
| max_fashion | `/sa/en/` → `/sa/ar/` | robots.txt itself answered a 403 Cloudflare challenge; URL not requested | kept, unverified |
| milano | `/products/` → `/ar/products/` | 200, `lang=ar`, Arabic title | kept |
| mothercare | `/en/` → `/ar/` | 200, Arabic title | kept |
| muji | `/en/` → `/ar/` | 200, Arabic title | kept |
| nayomi | `/en/` → `/ar/` | 200 after redirect to the unprefixed path, `lang=ar dir=rtl` | rule changed to `/en/` → `/` |
| nike | `/en/` → `/ar/` | 200, `lang=ar dir=rtl` | kept |
| steve_madden | `/products/` → `/ar/products/` | 200, `lang=ar`, product title still English | kept |
| victorias_secret | `/en/` → `/ar/` | 200, Arabic title | kept |
| zara | `/sa/en/` → `/sa/ar/` | 200 Akamai `bm-verify` interstitial (host stopped) | kept, unverified |

The run itself was the job (`BUCKET=file:…`, `PACE=3`, `IMAGES=0`): robots.txt read first on all 15
reachable hosts, three hosts stopped at their first challenge, nothing retried, `status.json`
outcome `complete`. Centrepoint, Max Fashion and Zara need the Cloud Run egress or an
owner-approved route; nothing in this job works around a challenge.

## Build and push (do not run from an agent session without the owner's OK)

```
DOCKER_CONFIG=/tmp/pi-task/docker docker build \
  -t me-central1-docker.pkg.dev/productintelligence-beeb3/pi-capture/page-capture:<git-sha> tools/page_capture
DOCKER_CONFIG=/tmp/pi-task/docker docker push \
  me-central1-docker.pkg.dev/productintelligence-beeb3/pi-capture/page-capture:<git-sha>
```

Local run: `BUCKET=file:/tmp/out PREFIX=run1 PLAN=plan.json CUTOFF=2026-10-02T12:00:00+00:00 \
PYTHONPATH=tools/page_capture python -m page_capture.run`.

## Tests

`tools/page_capture/tests` — synthetic payloads only, the HTTP client is stubbed; nothing in the
test suite touches the network. `make check` covers ruff, mypy --strict and coverage.
