# Runbook: deploy pi-api (handoff to Infra)

`pi-api` is the read-only service layer (`docs/design/service-layer.md`). **Infra deploys it**;
this runbook is the handoff. Every value below is binding (the coordinator's S4 guardrails and the
hosting requirements in the decision log). Change one only with a new coordinator decision.

> **Stop rule.** If any IAM or deploy step is refused (by a safety classifier, a permission guard,
> or an org policy), **stop and report it to the coordinator**. Do not route around it: no other
> account, no broader role, no different region.

## 0. Gate: approval first

Cloud Run `pi-api` and the Artifact Registry repository `pi-api` are new standing billable
resources (estimate ≈ $0–2/month at 1Gi, design §9). Create nothing until `docs/decision-log.md` has a
coordinator entry naming both resources, me-central1, the scaling limits below, and the estimate
against the remaining $25/month budget. That entry, which also approves `--allow-unauthenticated`
(§6), lands in PR #65; check it is on `main` before §3.

**No Hosting deploy from main between the #64 merge and §6 completion** (the `/api` rewrite
targets a service that doesn't exist yet). No workflow deploys Hosting automatically, so this
binds whoever deploys it by hand. If Hosting must ship earlier, remove the rewrite first (§9).

## 1. What gets created

| Resource | Setting | Why |
|---|---|---|
| Artifact Registry repo `pi-api` | Docker, **me-central1**, cleanup policy `infra/gcp/pi-api-ar-cleanup.json` (keep the last 5 versions, delete the rest) | images stay in-region; storage stays bounded |
| Service account `pi-api@productintelligence-beeb3.iam.gserviceaccount.com` | **no keys**; never the default compute SA | the runtime identity |
| Custom role `piApiObjectReader` | `storage.objects.get` only | reads, never lists (design §9) |
| Bucket IAM binding | `pi-api@` → `piApiObjectReader` on the datasets bucket, conditioned on the `datasets/` prefix | read-only, that prefix only |
| Cloud Run service `pi-api` | **me-central1**, min 0, **max 3**, default concurrency (80), 1 vCPU, **1Gi**, timeout 30 s, request-based CPU | design §9 |

**Not created:** no Cloud SQL, no VPC connector, no Secret Manager secret, no Firebase admin role,
no `min-instances=1`. The service needs no secret: ID tokens are checked against Google's public
certificates, and GCS reads use the service account.

## 2. Pre-checks (read-only)

```sh
set -a; . infra/pi-api/service.env; set +a   # the live settings (memory, maxScale), in git
PROJECT=$PI_API_PROJECT
REGION=$PI_API_REGION
BUCKET=productintelligence-beeb3.firebasestorage.app   # confirm: the bucket publish_dataset.py writes
gcloud storage buckets describe gs://$BUCKET --format='value(uniform_bucket_level_access,location)'
```

