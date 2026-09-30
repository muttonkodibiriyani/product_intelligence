# Demo app on Firebase (productintelligence-beeb3)

Live state, created 2026-09-30. Record every change here; nothing is click-ops.

| Piece     | State |
|-----------|-------|
| Hosting   | site `productintelligence-beeb3` → https://productintelligence-beeb3.web.app; config in `firebase.json` (`hosting.public = web-dist`, the static build copied in at deploy time, never committed; SPA rewrite; `noindex` + security headers) |
| Auth      | Identity Platform initialised; email/password only; **self sign-up and self-deletion disabled**. Users are invited with `scripts/invite_user.py` (no password is ever set; Firebase emails a reset link, valid 1 h). Access = custom claim `role` ∈ {admin, viewer} |
| Firestore | `(default)`, Standard, **me-central1** (permanent). Rules: clients read `demo_*` only when invited; no client writes |
| Storage   | `productintelligence-beeb3.firebasestorage.app`, **me-central1**. Rules: clients read `datasets/**` only when invited; no client writes. Small non-free-tier cost accepted (a few MB → < $0.05/month) |
| Web app   | registered as `pi-demo-web`; the page loads its config from Hosting's `/__/firebase/init.js` so no key is committed |

Enabled APIs: firestore, firebasestorage, identitytoolkit, firebasehosting, firebaserules (plus the billing APIs listed in `gcp/README.md`).

## Runbook (SA key mounted read-only; never copied into an image or the repo)

```sh
# rules + hosting (from infra/, with the web build in infra/web-dist/)
firebase deploy --project productintelligence-beeb3 --only firestore:rules,storage,hosting
# publish a dataset (validate first with --dry-run)
uv run --script infra/scripts/publish_dataset.py --project productintelligence-beeb3 <file.json>
# invite users: emails on stdin, one per line; add --no-email to create without sending
uv run --script infra/scripts/invite_user.py --project productintelligence-beeb3 --role viewer < emails.txt
```
