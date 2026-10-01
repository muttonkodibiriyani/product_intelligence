# Runbook: deploy pi-api (handoff to Infra)

`pi-api` is the read-only service layer (`docs/design/service-layer.md`). **Infra deploys it**;
this runbook is the handoff. Every value below is binding (the coordinator's S4 guardrails and the
hosting requirements in the decision log). Change one only with a new coordinator decision.

> **Stop rule.** If any IAM or deploy step is refused (by a safety classifier, a permission guard,
> or an org policy), **stop and report it to the coordinator**. Do not route around it: no other
> account, no broader role, no different region.

## 0. Gate: approval first

Cloud Run `pi-api` and the Artifact Registry repository `pi-api` are new standing billable
resources (estimate ≈ $0–1.5/month, design §9). Create nothing until `docs/decision-log.md` has a
coordinator entry naming both resources, me-central1, the scaling limits below, and the estimate
against the remaining $25/month budget.

## 1. What gets created

| Resource | Setting | Why |
|---|---|---|
| Artifact Registry repo `pi-api` | Docker, **me-central1**, cleanup policy `infra/gcp/pi-api-ar-cleanup.json` (keep the last 5 versions, delete the rest) | images stay in-region; storage stays bounded |
| Service account `pi-api@productintelligence-beeb3.iam.gserviceaccount.com` | **no keys**; never the default compute SA | the runtime identity |
| Custom role `piApiObjectReader` | `storage.objects.get` only | reads, never lists (design §9) |
| Bucket IAM binding | `pi-api@` → `piApiObjectReader` on the datasets bucket, conditioned on the `datasets/` prefix | read-only, that prefix only |
| Cloud Run service `pi-api` | **me-central1**, min 0, **max 3**, default concurrency, 1 vCPU, **512Mi**, timeout 30 s, request-based CPU | design §9 |

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

- **Uniform bucket-level access must be on.** IAM conditions on object names need it. If it is
  off, enabling it is a separate change that the coordinator approves first (it disables object
  ACLs on the bucket).
- **Hosting → Cloud Run in me-central1** (design §11 Q1). Confirm that Firebase Hosting rewrites
  can target a me-central1 service. If they can't, stop. The fallback (the web app calls the
  `run.app` URL with CORS) needs a code change and a CSP change, and it is not in this handoff.
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
  --min-instances=0 --max-instances=3 --cpu=1 --memory=512Mi --timeout=30 \
  --cpu-throttling --port=8080 --ingress=all --allow-unauthenticated \
  --set-env-vars="PI_API_FIREBASE_PROJECT=$PROJECT,PI_API_BUCKET=$BUCKET,PI_API_DATASETS=<paths from §2>"
```

- **No `--concurrency`** (default), no `--add-cloudsql-instances`, no `--vpc-connector`, no
  `--set-secrets`. Never set `PI_API_ALLOW_TEST` in production.
- **`--allow-unauthenticated` is deliberate.** Hosting rewrites call the service without an IAM
  identity, so `allUsers` gets `run.invoker`. Every route, unknown paths included, verifies the
  Firebase ID token in the app and fails closed (decision log, 2026-10-01). If an org policy
  (for example domain-restricted sharing) refuses the binding, stop (stop rule).
- The startup probe is the default TCP probe. There are no health routes, by design.

## 7. Hosting rewrite

`infra/firebase.json` already routes `/api/**` to `{serviceId: "pi-api", region: "me-central1"}`
**before** the SPA catch-all `**`. `test_hosting_routes_api_before_the_spa_catch_all` guards the
order and the region. Deploy Hosting only after the service exists:

```sh
firebase deploy --only hosting --project $PROJECT
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
  `jsonPayload.event="pi_api.export"` (uid, view, filters, row count; no row content).
- Check the describe output: `autoscaling.knative.dev/maxScale: '3'`, no `minScale` (or 0), no
  Cloud SQL or VPC annotations, the `pi-api@` account, memory 512Mi.

## 9. Record, roll back, tear down

- Append the resources to `infra/gcp/README.md` (date, settings, cost), as for the backup bucket.
- **Roll back:** `gcloud run services update-traffic pi-api --region=$REGION --to-revisions=<previous>=100`.
- **Tear down** (reverse order): `firebase.json` rewrite removed and Hosting redeployed; `gcloud run
  services delete pi-api`; remove the bucket binding; `gcloud iam roles delete piApiObjectReader`;
  `gcloud iam service-accounts delete pi-api@…`; `gcloud artifacts repositories delete pi-api`.