- **Uniform bucket-level access (UBLA) must be on.** IAM conditions on object names need it.
  Infra found it **off** (PR #64 review); the coordinator **approved enabling it** on 2026-10-01.
  It is free and reversible for 90 days. Do it in this order:
  1. Record the ACLs first, in the PR or task thread (not in the repo):
     `gcloud storage buckets describe gs://$BUCKET --format='yaml(acl,default_object_acl)'`.
  2. Enable it: `gcloud storage buckets update gs://$BUCKET --uniform-bucket-level-access`.
  3. Run the EN+AR dashboard smoke afterwards (`infra/scripts/smoke_demo.py`, as in its docstring): the
     dashboard must still read its dataset through Storage rules, and anonymous reads must still
     be refused. If it fails, revert with `--no-uniform-bucket-level-access` and stop (stop rule).
- **Hosting → Cloud Run in me-central1** is supported (Infra confirmed; design §11 Q1). If a
  Hosting deploy still rejects the rewrite, stop and report it (stop rule).
- Note the datasets to serve: the object paths `publish_dataset.py` writes under `datasets/`
  (e.g. `datasets/ae/beauty/latest.json`). They become `PI_API_DATASETS` on a first deploy; later
  deploys take the live value (§6).
  With per-source files (API ≥ 1.10.0, ADR-0010), assign each source to its file instead, e.g.
  `sephora_me=datasets/ae/sephora_me/latest.json,ulta_ae=datasets/ae/beauty/latest.json`. Don't
  also list one of those paths bare in the same scope.
  **Add a source to `PI_API_DATASETS` only after its file is published.** The per-source view is
  rebuilt only when every assigned file has loaded (`source.py`, `_composed`: "per-source view
  not rebuilt: no good file yet"). A running revision keeps its old views; a new revision (any env
  change deploys one) has none, so one missing file takes down every source in that scope, not
  just the new one. Deploy a new API version with the old value first, publish the new source's
  `latest.json`, then add it.

## 3. Artifact Registry

```sh
gcloud artifacts repositories create pi-api --project=$PROJECT --location=$REGION \
  --repository-format=docker --description="pi-api images (cleanup keeps the last 5)"
gcloud artifacts repositories set-cleanup-policies pi-api --project=$PROJECT --location=$REGION \
  --policy=infra/gcp/pi-api-ar-cleanup.json --no-dry-run
```

## 4. Runtime identity (least privilege)

```sh
gcloud iam service-accounts create pi-api --project=$PROJECT \
  --display-name="pi-api runtime (read datasets/ only)"
gcloud iam roles create piApiObjectReader --project=$PROJECT \
  --title="pi-api object reader" --permissions=storage.objects.get --stage=GA
gcloud storage buckets add-iam-policy-binding gs://$BUCKET \
  --member="serviceAccount:pi-api@$PROJECT.iam.gserviceaccount.com" \
  --role="projects/$PROJECT/roles/piApiObjectReader" \
  --condition="title=pi-api-datasets-only,expression=resource.name.startsWith(\"projects/_/buckets/$BUCKET/objects/datasets/\")"
```

- No project-level role for `pi-api@`, and no key: `gcloud iam service-accounts keys list` must
  stay empty.
- The identity that runs the deploy needs `roles/iam.serviceAccountUser` **on `pi-api@` only**
  (to attach it), not on the project.

## 5. Build and push

From the repo root, at the merged commit:

```sh
SHA=$(git rev-parse --short=12 HEAD)
IMAGE=$REGION-docker.pkg.dev/$PROJECT/pi-api/pi-api:$SHA
docker build -f packages/pi_api/Dockerfile -t "$IMAGE" .
docker push "$IMAGE"
DIGEST=$(gcloud artifacts docker images describe "$IMAGE" --format='value(image_summary.digest)')
```

Deploy by digest, not by tag.

## 6. Deploy

The env vars come from the live service, not from this doc: the served files and retailers move
(per-source files, the matched file, a new retailer's hosts, the match file), and `--set-env-vars`
replaces every variable, deleting any it does not list. The deploy below sets exactly ten:
`PI_API_FIREBASE_PROJECT`, `PI_API_BUCKET`, `PI_API_DATASETS`, `PI_API_EVIDENCE_HOSTS`,
`PI_API_IMAGE_HOSTS`, `PI_API_MEMORY_MIB` (required; `MEMORY_MIB` is `infra/pi-api/service.env`'s,
and an empty live value is adopted, since services deployed before it have none) and `PI_API_CATALOGUES`, `PI_API_MATCHES`, `PI_API_ADMITTED`, `PI_API_REQUIRE_ALL`
(optional; an empty value is left out; `REQUIRE_ALL=1` is set on every body refresh, see
"Body refresh (deploy plan v2)" below). Set `BUCKET` (§2), `DATASETS`, `EVIDENCE_HOSTS`,
`IMAGE_HOSTS`, `CATALOGUES` and `MATCHES` to the values you mean to serve, and `ADMITTED` to the
`PI_API_ADMITTED=` value `infra/scripts/pi_api_admission.py check` prints for that `DATASETS` (§6;
empty while the served set is within the fit) (the §2 paths and the hosts below on a first deploy),
then run (bash):

```sh
SVC_JSON=$(gcloud run services describe pi-api --project=$PROJECT --region=$REGION \
  --format=json 2>/dev/null)
live_env() { printf '%s' "$SVC_JSON" | python3 -c 'import json,sys
env = json.load(sys.stdin)["spec"]["template"]["spec"]["containers"][0].get("env", [])
if sys.argv[1] == "--names": print("\n".join(e["name"] for e in env))
else: print(next((e.get("value", "") for e in env if e["name"] == sys.argv[1]), ""))' \
  "$1" 2>/dev/null; }
FIREBASE_PROJECT=$PROJECT MEMORY_MIB=$PI_API_MEMORY_MIB
REQUIRED="FIREBASE_PROJECT BUCKET DATASETS EVIDENCE_HOSTS IMAGE_HOSTS MEMORY_MIB" OPTIONAL="CATALOGUES MATCHES ADMITTED REQUIRE_ALL"
ENV_OK=1 SET_ENV= KNOWN=" "
test "$FIRST_DEPLOY" = 1 && test -n "$SVC_JSON" \
  && { echo "STOP: FIRST_DEPLOY=1 but pi-api already exists"; ENV_OK=0; }
for v in $REQUIRED $OPTIONAL; do
  want=${!v}; have=$(live_env "PI_API_$v"); KNOWN="$KNOWN PI_API_$v "
  case " $OPTIONAL " in *" $v "*) opt=1;; *) opt=0;; esac
  if { test -n "$want" || { test $opt = 1 && test -z "$have"; }; } \
    && { test "$want" = "$have" || { test -z "$have" \
      && { test "$FIRST_DEPLOY" = 1 || test $v = MEMORY_MIB || test $v = REQUIRE_ALL; }; }; } \
    && case "$want" in *@*) false;; esac
  then echo "PI_API_$v ok: [$want]"; test -z "$want" || SET_ENV="$SET_ENV@PI_API_$v=$want"
  else echo "STOP: PI_API_$v live=[$have] wanted=[$want] (no '@' allowed)"; ENV_OK=0
  fi
done
EXTRA=$(live_env --names | while read -r n; do
  case "$KNOWN" in *" $n "*) ;; *) printf '%s ' "$n";; esac; done)
test -z "$EXTRA" || { echo "STOP: live env vars this deploy would delete: $EXTRA"; ENV_OK=0; }
SET_ENV="^@^${SET_ENV#@}"
test "$ENV_OK" = 1 && echo "ENV OK" || echo "ENV STOP"
```

On any STOP, do not deploy. Either take the live value (`DATASETS=$(live_env PI_API_DATASETS)`,
and the same for the others) or treat the difference as a config change with its own approval and
its own before/after diff. A live variable outside the ten (printed by name only) means this
command would delete it: STOP and extend this list in a reviewed change first. Only a first
deploy (no service yet) sets `FIRST_DEPLOY=1`, and the guard STOPs if the service exists; a failed
describe otherwise STOPs. The STOP lines print live values: all ten are non-secret config (`ADMITTED` is sha256 digests). A
secret never joins this list; it would need `--set-secrets` (not used, see below) and a reviewed
change that prints its name only. To change one variable on a running service, use `gcloud run
services update --update-env-vars` with its own approval (it leaves the others alone), not this
command.

Then check the live memory and maxScale against `infra/pi-api/service.env` (the deploy below sets
the revision's from it; a STOP means the file and the service disagree, so the memory rule would be
evaluated against the wrong instance size):

```sh
gcloud run services describe pi-api --project=$PROJECT --region=$REGION --format=json \
  | uv run python infra/scripts/pi_api_admission.py service   # → SERVICE OK, or no deploy
```

Skip it on a first deploy (no service yet), and in the revision that changes `service.env` itself:
there it STOPs on exactly the changed lines, which the PR's reviewed diff covers.

```sh
test "$ENV_OK" = 1 && gcloud run deploy pi-api --project=$PROJECT --region=$REGION \
  --image="$REGION-docker.pkg.dev/$PROJECT/pi-api/pi-api@$DIGEST" \
  --service-account="pi-api@$PROJECT.iam.gserviceaccount.com" \
  --min-instances=0 --max-instances=$PI_API_MAX_SCALE_REVISION --cpu=1 \
  --memory=${PI_API_MEMORY_MIB}Mi --timeout=30s \
  --cpu-throttling --cpu-boost --port=8080 --ingress=all --allow-unauthenticated \
  --set-env-vars="$SET_ENV"
```

This full form is for a first deploy or a deliberate config change only, in the same shell right
after `ENV OK`. An image-only redeploy passes `--image` and nothing else, so every env var stays
as it is.

- **No `--concurrency`** (default), no `--add-cloudsql-instances`, no `--vpc-connector`, no
  `--set-secrets`. Never set `PI_API_ALLOW_TEST` in production.
- **Evidence links** need `PI_API_EVIDENCE_HOSTS` (for example
  `<source_key>=<host>,<source_key>=<host>`, the exact hosts the connectors fetch). Without
  it the service runs, but every offer's `evidence.url` is null. A host the API should not link
  to is simply left out; there are no wildcards.
  The first value (set on `pi-api-00004-9b6`, 2026-10-01) was
  `sephora_me=www.sephora.me,ulta_ae=www.ulta.ae`; read today's from the service (§6). A
  redeploy that changes only the image keeps it: never pass `--set-env-vars` for an image-only
  deploy. A typo nulls every link without an error, which is why §8 checks one. For two or more
  pairs, the commas clash with `--set-env-vars`. Switch the delimiter:
  `--set-env-vars="^@^PI_API_EVIDENCE_HOSTS=a=x.example,b=y.example@PI_API_BUCKET=..."`.
- **Card thumbnails** (API 1.3.0) need `PI_API_IMAGE_HOSTS`, in the same format: the hosts the
  dashboard may hotlink images from. The 2026-10-01 value was
  `sephora_me=img-product.sephora.me,ulta_ae=media.alshaya.com` (read today's from the service,
  §6), the two external hosts in the Hosting CSP `img-src` (decision log, 2026-10-01). Without it
  every `ProductCard.image` is null.
- **Match edges** (ADR-0012 §6) optionally use `PI_API_MATCHES`, one `pi.matches/v1` object path
  applied to the per-source views (it needs `source=path` entries in `PI_API_DATASETS`). Setting or
  changing it is its own deploy with the owner's go. Once it is live, §6 carries it: a redeploy
  with a different or empty `MATCHES` STOPs.
- **SKU galleries and identities** (API 1.7.0) optionally use `PI_API_CATALOGUES`, a comma-separated
  list of `pi.catalogue/v1` objects, for example
  `datasets/ae/beauty/catalogues/ulta_ae/latest.json`. These stay under the runtime identity's
  existing `datasets/` read permission. `/api/v1/catalogues/{retailer}` reports inventory and
  completeness; `/api/v1/catalogues/{retailer}/skus/{sku}` returns IDs, parent/child links and the
  complete gallery behind the same Firebase login. Image URLs use the existing exact host map.
  Identical downloaded bytes appear once per SKU gallery; the catalogue retains every source
  asset reference. Missing linked SKUs remain unresolved, and parent summaries are marked using
  explicit relationships, never the shape of a SKU. This optional dataset does not replace the
  combined price dataset or advance its cutoff. Original capture and metadata import times are
  separate. `offline_import.ulta_catalogue` validates an audited inventory against stored source
  content, appends derived metadata to `listing_content` idempotently, then exports from that
  database. It never writes price or stock observations.
- **`--allow-unauthenticated` is deliberate.** Hosting rewrites call the service without an IAM
  identity, so `allUsers` gets `run.invoker`. Every route, unknown paths included, verifies the
  Firebase ID token in the app and fails closed (decision log, 2026-10-01). If an org policy
  (for example domain-restricted sharing) refuses the binding, stop (stop rule).
- The startup probe is the default TCP probe. There are no health routes, by design.
- **Checks after a revision that changes the served files or the memory** (there is no
  `/healthz`; every route needs a Firebase token):
  1. The revision's logs from container start carry no `MEMORY RULE: … REFUSED` ERROR and no
     `PI_API_MEMORY_MIB is …: assuming 1024 MiB` ERROR, and one `dataset <path> loaded at
     generation <n>` line per `DATASETS` path (a path shared by several sources loads once).
  2. One signed-in product request per dataset key in `DATASETS` (for example `ounass_ae`,
     `sephora_me`, `ulta_ae`, `faces_ae`) returns 200 (`infra/scripts/prod_smoke_api.py`, run by
     the owner with their token; until then the report says "signed-in smoke NOT run").
  3. The loaded product count per new source matches the export's (for Ounass, the export's
     `products` count; 32,810 on 2026-10-07).
- **`--cpu-boost`**: the gcloud default (startup-only), passed explicitly so redeploys match live; accepted 2026-10-01.
- **Memory 1Gi** (decision log, 2026-10-01; was 512Mi). Measured locally (RSS, Python 3.12):

  | What | Measured |
  |---|---|
  | App baseline (imports, FastAPI app, a 16-product fixture loaded) | ~66 MiB |
  | Loaded dataset | ~27 KiB per product (20 000 products, 54 MiB JSON → 558 MiB RSS) |
  | One export, per row (CSV: rows + encode peak; JSONL less) | ~4.4 KiB (50 k rows ≈ 220 MiB) |
  | **Peak, 20 000 products loaded + 2 concurrent CSV exports of all of them** | **800 MiB** |

  That table predates content and the Ounass/Bloomingdale's catalogues. Re-measured 2026-10-07 on
  main `67496647`: pi_api's own `SnapshotSource` on the real Ounass v3 (32,810 products,
  107.4 MB indented = **72.7 MB compact**) plus the 9,529-product beauty file, composed as
  `sephora_me`, `ulta_ae` and `ounass_ae`. Faces is not included, so production is somewhat higher.

  | Phase | Time | Peak RSS | RSS after |
  |---|---|---|---|
  | Imports | | | 67 MiB |
  | Cold start, beauty only | 5 s | 308 MiB | 268 MiB |
  | Cold start, + Ounass (42,339 products) | 26–30 s | 1,185 MiB | 942 MiB |
  | `GET /products?q=…` | 4.5 s | 947 MiB | 947 MiB |
  | CSV export of all products (6.7 MB) | 15–16 s | ~1,030 MiB | ~1,000 MiB |
  | **Refresh: a new Ounass generation** (×4) | 22–31 s | **1,739–1,795 MiB** | 1,409–1,596 MiB |

  Re-measured on the same files once offer content is packed on load and the dataset is
  validated from bytes (tm8 01a11763-dc85). These are the numbers the gate below uses:

  | Phase | Time | Peak RSS | RSS after (trimmed) |
  |---|---|---|---|
  | Cold start, beauty only | 5 s | 308 MiB | 272 MiB |
  | Cold start, + Ounass | 32 s | **982 MiB** | 712 MiB |
  | CSV export of all products | 15 s | 752 MiB | 747 MiB |
  | `GET /products/{id}` (unpacks one product's content) | 0.2 s | 749 MiB | 747 MiB |
  | **Refresh: a new Ounass generation** (×4) | 30–43 s | **1,450–1,455 MiB** | 1,059–1,138 MiB |

  Most of the old peak was the parse, not the resident data: validating a decoded `str` held the
  text (~2× the file) plus a UTF-8 copy for pydantic-core. Validating the bytes removes both.
  Packing keeps description, ingredients, images and variants zlib-compressed per offer and
  unpacks them for the detail view only; card, list and search fields stay resident.

  - **No leak.** Allocated blocks stay flat across refreshes. The RSS that remains after a refresh
    is glibc keeping freed arenas: `malloc_trim` brings it back to ~1,050 MiB, and the next
    refresh's peak does not grow.
  - **A refresh holds two generations.** The old file and its composed view stay live while the
    new file is parsed and composed. For Ounass that is now ~1,180 MiB above the other sources at
    peak (was ~1,530), about 2.68 × its steady ~440 MiB (~6.3 bytes resident per compact JSON
    byte; was 9.3), or **~16.3 MiB of refresh peak per compact MB** (was 21.0).
  - **1Gi cannot hold Ounass**, not even at cold start (982 MiB before Faces). 2Gi holds today's
    set (Ounass, beauty, Faces, two exports) with ~265 MiB to spare at a refresh peak, but the
    general rule below would allow only ~27.5 MB for the largest file there. **3Gi** is the size for
    Ounass (decision log 2026-10-07), with max-instances 1 on the revision and the service
    (`infra/pi-api/service.env`). Cost at me-central1 (Tier 2, request-based CPU): about $3-7 a
    month expected; one instance serving every second of a month would be about $107 (the cost
    row and the budget alerts are in step F's runbook change). Step F's revision (`f3gi`,
    2026-10-07) went first, on the image from before the load rule, after a bench of the live set on that image's code
    (export sha256 `8963cbed…`, beauty and Faces as served: refresh peak 1,757 MiB ≤ 2,304).
    The first revision on an image with the load rule must carry the record
    `infra/pi-api/admission/ounass_ae.json` (the same four files, packed: refresh peak 1,661 MiB)
    as `PI_API_ADMITTED=8963cbedf30bdcd6247de077296a7d5421c4462589182951c64ea463e8933eed:28937955`
    (others: beauty 26,712,113 counted once for `sephora_me` and `ulta_ae`, Faces 2,225,842).
    Without it pi_api refuses Ounass (`UNAVAILABLE`): the set is 2,938 MiB on the fit. Others
    are 1.06 MB under the 30 MB reserve, so no beauty, Faces or Ounass publish goes out until
    that revision is live (Coordinator, 2026-10-07); any later publish of one of them is a new
    record.
  - **The export gate** (`V3_MAX_BYTES` in `pi_dataset.gate`, imported by the exporter and by
    pi_api) is **51,000,000** bytes of **compact** JSON. The exporter and the publisher write
    compact JSON; whitespace is about a third of an indented file and none of it is resident. It
    comes from a fit, not from one file: the beauty file (the densest per byte measured; Ounass is
    16.3 MiB per MB) scaled by repeating its products with fresh skus, served alone by
    `SnapshotSource`, cold start then four refreshes, RSS sampled every 20 ms (2026-10-07):

    | Compact bytes | Products | Cold start peak | Refresh peaks (×4) |
    |---|---|---|---|
    | 10,110,000 | 9,529 | 309 MiB | 394 MiB |
    | 30,451,012 | 28,587 | 770 MiB | 1,018–1,020 MiB |
    | 60,957,592 | 57,174 | 1,474 MiB | 1,967–1,993 MiB |

    Least squares on the highest refresh peak: **refresh peak ≈ 70.4 MiB + 31.48 MiB per compact
    MB** (residuals −5, +9, −4 MiB; the intercept is the ~67 MiB of imports). The rule is that the
    largest file's refresh peak plus the other files' resident memory stays within **75% of the
    instance memory** (25% for exports, request buffers and allocator slack). With the other files
    at the 600 MiB reserve (rule 2 below):

    | Memory | 75% | Largest file (rule 1) | Today's Ounass, 72.7 MB |
    |---|---|---|---|
    | **3Gi** | 2,304 MiB | (2,304 − 600 − 70.4) / 31.48 = 51.9 MB → **51,000,000** bytes | over the gate: needs an admission record |
    | 2Gi | 1,536 MiB | (1,536 − 600 − 70.4) / 31.48 = 27.5 MB | over the gate |

    The fit spans 10–61 MB. Nothing smaller than the 10 MB point was measured, so for small files
    the intercept is extrapolated (the 10 MB point sits 5 MiB under the line, so it is not
    optimistic there), and nothing above 61 MB is covered: a larger file is only ever served on a
    record of its own. `test_content_memory.py` loads a 10 MB content-heavy sample (real Ounass
    text, its zlib ratio pinned) and scales it to the gate, so it pins the content-heavy end.
    The constant assumes **3Gi**; at 2Gi it would be 27,500,000.
  - **Over the gate, a file is served on a measured admission record only** (Coordinator,
    2026-10-07; supersedes the 2026-10-03 "no override" note). `demo_export --allow-over-gate`
    writes an over-gate body, prints `OVER GATE <file> <bytes> sha256=<hex>` and exits 3; that
    sha is advisory, because the publisher re-serialises. **pi_api enforces the composed rule at
    load** (`pi_dataset.gate.refusal`), not the per-file byte gate: before parsing a new
    generation it sums every served body with the new one (a path shared by several sources,
    such as `sephora_me` and `ulta_ae` on the beauty file, is read, parsed and counted once) and
    evaluates `70.4 + 31.48 × largest_MB + 20 × others_MB` against 75% of `PI_API_MEMORY_MIB`.
    Over it, the set loads only if the largest body's sha256 is in `PI_API_ADMITTED` and the
    other files total at most that entry's measured bytes. Otherwise it logs ERROR `MEMORY RULE:
    dataset <path> generation <n> REFUSED, …` with the reason and does not parse it: at cold
    start the path is `UNAVAILABLE` (its sources serve nothing), on a refresh it is `kept at
    <generation>` (the last good one stays served). A missing or unreadable `PI_API_MEMORY_MIB`
    logs an ERROR and assumes 1024 MiB, the smallest instance (fail closed). `PI_API_ADMITTED`
    entries are `sha256:others_bytes`, as `pi_api_admission.py check` prints them; the record also
    pins whether offer content was packed (`packContent`; pi_api packs by default). **The admitted sha256 is of the
    decompressed `latest.json` body that pi_api parses**: not of the gzip object in the bucket,
    and not of the exporter's file (the publisher writes `dump_dataset(compact=True)`, then
    gzips). The publisher prints it: `admission body=<n>B sha256=<hex>`, dry run included.

    The record is `infra/pi-api/admission/<dataset>.json` (schema `pi.admission/v1`: sha256,
    bytes, memory, every served file's path/bytes/sha256, baseline, cold-start and four refresh
    peaks, date, bench commit), written by `infra/scripts/pi_api_admission.py measure` with
    **every** `PI_API_DATASETS` file resident and the largest refreshed four times. It passes only
    if the highest refresh peak is at most 75% of the memory. `pi_api_admission.py check`, run
    before the deploy, refuses (`ADMISSION STOP`) when an over-gate body has no record with its
    sha256, when the record's peak is over 75%, when it was measured at another memory or with
    another set of files, or when another file grew; otherwise it prints `ADMISSION OK` and the
    `PI_API_ADMITTED=` value. A new export is a new sha: it is measured again. Order for an
    over-gate dataset (Ounass):

    1. Export with `--allow-over-gate` (exit 3 is expected for this dataset only).
    2. Publisher `--dry-run --live-file`: note the `admission … sha256`.
    3. Bench that exact body: `pi_api_admission.py measure` on a local copy of every served
       object at its bucket path, with the next revision's `DATASETS` and memory.
    4. Commit the record through review.
    5. Publish for real. pi_api does not serve it yet: its log shows one `MEMORY RULE: … REFUSED,
       kept at …` (or `UNAVAILABLE`) ERROR for this dataset per refresh, `… has no admission
       record`, which is expected until step 6, not an incident.
    6. Deploy the revision with `ADMITTED` from `pi_api_admission.py check` (and the memory the
       record was measured at).
    7. Verify it is served.
  - **The gate is per file; the memory is for all served files together.** Refreshes run one at
    a time, so only the largest file's second generation counts; every other file counts at its
    resident rate, ~20 MiB per compact MB (the beauty file's measured rate: 201 MiB for 10.1 MB).
    That rate is lower than the refresh rate, so rule 2 holds only while **the largest file
    (rule 1) is at least as large as any other single file**: the file that refreshes at 31.48
    MiB per MB must be the largest. The 600 MiB reserve is **30 MB** at the resident rate
    (`OTHERS_MAX_BYTES`, the exporter's derivation of the 51 MB gate). An admission record is
    issued only while its other files total at most `ADMISSION_OTHERS_MAX_BYTES` (80,000,000:
    beauty, Faces and Bloomingdale's beside Ounass); the record's measured peak at 75% of the
    instance is still what admits a set. That cap governs issuing a record, never serving: pi_api serves an admitted body while the
    other files total at most the record's own measured figure (`refusal`, `≤`). Before
    any revision that adds to `PI_API_DATASETS` (or a publish that grows a served file), size
    **every** served file's `latest.json` as **decompressed, compact** bytes and check:

    1. the largest file is at most **51,000,000** bytes (or has a passing admission record), and
    2. all the other files together are at most **30,000,000** bytes.

    If either fails, do not deploy that revision: serve the large dataset alone, or keep the new
    one out until it is measured. A second large catalogue (Bloomingdale's) always fails rule 2
    and needs a record with both resident. Two traps: the publisher stores objects gzip-encoded,
    so the GCS object size is the gzip size; and a file published before compact output (before
    2026-10-07) is indented, ~1.5× its compact size. The check below handles both (paths from
    `DATASETS`, dropping any `source=` prefix):

    ```sh
    for p in $(printf '%s' "$DATASETS" | tr ',' '\n' | sed 's/^[^=]*=//' | sort -u); do
      gcloud storage cat "gs://$BUCKET/$p" | python3 -c 'import gzip,json,sys
    b = sys.stdin.buffer.read()
    b = gzip.decompress(b) if b[:2] == b"\x1f\x8b" else b
    print(len(json.dumps(json.loads(b), separators=(",", ":"), ensure_ascii=False).encode()), sys.argv[1])' "$p"
    done | sort -rn
    ```

    The first line is the largest file (rule 1); the rest must sum to at most 30,000,000 (rule 2).
  - **While pi-api runs at 1Gi** (until step F's 3Gi revision is live), the same composition sets
    the cap: the largest file's refresh peak plus the others' resident memory within 75% of 1Gi,
    `70.4 + 31.48 × largest_MB + 20 × others_MB ≤ 768 MiB`, with the largest file at least as large
    as any other. Today's set (beauty 17.05 MB, Faces 1.4 MB) is 635 MiB. With Faces as the only
    other file, the largest may be at most **21,000,000** bytes. pi_api applies this at load with
    `PI_API_MEMORY_MIB=1024`: a file that would break it is refused, not served into an OOM.
  - **Cold start vs `--timeout=30s`.** With Ounass the load takes 26–30 s, and uvicorn opens the
    port only after it, so the default TCP startup probe passes. The first request after scale to
    zero waits that long. Measure it on the first 3Gi revision. `--min-instances=1` would remove
    the wait, but it is new spend and needs the owner's OK.
  - The app allows two exports at once per instance; a third gets `429 rate_limited`
    (`Retry-After: 5`). If Cloud Run logs a memory-limit restart, report it; change nothing
    without a decision.
- **`--timeout=30s`, `--cpu-throttling` (request-based CPU).** The slowest route is a 50 k-row CSV
  export, ~4 s measured locally (~1.3 s JSONL); even several times slower on 1 vCPU it is well
  inside 30 s.

### Body refresh (deploy plan v2)

A new dataset body never overwrites a served object. It goes to a new create-only path, a new
revision serves it, and rollback is routing traffic back to the previous revision.

1. **Publish to a versioned path.** Read the live `PI_API_DATASETS` (`live_env PI_API_DATASETS`
   above) and pass it verbatim:

   ```sh
   uv run python infra/scripts/publish_dataset.py <body.json> --project=$PROJECT \
     --versioned --live-datasets="$(live_env PI_API_DATASETS)"
   ```

   It writes one object, `datasets/<cc>/<source|beauty>/v/<stem>-<sha12>.json`, with
   `if_generation_match=0` (a re-run is refused, never an overwrite). It writes no `latest.json` and
   no Firestore document, and prints the `PI_API_DATASETS=` value to deploy. A path the live
   revision serves is refused, and so is a body set on the refused list.
   - **Beauty (sephora_me + ulta_ae)** also needs `--allow-beauty-versioned`, only on the owner's P1
     answer (form 01a11c72-16e3). The retention check is built in and fails the publish with
     nothing uploaded:
     - without `--reconciled-removals` (keys-only): every live ulta_ae offer is present by product
       id and offer key, and every live (sku, url) pair is still there;
     - with `--reconciled-removals FILE` (fresh): an offer may be missing only if its product id is
       in FILE, the capture lane's `removal_evidence.csv` (removal task 01a11c77-75e6). Every
       ulta_ae row must carry `pdp-404`, `pdp-410`, `sitemap-absent` or `search-absent`. Any other
       value refuses the publish: a notObservedReason (`retained`, `blocked`, `rate_limited`,
       `capture_in_progress`, `planned_not_captured`) or `pdp-variant-absent`, which drops a
       variant from a kept offer and never excuses an absent one (Coordinator 01a11cad-17da,
       01a11cad-a1a9).
     - the file's sephora_me offers get the source guard (no live offer lost), against the body
       the live `PI_API_DATASETS` serves sephora_me from.
   - **Ulta U1 (owner's export) publish gate, both must pass** (Coordinator 01a11c8f-2138): the
     keys-only check above **and** DeepTester's `MODE=retain` (`scratch/wk/ulta-retention-check.py`,
     01a11c8d-e603). Keys-only proves no offer was dropped. MODE=retain proves every offer missing
     from the export is retained as not_observed: its capturedAt is unchanged and earlier than the
     window, and it has no price or stock value in the new window. Neither replaces the other.
   - **Window guard (in code; ruling 01a11cad-17da).** Publish every body first, chaining each
     printed `PI_API_DATASETS=` value into the next `--live-datasets`. Then check the final value,
     read-only, before step 2:

     ```sh
     uv run python infra/scripts/publish_dataset.py --project=$PROJECT --check-served="$NEW_DATASETS"
     ```

     It reads every body the value serves and HOLDs if any retailer has no crawl window (or no
     market for its country), if the windows are in more than one market time zone, or if two
     windows' ENDs are more than 7 calendar days apart in that zone (`meta.markets` by country;
     for AE, Asia/Dubai: 8 is refused, 7 passes, and days turn at 20:00Z).
     A retailer that cannot be refreshed (tonight ulta_ae, blocked: Coordinator 01a11cc0-86a1)
     is WITHHELD, not refused, only when its body gives it no window and carries a
     `notObserved[]` entry for the whole retailer (`context` and `categories` null) that starts
     no later than the day after its `since` and whose `end` reaches its scope's cutoff day: the
     latest `meta.cutoff` across the `NEW_DATASETS` bodies of the retailer's scope (for ulta_ae,
     the beauty-scope bodies), as a date in the market's time zone (Asia/Dubai; 20:00Z is already
     the next day), as the API's per-scope `compose` takes it (Coordinator 01a11d05-862f,
     01a11d19-9686). Set that `end` at roll time, from the final set, never from the body's own
     window. The guard prints `<body>: <retailer> withheld, not observed until <date>: <why>`
     and leaves it out of the gap, which is still counted over the whole set. Never give it a
     window to pass: a retailer with a window is always counted. A windowless retailer with no
     offers serves nothing and is skipped.
     **Required pre-roll step** (Coordinator 01a11d14-184d): run this on the full final set and
     paste its output verbatim into the pre-roll report. It must print `withheld` for ulta_ae
     and no refusal; any refusal stops the roll. Only a value that prints
     `window guard: N bodies, ok` is rolled. The new revision
     repeats the same check (`pi_api.windows`) at start under `PI_API_REQUIRE_ALL=1`, so a value
     that skipped this step never becomes Ready.
2. **Deploy a new revision without traffic.** Only `PI_API_DATASETS` changes (and
   `PI_API_REQUIRE_ALL=1`, the first time), so this is the one-variable update above, not the full
   form, which would STOP on the changed `DATASETS`:

   ```sh
   gcloud run services update pi-api --project=$PROJECT --region=$REGION --no-traffic \
     --tag=refresh --update-env-vars="^@^PI_API_DATASETS=$NEW_DATASETS@PI_API_REQUIRE_ALL=1"
   ```

   With `PI_API_REQUIRE_ALL=1` pi_api refuses to start unless every configured file and view loads,
   so a revision with an unserved body never becomes Ready. Run the §8 checks against the `refresh`
   tag URL before any traffic moves.
3. **Move traffic:** `gcloud run services update-traffic pi-api --region=$REGION
   --to-revisions=<new>=100`.
4. **Roll back** by routing traffic to the previous revision (§9). Its env still names the old
   objects, which are never overwritten or deleted, so rollback needs no republish.
5. **Report** on the deploy task: the before and after revision and image digest; the old and new
   `PI_API_DATASETS`; each new body's sha256 and path; the exact traffic command; and for beauty,
   the form response id that allowed it.

## 7. Hosting rewrite

`infra/firebase.json` routes `/api/**` to `{serviceId: "pi-api", region: "me-central1"}` as its
first rewrite, with no catch-all after it. `test_hosting_routes_api_first_and_unknown_paths_404`
guards the order, the region and the missing catch-all. Deploy Hosting only after the service exists:

```sh
npx -y firebase-tools@14.27.0 deploy --only hosting --project $PROJECT
```

The rewrite keeps the API same-origin, so the CSP `connect-src 'self'` is unchanged.

## 8. Verify (no data changes)

```sh
URL=https://$PROJECT.web.app
curl -si "$URL/api/v1/meta" | grep -iE '^(HTTP|cache-control|www-authenticate)'
#  → 401, Cache-Control: private, no-store, WWW-Authenticate: Bearer realm="pi-api"
curl -si "$URL/api/v1/no-such-route" | head -1            # → 401 too (auth runs first)
gcloud run services describe pi-api --project=$PROJECT --region=$REGION \
  --format='yaml(spec.template.spec.serviceAccountName,spec.template.metadata.annotations,spec.template.spec.containers[0].resources)'
```

- With a signed-in user's ID token, `GET /api/v1/meta` → 200, `private, no-store`.
- `GET /api/v1/export/coverage` (signed in) downloads a CSV whose line 1 is `# {"schemaId":
  "pi-api.export/v1", ...}`. Logs Explorer shows one entry with
  `jsonPayload.event="pi_api.export"` and `outcome="ok"` (uid, view, filters, row count; no row
  content).
- **Evidence links:** signed in, `GET /api/v1/products/s-P10000765-unknown-unknown` → the
  `sephora_me` offer's `evidence.url` is non-null and starts with `https://www.sephora.me/`. If it
  is null, `PI_API_EVIDENCE_HOSTS` is missing or misspelt. If that id has left the dataset, pick
  another from the published file (stored gzip-encoded; `gunzip -cf` also passes plain JSON):
  `gcloud storage cat gs://$BUCKET/datasets/ae/beauty/latest.json | gunzip -cf | jq -r '[.products[] | select(.offers.sephora_me.url) | .id][0]'`.
- **Negative check:** an offer from a retailer that is not in `PI_API_EVIDENCE_HOSTS`, or whose url
  is on another host, must have `evidence.url: null`. Both live retailers (`sephora_me`,
  `ulta_ae`) are listed, so this is covered by the pi_api tests from #72. Before adding a new
  retailer's host, run the same `GET` on one of its ids and expect null.
- Check the describe output: `autoscaling.knative.dev/maxScale: '3'`, no `minScale` (or 0), no
  Cloud SQL or VPC annotations, the `pi-api@` account, memory 1Gi, timeout 30.

## 9. Record, roll back, tear down

- Append the resources to `infra/gcp/README.md` (date, settings, cost), as for the backup bucket.
- **Roll back:** `gcloud run services update-traffic pi-api --region=$REGION --to-revisions=<previous>=100`.
- **Tear down** (reverse order): `firebase.json` rewrite removed and Hosting redeployed; `gcloud run
  services delete pi-api`; remove the bucket binding; `gcloud iam roles delete piApiObjectReader`;
  `gcloud iam service-accounts delete pi-api@…`; `gcloud artifacts repositories delete pi-api`.
