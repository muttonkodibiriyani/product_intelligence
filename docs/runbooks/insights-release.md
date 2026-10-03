# Insights release (#231 API, #234 page)

The owner runs this; the Insights lane only prepares it. It ships the `GET /api/v1/insights`
endpoint (#231) and the `/app/{en,ar}/insights/` page (#234). It creates nothing billable: the
pi-api image goes to the existing Artifact Registry repo and Cloud Run service (scale to zero), and
Hosting is the existing site. **Run it only after both PRs are merged to main** and the
Coordinator marks `<MAIN_SHA>` releasable.

Order matters: **API first, then Hosting.** The page calls `/api/v1/insights`; a Hosting release
before the API answers would show the error card on every visit (no wrong numbers, but broken).
The rest of the site does not depend on this order: the old pages call nothing new.

```sh
PROJECT=productintelligence-beeb3
REGION=me-central1
MAIN_SHA=<the releasable main commit>
git fetch origin && git checkout --detach "$MAIN_SHA"
```

## 1. Pre-checks (read-only)

1. CI is green on `$MAIN_SHA` itself: `gh run list --commit "$MAIN_SHA" --workflow ci.yml`.
2. **What ships beyond Insights.** `<LIVE_WEB_SHA>` is the main commit of the last Hosting deploy
   (the deploy record); `<LIVE_API_SHA>` the commit of the live pi-api image tag.

   ```sh
   git log --oneline <LIVE_WEB_SHA>..$MAIN_SHA -- apps/web infra/firebase.json
   git log --oneline <LIVE_API_SHA>..$MAIN_SHA -- packages docs/contracts
   ```

   Anything other than #231, #234 and their rebases ships too. Send the list to the Coordinator
   and go on only once the owner accepts it.
3. **Contract.** `grep -o '"apiVersion": "[^"]*"' docs/contracts/golden/pi-api/insights.json`
   prints `1.17.0` (or later, if a later PR bumped it). `apps/web/lib/api/schema.gen.ts` is
   generated from the same commit (CI `check:api` proved it).

## 2. API: image-only redeploy of pi-api

Follow `docs/runbooks/pi-api-deploy.md` §5 (build and push, tag `$MAIN_SHA`) and the
**image-only** form of §6:

```sh
gcloud run services describe pi-api --project=$PROJECT --region=$REGION \
  --format='value(status.latestReadyRevisionName)'          # note as <PREV_REVISION>
gcloud run deploy pi-api --project=$PROJECT --region=$REGION \
  --image="$REGION-docker.pkg.dev/$PROJECT/pi-api/pi-api@$DIGEST"
```

Never pass `--set-env-vars` here (it would replace the evidence and image host maps).

**Verify** (pi-api-deploy §8, plus):

- Unauthenticated `curl -si https://$PROJECT.web.app/api/v1/insights?retailers=sephora_me,ulta_ae`
  → `401`, `Cache-Control: private, no-store`.
- Signed in, the same URL → `200`, `meta.apiVersion` `1.17.0`, `meta.endpoint` `insights`.
  `data.pricing.status` is `not_enough_data` with `matches_unreviewed` until reviewed exact edges
  are in the published dataset; that is the expected state, not a failure.
- Signed in, `GET /api/v1/meta` still `200` (the rest of the API is unchanged).

**Roll back:** `gcloud run services update-traffic pi-api --project=$PROJECT --region=$REGION --to-revisions=<PREV_REVISION>=100`.

## 3. Hosting: the web export

Exactly as `apps/web/README.md` § Deploy, Linux, Node 22, **no** `NEXT_PUBLIC_*` set.

1. **Record the live release** (for rollback), as in `assistant-enablement.md` §10c step 1; note
   `<LIVE_VERSION>`.
2. **Build and gate:**

   ```sh
   node --version                         # v22.x
   env | grep NEXT_PUBLIC_                # must print nothing
   apps/web/build.sh verify
   (cd apps/web && npm ci && npm run build)
   # must end: csp: N inline script hashes (... in out, out-assistant) match infra/firebase.json
   ls apps/web/out/en/insights/index.html apps/web/out/ar/insights/index.html
   ```

   Do **not** run `csp:write` on the deploy checkout: the hashes are committed with #234 (and
   re-written on its final rebase). A mismatch means the checkout is not `$MAIN_SHA`: stop.
3. **Which export.** Deploy `out/` (assistant off) unless the assistant is live; if it is, follow
   `assistant-enablement.md` §10c step 5 with `out-assistant/` and the site key file instead.

   ```sh
   rm -rf infra/web-dist && cp -r apps/web/dist infra/web-dist && cp -r apps/web/out infra/web-dist/app
   (cd infra && npx -y firebase-tools@14.27.0 deploy --only hosting --project $PROJECT)
   ```

   Re-run step 1: it must print a version other than `<LIVE_VERSION>`.

## 4. Smoke (EN and AR, as a viewer)

Open `https://$PROJECT.web.app/app/en/insights/`, then `/app/ar/insights/`:

- The nav lists **Insights / الرؤى** after Compare; the page loads with no error card and the
  browser console shows no CSP violation.
- The pair defaults to the first two collected shops. Six cards in order: price gap by size,
  brand price policy, assortment white space, promotion strategy, brand stock-outs, size traps;
  then the collapsed **More**.
- Price cards: while matches are unreviewed, each shows the reason and **no number**, and the
  "N unreviewed matches: not counted" chip is visible.
- Stock-outs: rows read "{out} out of stock / {observed} observed"; a partial shop carries the
  "partial crawl" label; **no percentage** anywhere in the card; a brand link opens Products
  filtered to that brand and shop.
- Promotions card: no digits, its link opens `/app/<locale>/promotions/`.
- Arabic: right-to-left layout, Latin digits, no horizontal scroll on a phone width.
- Then the existing dashboard smoke: `infra/scripts/smoke_demo.py` as in its docstring.

## 5. Roll back

- **Page:** in the Hosting console, roll back to `<LIVE_VERSION>` (instant; the API change is
  harmless without the page).
- **API:** §2 roll back. Roll back Hosting first if both go, so no live page calls a missing route.
- Record the deploy (commit, env, result, rollback path) in the deploy record and tell the
  Coordinator.
