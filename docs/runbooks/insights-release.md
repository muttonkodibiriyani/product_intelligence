# Insights release (#231 API, #234 page)

The owner runs this; the Insights lane only prepares it. It ships the `GET /api/v1/insights`
endpoint (#231) and the `/app/{en,ar}/insights/` page (#234). It creates nothing billable: the
pi-api image goes to the existing Artifact Registry repo and Cloud Run service (scale to zero), and
Hosting is the existing site. **Run it only after both PRs are merged to main** and the
Coordinator marks `<MAIN_SHA>` releasable.

Order: **API first, then Hosting.** The page reads `meta.apiVersion` from `/api/v1/meta`. On an
API older than the one that serves Insights, the nav does not list Insights. The page itself shows
only "Insights is not available yet", with no card and no number, and sends no request to
`/insights`, `/compare` or `/assortment-gaps`. If `/meta` reports 1.18.0 but `/insights` answers
404 (the route is not deployed), the page shows the same honest "not available yet", never an
error card. So a Hosting-first release is safe but empty. The
rest of the site does not depend on this order: the old pages call nothing new.

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
   prints `1.18.0` (or later, if a later PR bumped it). `apps/web/lib/api/schema.gen.ts` is
   generated from the same commit (CI `check:api` proved it).

## 2. API: deploy-api.sh, STOP, Reviewer, then traffic-api.sh

Use only the approved scripts, `deploy-api.sh` and `traffic-api.sh`. They live outside the repo with
the release operator. Make no manual `gcloud run deploy` and no `--set-env-vars`.

1. **Deploy without traffic.**

   ```sh
   deploy-api.sh <API_SHA> 1.18.0 <PREV_REVISION>
   ```

   - `<API_SHA>` is the #231 squash commit on `origin/main`. `<PREV_REVISION>` is the revision now
     serving 100 % (`pi-api-00012-8dg` at the time of writing; the script STOPs if it is not).
   - The script checks, and STOPs on any failure:
     - the commit is on `origin/main` and CI is 7/7 at the exact tree;
     - `/` has at least 5 GB free;
     - the built image reports `API_VERSION` 1.18.0.
   - It then builds the image, pushes it once and deploys with `--no-traffic`.
   - It prints `NEWREV` and `DIGEST`. **STOP here.**
2. **Reviewer.** Send `NEWREV`, `DIGEST` and the script output to the Reviewer, and wait for
   their explicit go on that exact revision and digest.
3. **Move traffic only after that go:**

   ```sh
   traffic-api.sh <NEWREV> <DIGEST> <PREV_REVISION>
   ```

**Verify** (owner-run, signed in as a viewer):

- Unauthenticated `curl -si https://$PROJECT.web.app/api/v1/insights?retailers=sephora_me,ulta_ae`
  → `401`, `Cache-Control: private, no-store`.
- Signed in, the same URL → `200`, `meta.apiVersion` `1.18.0`, `meta.endpoint` `insights`.
  `data.pricing.status` is `not_enough_data` with `matches_unreviewed` until reviewed exact edges
  are in the published dataset; that is the expected state, not a failure.
- Signed in, `GET /api/v1/meta` → `200` with `apiVersion` `1.18.0`.

**Roll back:** `traffic-api.sh`'s own rollback line, which moves traffic back to `<PREV_REVISION>`.

## 3. Hosting: the reviewed Hosting runbook v4 only

Hosting ships **only** through the Reviewer-approved Hosting runbook **v4** (Part B), run by the
owner as that runbook says. It pins:

- `WEB_SHA` = the #234 squash commit, gated to the tree of the Reviewer-approved #234 head;
- `LIVE_WEB_SHA` and `ROLLBACK_VERSION`;
- **G5** re-anchored to `API_SHA` = the #231 squash commit served by pi-api 1.18.0, so Hosting
  cannot start until §2 has moved traffic.

This file adds no Hosting command and does not replace any of v4's gates: build, CSP, the
`out/` vs `out-assistant/` choice, deploy and the recorded release version all follow v4. Run v4
only after §2's traffic move.

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
- Then the existing dashboard smoke: `infra/scripts/smoke_demo.py` as in its docstring. All smokes are owner-run.

## 5. Roll back

- **Page:** Hosting runbook v4's rollback to its `ROLLBACK_VERSION`. The API change is harmless
  without the page.
- **API:** §2's roll back. If both go, roll back Hosting first. The page also handles an older
  API (Insights hidden, page says "not available yet"), so either order is safe.
- Record the deploy (commit, env, result, rollback path) in the deploy record and tell the
  Coordinator.
