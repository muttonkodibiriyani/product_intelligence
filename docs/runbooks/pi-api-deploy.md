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
PROJECT=productintelligence-beeb3
REGION=me-central1
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
  (e.g. `datasets/ae/beauty/latest.json`). They become `PI_API_DATASETS`.

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

```sh
gcloud run deploy pi-api --project=$PROJECT --region=$REGION \
  --image="$REGION-docker.pkg.dev/$PROJECT/pi-api/pi-api@$DIGEST" \
  --service-account="pi-api@$PROJECT.iam.gserviceaccount.com" \
  --min-instances=0 --max-instances=3 --cpu=1 --memory=1Gi --timeout=30s \
  --cpu-throttling --cpu-boost --port=8080 --ingress=all --allow-unauthenticated \
  --set-env-vars="^@^PI_API_FIREBASE_PROJECT=$PROJECT@PI_API_BUCKET=$BUCKET@PI_API_DATASETS=<paths from §2>@PI_API_EVIDENCE_HOSTS=sephora_me=www.sephora.me,ulta_ae=www.ulta.ae@PI_API_IMAGE_HOSTS=sephora_me=img-product.sephora.me,ulta_ae=media.alshaya.com"
```

This full form is for a first deploy or a deliberate config change only. The values above are the
live ones on `pi-api-00004-9b6` (2026-10-01). An image-only redeploy passes `--image` and nothing
else, so every env var stays as it is.

- **No `--concurrency`** (default), no `--add-cloudsql-instances`, no `--vpc-connector`, no
  `--set-secrets`. Never set `PI_API_ALLOW_TEST` in production.
- **Evidence links** need `PI_API_EVIDENCE_HOSTS` (for example
  `<source_key>=<host>,<source_key>=<host>`, the exact hosts the connectors fetch). Without
  it the service runs, but every offer's `evidence.url` is null. A host the API should not link
  to is simply left out; there are no wildcards.
  Today's value (set on `pi-api-00004-9b6`, 2026-10-01) is
  `sephora_me=www.sephora.me,ulta_ae=www.ulta.ae`. A redeploy that changes only the image keeps
  it: never pass `--set-env-vars` for an image-only deploy. A typo nulls every link without an
  error, which is why §8 checks one. For two or more pairs, the commas clash with
  `--set-env-vars`. Switch the delimiter:
  `--set-env-vars="^@^PI_API_EVIDENCE_HOSTS=a=x.example,b=y.example@PI_API_BUCKET=..."`.
- **Card thumbnails** (API 1.3.0) need `PI_API_IMAGE_HOSTS`, in the same format: the hosts the
  dashboard may hotlink images from. Today's value is
  `sephora_me=img-product.sephora.me,ulta_ae=media.alshaya.com`, the two external hosts in the
  Hosting CSP `img-src` (decision log, 2026-10-01). Without it every `ProductCard.image` is null.
- **SKU galleries and identities** (API 1.6.0) optionally use `PI_API_CATALOGUES`, a comma-separated
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
- **`--cpu-boost`**: the gcloud default (startup-only), passed explicitly so redeploys match live; accepted 2026-10-01.
- **Memory 1Gi** (decision log, 2026-10-01; was 512Mi). Measured locally (RSS, Python 3.12):

  | What | Measured |
  |---|---|
  | App baseline (imports, FastAPI app, a 16-product fixture loaded) | ~66 MiB |
  | Loaded dataset | ~27 KiB per product (20 000 products, 54 MiB JSON → 558 MiB RSS) |
  | One export, per row (CSV: rows + encode peak; JSONL less) | ~4.4 KiB (50 k rows ≈ 220 MiB) |
  | **Peak, 20 000 products loaded + 2 concurrent CSV exports of all of them** | **800 MiB** |

  So at the dataset budget (≤ 50 MB JSON) the measured peak is ~800 MiB, inside 1Gi with
  ~200 MiB headroom. A 50 k-row export would need a 50 k-product dataset, which by itself exceeds
  the budget, so the 2 × ~220 MiB worst case never adds to a full dataset. 512Mi does not fit a
  budget-size dataset at all. The app allows two exports at once per instance; a third gets
  `429 rate_limited` (`Retry-After: 5`). If Cloud Run logs a memory-limit restart, report it;
  change nothing without a decision. The first lever is less concurrency (a lower
  `--concurrency`, or `MAX_CONCURRENT_EXPORTS` in `pi_api/export.py`), not more memory.
- **`--timeout=30s`, `--cpu-throttling` (request-based CPU).** The slowest route is a 50 k-row CSV
  export, ~4 s measured locally (~1.3 s JSONL); even several times slower on 1 vCPU it is well
  inside 30 s.

## 7. Hosting rewrite

`infra/firebase.json` already routes `/api/**` to `{serviceId: "pi-api", region: "me-central1"}`
**before** the SPA catch-all `**`. `test_hosting_routes_api_before_the_spa_catch_all` guards the
order and the region. Deploy Hosting only after the service exists:

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
