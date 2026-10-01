# Demo app on Firebase (productintelligence-beeb3)

Live state, created 2026-09-30. Record every change here; nothing is click-ops.

| Piece     | State |
|-----------|-------|
| Hosting   | site `productintelligence-beeb3` → https://productintelligence-beeb3.web.app; config in `firebase.json` (`hosting.public = web-dist`, the static build copied in at deploy time, never committed; SPA rewrite; `noindex` + security headers) |
| Auth      | Identity Platform initialised; email/password only; **self sign-up and self-deletion disabled**. Users are invited with `scripts/invite_user.py` (no password is ever set; Firebase emails a reset link, valid 1 h). Access = custom claim `role` ∈ {admin, viewer}; `killswitch` is the one budget kill-switch account (no data access) |
| Firestore | `(default)`, Standard, **me-central1** (permanent). Rules: clients read `demo_*` only when invited; no client writes |
| Storage   | `productintelligence-beeb3.firebasestorage.app`, **me-central1**. Rules: clients read `datasets/**` only when invited; no client writes. Small non-free-tier cost accepted (a few MB → < $0.05/month) |
| Web app   | registered as `pi-demo-web`; the page loads its config from Hosting's `/__/firebase/init.js` so no key is committed |

Enabled APIs: firestore, firebasestorage, identitytoolkit, firebasehosting, firebaserules (plus the billing APIs listed in `gcp/README.md`).

## Runbook (SA key mounted read-only; never copied into an image or the repo)

```sh
# rules + hosting (from infra/, with the web build in infra/web-dist/)
firebase deploy --project productintelligence-beeb3 --only firestore:rules,storage,hosting
# publish a dataset (validate first with --dry-run). The schema picks the layout:
#   pi.dataset/v1 -> datasets/uae/ + demo_meta/current (what the dashboard reads today)
#   pi.dataset/v2 -> datasets/<country>/<scope>/ + demo_meta/v2_<country>_<scope> (ADR-0007 §6)
# Until the dashboard moves to v2, publish both files from the same export.
uv run --script infra/scripts/publish_dataset.py --project productintelligence-beeb3 <file.json>
# invite users: emails on stdin, one per line; add --no-email to create without sending
uv run --script infra/scripts/invite_user.py --project productintelligence-beeb3 --role viewer < emails.txt
```

## Also applied 2026-09-30

- Bucket CORS from `storage.cors.json` (GET from the two Hosting origins):
  `gcloud storage buckets update gs://productintelligence-beeb3.firebasestorage.app --cors-file=infra/storage.cors.json`
- Browser API key ("auto created by Firebase", 27 Firebase API targets) restricted to HTTP referrers
  `https://productintelligence-beeb3.web.app/*` and `https://productintelligence-beeb3.firebaseapp.com/*`
  (apikeys.googleapis.com enabled for this).
- Hashed `*.js`/`*.css` served with `max-age=31536000, immutable`; `*.html`/`*.json` with `no-cache`.
- Secret `pi-proxy-iproyal-ae` (created by the owner; value never read): resource-level binding
  `roles/secretmanager.secretAccessor` for `serviceAccount:firebase-adminsdk-fbsvc@productintelligence-beeb3.iam.gserviceaccount.com`
  only (the crawl identity). No project-level secretAccessor binding exists.
  `gcloud secrets add-iam-policy-binding pi-proxy-iproyal-ae --member=serviceAccount:<sa> --role=roles/secretmanager.secretAccessor`
  Caveat: project-level `roles/owner` (this SA and the owner) still implies access; a dedicated crawl SA
  without Owner would make this binding the only path.

## Rules parity (checked 2026-09-30 via firebaserules.googleapis.com releases)

| Release | Deployed ruleset | Updated (UTC) | sha256[:16] live | sha256[:16] repo |
| --- | --- | --- | --- | --- |
| `cloud.firestore` | `rulesets/4000bcde-2291-4089-bca9-2d49ca04b800` | 2026-09-30 21:15:46 | `021f754d901855c2` | `021f754d901855c2` (`firestore.rules`) |
| `firebase.storage/productintelligence-beeb3.firebasestorage.app` | `rulesets/fbab556b-8abb-44d9-bccc-448a5afc5cd2` | 2026-09-30 21:15:43 | `798b55374f6d9dfb` | `798b55374f6d9dfb` (`storage.rules`) |

After this PR merges, rules are redeployed only from `main` (`firebase deploy --only firestore:rules,storage`).

## Rules tests

`infra/tests/test_rules_emulator.py` checks both rule files against the Firestore/Storage emulators
(CI job `firebase-rules`, 0 skips allowed). It covers: anonymous, no-role and unknown-role users
denied; viewer/admin may read `demo_meta/*` and `datasets/**` only; no client writes. Run it locally with:

    npx -y firebase-tools@14 emulators:exec --config infra/firebase.json --project demo-pi \
        --only firestore,storage "uv run pytest infra/tests -m emulator"

## Follow-ups (after the demo)

- Dedicated crawl service account without Owner, holding only the resource-level
  `secretAccessor` on `pi-proxy-iproyal-ae` (approved by the Coordinator; no IAM churn before the demo).
