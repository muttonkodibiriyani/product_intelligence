# Ryzan AI Assistant: owner-run enablement runbook

Owner-run, in one pass. **Run the sections in order; stop on any failed verify and report to
the Coordinator.** Agents never enable, create or deploy anything. Source of truth for the reasoning:
`docs/design/ai-assistant.md` §6, §9.4, §10 and §10.1. This runbook only orders those steps and
adds a verify and an off path to each.

- Project: **productintelligence-beeb3 only.** Region: `me-central1`.
- Values in `<ANGLE_BRACKETS>` are filled in by the owner at run time. No secret is written in
  this document, in the repo or in a shell argument; secrets are typed into prompts or stdin.
- The Firebase CLI is always the pinned `npx -y firebase-tools@14.27.0`.
- The assistant stays **off** throughout: `assistant_config/current` is seeded with
  `enabled: false`, and the chat callable is not deployed until the switch-on block (section 10),
  which is handed over separately.

```sh
export PROJECT=productintelligence-beeb3
gcloud config set project "$PROJECT"
gcloud services list --enabled --format="value(config.name)" | sort > enabled-before.txt
```

Keep `enabled-before.txt`: it is the rollback list for the API sections.

**Instant off, at any point after section 5:** in the Firebase console, set
`assistant_config/current.enabled` to `false`. The meter re-reads it before every model call.

---

## 1. Billing currency and budget topic (§9.4 steps 0–1)

```sh
# Only the ones missing from enabled-before.txt.
gcloud services enable pubsub.googleapis.com secretmanager.googleapis.com
gcloud pubsub topics create pi-budget-alerts \
  --message-storage-policy-allowed-regions=me-central1
```

Console: *Billing → Budgets & alerts → pi-monthly-25usd → Manage notifications → Connect a
Pub/Sub topic → pi-budget-alerts*. Do **not** use `gcloud billing budgets update
--notifications-rule-pubsub-topic`: it rewrites the notification rule and can drop the
50/90/100 % email alerts.

Record:

- `<CURRENCY>`: the billing account's ISO 4217 currency (*Billing → Account management*). The
  budget's amounts are in it. It also goes in the decision log.
- `<BUDGET_ID>`: the budget's UUID in lower case (the last segment of its resource name, shown
  in the console URL of the budget).
- `<BUDGET_AMOUNT>`: the budget amount in `<CURRENCY>`.

The owner reads every report and billing figure in **AED**. If `<CURRENCY>` is AED, the budget
is about AED 91.81 (the $25 total cap). If it is USD, write the AED equivalent next to each
amount you record, at the fixed peg of 3.6725 AED per USD.

The kill switch holds no amount of its own. It trips when the budget message's
`costAmount / budgetAmount` reaches **90 %** (`THRESHOLD_PCT`), both in `<CURRENCY>`: about
AED 82.63 of AED 91.81, or $22.50 of $25. Only that ratio matters. The section 6 test publishes
95 %, so `disabledBy` reads `95%`. `KILL_SWITCH_CURRENCY=<CURRENCY>` is used for one
thing only: a message in any other currency turns the assistant off (fail closed).

**Verify**

- The budget still shows the 50/90/100 % thresholds and the email recipients.
- `gcloud pubsub topics get-iam-policy pi-budget-alerts` lists only the billing budget
  publisher grant the console added. Any other publisher is removed.

**Off / rollback:** disconnect the topic in the budget's *Manage notifications*, then
`gcloud pubsub topics delete pi-budget-alerts`.

## 2. APIs for the Functions deploy (§9.4 step 0, §10)

```sh
# Only the ones missing from enabled-before.txt.
gcloud services enable cloudfunctions.googleapis.com run.googleapis.com \
  cloudbuild.googleapis.com artifactregistry.googleapis.com eventarc.googleapis.com
```

This is an explicit step because the Firebase CLI deploy would otherwise enable them silently.
`aiplatform` (Vertex) is **not** enabled here; see section 9.

**Verify:** `gcloud services list --enabled --format="value(config.name)" | sort | diff
enabled-before.txt -` shows only the APIs from sections 1–2.

**Off / rollback:** `gcloud services disable <API>` for each API added here that is not in
`enabled-before.txt`. Only after the functions in section 5 are deleted, because disabling them
breaks a deployed function.

**NEVER disable `run`, `artifactregistry` or `cloudbuild`, even if the diff seems to show them.
pi-api runs on Cloud Run with images in Artifact Registry, so they were enabled before this
runbook. Disabling `run` takes pi-api down.**

## 3. Kill-switch identity: SA, Auth account, secret (§9.4 steps 2–3)

```sh
gcloud iam service-accounts create pi-killswitch --display-name="PI budget kill switch"
```

No roles and no key. Create the Auth account with the claim and the reset email (the email is
read from stdin, so it stays out of argv and shell history):

```sh
uv run --script infra/scripts/invite_user.py --project "$PROJECT" --role killswitch
# type <KILLSWITCH_EMAIL> (an owner-controlled mailbox), Enter, then Ctrl-D
```

The owner sets the password from the reset email, so nobody else sees it. Store it as the
first version of the secret. It is typed at the prompt, never on the command line:

```sh
gcloud secrets create KILL_SWITCH_PASSWORD \
  --replication-policy=user-managed --locations=me-central1
read -rs PW && printf '%s' "$PW" | gcloud secrets versions add KILL_SWITCH_PASSWORD --data-file=- \
  && unset PW
gcloud secrets add-iam-policy-binding KILL_SWITCH_PASSWORD \
  --member="serviceAccount:pi-killswitch@$PROJECT.iam.gserviceaccount.com" \
  --role=roles/secretmanager.secretAccessor
```

**Single-account check.** Exactly one user holds `role: killswitch`. Run it with the same
credentials as `invite_user.py` (see its docstring). It prints only a count and uids. No email
is ever echoed or logged, not even masked: a masked email still shows the domain.

```sh
uv run --with firebase-admin python - "$PROJECT" <<'PY'
import sys, firebase_admin
from firebase_admin import auth
firebase_admin.initialize_app(options={"projectId": sys.argv[1]})
hits = [u.uid for u in auth.list_users().iterate_all()
        if (u.custom_claims or {}).get("role") == "killswitch"]
print(len(hits), hits)
PY
```

**Verify**

- The check prints `1` and one uid. Record it as `<KILLSWITCH_UID>`.
- `gcloud projects get-iam-policy "$PROJECT" --flatten=bindings
  --filter="bindings.members:pi-killswitch@" --format="value(bindings.role)"` prints nothing.
- `gcloud secrets get-iam-policy KILL_SWITCH_PASSWORD` shows only `pi-killswitch@` as
  `secretAccessor`.
- `gcloud iam service-accounts keys list --iam-account=pi-killswitch@$PROJECT.iam.gserviceaccount.com
  --managed-by=user` lists no keys.

If the count is not 1, stop. With 0, the switch cannot sign in. With more than 1, disable each
extra account, remove its claim and find out how it was set.

**Off / rollback:** disable the Auth account (sign-in then fails and the function logs
`kill_switch_failed`). Disable the secret's versions, then delete the SA.

## 4. API-key check and config seed (§9.4 step 4, corrected: seed with `enabled: false`)

**API key check.** The switch signs in server-side and sends no `Referer`. Use the project's Web
API key as `<WEB_API_KEY>` only if it has **no application restriction** and either no API
restriction or one that includes `identitytoolkit.googleapis.com`:

```sh
gcloud services api-keys list --format="table(uid,displayName)"
gcloud services api-keys describe <KEY_UID> --format="yaml(restrictions)"
```

Otherwise stop. A dedicated key restricted to `identitytoolkit` is a new resource and needs OK.

**Seed `assistant_config/current`** in the Firebase console (*Firestore → Start collection
`assistant_config` → document id `current`*). It must exist before the first alert: the rules
only allow an update. The document is a full, schema-valid config (`AssistantConfigSchema`),
so switch-on only flips `enabled`. Types matter: USD amounts are **strings**, counts and limits
are **numbers**.

| Field | Type | Value |
|---|---|---|
| `enabled` | boolean | `false` |
| `model` | string | `gemini-2.5-flash` |
| `promptVersion` | string | `chat-2026-10-01.3` (must equal `PROMPT_VERSION` in `apps/assistant/src/flows/prompt.ts` on the deployed commit; re-checked in the section 10 version pre-check) |
| `priceTableVersion` | string | `2026-09-30-planning` (must equal `version` in `apps/assistant/config/prices.json`) |
| `caps.monthUsd` | string | `5.00` |
| `caps.labelMonthUsd.ci` | string | `1.50` |
| `caps.labelDayUsd.chat` | string | `0.40` |
| `caps.questionsPerUserDay.viewer` | number | `40` |
| `caps.questionsPerUserDay.admin` | number | `150` |
| `limits.maxInputTokens` | number | `10000` |
| `limits.maxOutputTokens` | number | `1500` |
| `limits.thinkingBudget` | number | `500` |
| `limits.maxModelCallsPerQuestion` | number | `4` |

No `disabledBy` field. The caps are the design's (§9.3: $5 a month, $0.40 a day, CI $1.50, 40/150
questions a day), and the four `limits` are the meter's tested defaults. Both are accepted by
the Coordinator **on the condition that they stay inside the owner's $5/month AI slice**. The
meter enforces `caps.monthUsd = 5.00` before every call, across every label, CI included.
Raising any of them needs the owner's OK.

The config stays in USD because the meter prices tokens from a USD list-price table
(`apps/assistant/config/prices.json`). The owner reads the caps in AED, at the fixed peg of
3.6725 AED per USD:

| Cap | AED (displayed) | USD (config) |
|---|---|---|
| Total GCP, all services | AED 91.81 | $25.00 |
| AI month, every label (`caps.monthUsd`) | AED 18.36 | $5.00 |
| CI month (`caps.labelMonthUsd.ci`) | AED 5.51 | $1.50 |
| Chat day (`caps.labelDayUsd.chat`) | AED 1.47 | $0.40 |

**Verify:** the document shows exactly these fields and types.

**Off / rollback:** delete the document (a missing config means disabled; the kill switch then
fails and retries until section 5 is undone).

## 5. Rules and the kill-switch function (§9.4 step 4)

The env file is gitignored. Write it from the template; it holds no secret (the password is the
Secret Manager secret):

```sh
cp apps/assistant/.env.example apps/assistant/.env.productintelligence-beeb3
# Fill in KILL_SWITCH_BUDGET_ID=<BUDGET_ID>, KILL_SWITCH_CURRENCY=<CURRENCY>,
# KILL_SWITCH_API_KEY=<WEB_API_KEY>, KILL_SWITCH_EMAIL=<KILLSWITCH_EMAIL>.
# Leave the PI_* chat lines empty.
git status --short apps/assistant   # must NOT list the .env file
```

`KILL_SWITCH_EMAIL` ends up as a plain env var on the `budgetkillswitch` Cloud Run revision,
readable by anyone with `run.viewer`. That is accepted: it is an owner mailbox, not a secret.
The password stays in Secret Manager.

**Rules are pinned.** `deploy --only firestore:rules` replaces the WHOLE live ruleset. Record:

- `<RULES_SHA>`: the main commit with the assistant rules, which is the one you deploy from;
- `<PREV_SHA>`: the main commit whose `infra/firestore.rules` is live today.

Before deploying, open *Firebase console → Firestore → Rules* and check that the live ruleset
equals `git show <PREV_SHA>:infra/firestore.rules`. If it differs (drift), stop and report: the
deploy would silently overwrite the live change.

```sh
git fetch origin && git checkout --detach <RULES_SHA>
npm ci --prefix apps/assistant
npx -y firebase-tools@14.27.0 deploy --config infra/firebase.json \
  --project productintelligence-beeb3 --only firestore:rules
npx -y firebase-tools@14.27.0 deploy --config apps/assistant/firebase.json \
  --project productintelligence-beeb3 --only functions:assistant:budgetKillSwitch
```

A missing or malformed env value makes the revision refuse to start. The error names the
variable, never its value.

**Image cleanup.** The first Functions deploy creates the Artifact Registry repo `gcf-artifacts`
in `me-central1`. Images build up with every deploy, and storage over 0.5 GB is billed. Set a
cleanup policy once, after the first deploy:

```sh
npx -y firebase-tools@14.27.0 functions:artifacts:setpolicy --location me-central1 --days 7 \
  --project productintelligence-beeb3
```

If 14.27.0 does not know that command, use the keep-2-most-recent policy instead:

```sh
cat > gcf-cleanup.json <<'JSON'
[{"name": "keep-2", "action": {"type": "Keep"}, "mostRecentVersions": {"keepCount": 2}},
 {"name": "delete-rest", "action": {"type": "Delete"}, "condition": {"tagState": "ANY"}}]
JSON
gcloud artifacts repositories set-cleanup-policies gcf-artifacts --location=me-central1 \
  --policy=gcf-cleanup.json --no-dry-run
```

**Verify**

- The deploy reports `budgetKillSwitch(me-central1)` created, and the function's log shows no
  `refusing to start`.
- `gcloud run services get-iam-policy budgetkillswitch --region=me-central1` grants
  `roles/run.invoker` only to the Eventarc trigger's service account.
- **Runtime identity.** The code pins `pi-killswitch@`; prove the deploy honoured it:
  `gcloud run services describe budgetkillswitch --region=me-central1
  --format='value(spec.template.spec.serviceAccountName)'` prints
  `pi-killswitch@productintelligence-beeb3.iam.gserviceaccount.com`. If it shows the compute
  default service account, delete the function (off path below) and stop. The CLI would also
  have granted the secret to that account.
- Re-run section 3's secret check **now**, after the deploy: `gcloud secrets get-iam-policy
  KILL_SWITCH_PASSWORD` shows only `pi-killswitch@` as `secretAccessor`. Remove any other
  member.
- The live rules equal `infra/firestore.rules` at `<RULES_SHA>` (console *Rules* tab).
- `gcloud artifacts repositories describe gcf-artifacts --location=me-central1` shows a cleanup
  policy.

**Off / rollback:**

```sh
npx -y firebase-tools@14.27.0 functions:delete budgetKillSwitch --region me-central1 \
  --config apps/assistant/firebase.json --project productintelligence-beeb3
```

Rules: roll back to the exact ruleset you checked before the deploy. Either pick that version
in *Firestore → Rules → history*, or `git checkout --detach <PREV_SHA>` and run the same rules
deploy command. Never use "the previous main commit": it may not be what was live.

## 6. Synthetic verify, then leave it off (§9.4 step 5)

Publish a hand-built notification at 95 % of the budget, as the owner. It must be fresh (under
6 h) and carry the real `budgetId`:

```sh
gcloud pubsub topics publish pi-budget-alerts \
  --attribute=budgetId=<BUDGET_ID>,schemaVersion=1.0 \
  --message='{"budgetDisplayName":"pi-monthly-25usd","costAmount":<0.95_x_BUDGET_AMOUNT>,"costIntervalStart":"<YYYY-MM>-01T00:00:00Z","budgetAmount":<BUDGET_AMOUNT>,"budgetAmountType":"SPECIFIED_AMOUNT","currencyCode":"<CURRENCY>"}'
```

Use the recorded `<BUDGET_AMOUNT>` and `<CURRENCY>` exactly: if the billing account is in AED,
that is about 91.81 with `"currencyCode":"AED"`. Never type 25 just because the budget is named
`pi-monthly-25usd`; the name is only a label. The kill switch compares `costAmount` with
`budgetAmount` as a ratio, so it works in any currency. A message whose currency differs from
`KILL_SWITCH_CURRENCY` turns the assistant **off** (fail closed, design §9.4), because the
threshold can no longer be trusted.

**Verify**

- `assistant_config/current` now has `disabledBy = "budget_alert:95%:<YYYY-MM>"` and
  `enabled: false`. The config was seeded `false`, so the new `disabledBy` is the proof of the
  write.
- `gcloud logging read 'resource.type="cloud_run_revision" AND
  resource.labels.service_name="budgetkillswitch"' --limit=20 --freshness=1h` shows
  `kill_switch_disabled` and nothing secret: no password, no ID token, no API key.
- Re-run the single-account check (section 3): `1`.

Then, as admin in the console, **delete the `disabledBy` field** and keep `enabled: false`.
**Verify** that `enabled` is still `false` afterwards.

**Off / rollback:** nothing to undo. If the flag did not appear, check the log for
`kill_switch_failed` or `kill_switch_ignored`, and stop.

## 7. Chat runtime identity: `pi-assistant@` (§6, §10)

`roles/aiplatform.user` is too broad: it can create endpoints, tuning and batch jobs and other
billable resources. Gemini `generateContent` and `countTokens` on publisher models need only
`aiplatform.endpoints.predict`, so create a custom role with exactly that permission (custom
roles are free):

```sh
gcloud iam roles create piAssistantVertex --project="$PROJECT" \
  --title="PI assistant: Gemini predict" --permissions=aiplatform.endpoints.predict --stage=GA
gcloud iam service-accounts create pi-assistant --display-name="PI assistant runtime"
for ROLE in "projects/$PROJECT/roles/piAssistantVertex" roles/datastore.user; do
  gcloud projects add-iam-policy-binding "$PROJECT" \
    --member="serviceAccount:pi-assistant@$PROJECT.iam.gserviceaccount.com" --role="$ROLE" \
    --condition=None
done
```

Exactly these two roles. No Secret Manager access, no key, and no Storage role (reports are
stage 2). `datastore.user` is **database-wide**: Firestore IAM has no collection-level scope.
The code limits it to the assistant's collections, and a test pins their names. That is the
accepted state. A named Firestore database was considered and closed: Firestore's free quota
applies only to `(default)`, so a named database is billed from its first read.

**Verify:** `gcloud projects get-iam-policy "$PROJECT" --flatten=bindings
--filter="bindings.members:pi-assistant@" --format="value(bindings.role)"` prints exactly
`projects/productintelligence-beeb3/roles/piAssistantVertex` and `roles/datastore.user`.
`gcloud iam roles describe piAssistantVertex --project="$PROJECT"` lists only
`aiplatform.endpoints.predict`. `keys list --managed-by=user` (as in section
3) lists none.

**Off / rollback:** `gcloud projects remove-iam-policy-binding` for each role, then
`gcloud iam service-accounts disable pi-assistant@$PROJECT.iam.gserviceaccount.com` and
`gcloud iam roles delete piAssistantVertex --project="$PROJECT"`.

## 8. App Check with reCAPTCHA Enterprise (§6, §10)

`assistantChat` is deployed with `enforceAppCheck: true`, so this is **required**: without it,
every chat call is rejected.

```sh
# Only the ones missing from enabled-before.txt.
gcloud services enable recaptchaenterprise.googleapis.com firebaseappcheck.googleapis.com
gcloud recaptcha keys create --display-name="pi-web-appcheck" --web \
  --integration-type=score \
  --domains=productintelligence-beeb3.web.app,productintelligence-beeb3.firebaseapp.com
```

Add any custom domain the app is served from to `--domains`. Record the printed key id as
`<RECAPTCHA_SITE_KEY>`. A site key is public by design (it ships in the web page), but it still
stays out of the repo. It goes into the web build env `NEXT_PUBLIC_RECAPTCHA_SITE` at
switch-on.

Firebase console: *App Check → Apps → the web app → reCAPTCHA Enterprise → paste
`<RECAPTCHA_SITE_KEY>` → Save*. **Do not press "Enforce"** for Firestore, Storage or
Authentication. The current web app does not send App Check tokens yet, and console enforcement
would lock it out. The callable enforces in code.

**Verify:** App Check shows the web app as registered with reCAPTCHA Enterprise. The *APIs* tab
shows every product as **Unenforced**. `gcloud recaptcha keys list` shows the key with the two
domains. After switch-on, check *Security → reCAPTCHA → the key → Assessments*: the free tier
is 10,000 assessments a month, and App Check refreshes about one token per user per hour, so
usage should stay far below it.

**Off / rollback:** unregister the app's provider in App Check, then `gcloud recaptcha keys
delete <RECAPTCHA_SITE_KEY>`.

## 9. TTL policies and Vertex (§6, §10, §10.1)

**TTL** (90-day retention on `expireAt`). Infra adopts TTL as code
(`infra/firestore.indexes.json` field overrides, in its switch-on PR). Until that lands, run the
loop below. Both end in the same state, and a later `deploy --only firestore:indexes` from the
file is idempotent. TTL deletes count as normal deletes (free tier 20,000 a day on
`(default)`).

```sh
for G in assistant_usage_counters assistant_reservations assistant_threads assistant_messages; do
  gcloud firestore fields ttls update expireAt --collection-group="$G" --enable-ttl --async
done
```

**Verify:** `gcloud firestore fields ttls list` shows all four groups `ACTIVE` (it can take a
few minutes).
**Off / rollback:** the same loop with `--disable-ttl`.

**Vertex.** The owner approved enabling it in this one pass. Run it only after sections 5–6
verify (§10.1 items 1–2: #51 and the kill switch are merged, the owner's $5 alert is set, and
the kill switch is deployed and proven):

```sh
gcloud services enable aiplatform.googleapis.com
```

Enabling the API costs nothing; spend starts only with model calls, and none happen until
switch-on.

**Location probe (zero cost).** `countTokens` is not billed and runs no generation. As the
owner (the token goes through stdin, never argv):

```sh
gcloud auth print-access-token | sed 's/^/Authorization: Bearer /' | curl -sS -o probe.json \
  -w '%{http_code}\n' -H @- -H 'Content-Type: application/json' -X POST \
  "https://me-central1-aiplatform.googleapis.com/v1/projects/$PROJECT/locations/me-central1/publishers/google/models/gemini-2.5-flash:countTokens" \
  -d '{"contents":[{"role":"user","parts":[{"text":"ping"}]}]}'
```

- `200`: record `<VERTEX_LOCATION>=me-central1`.
- `404`, or "not found" / "not supported in location" in `probe.json`: **stop**. Infra names
  the nearest region, with the data-residency note, for the owner to decide. Prompts and tool
  results (product data, never user PII beyond the uid) would then be processed outside
  `me-central1`. Never pick `global` or a `europe-west*` region silently.
- Any other code (e.g. `403`: the API is not enabled yet or a permission is missing; `429`;
  `5xx`): **stop and report** to Infra. It does not mean "not served".

Also check *Model Garden → Gemini 2.5 Flash* for its retirement date before switch-on. If it is
within 3 months, stop: `config.model` must change first (Coordinator decision).

**Verify:** `gcloud services list --enabled --filter=config.name=aiplatform.googleapis.com`, and
the probe returned `200`.
**Off / rollback:** `gcloud services disable aiplatform.googleapis.com`.

## 10. Switch-on (handed over separately)

Not part of this handover. It will hold:

- the chat env lines (`PI_API_BASE_URL`, `PI_VERTEX_LOCATION=<VERTEX_LOCATION>`,
  `PI_EVIDENCE_HOSTS`);
- Infra's switch-on PR merged and deployed: the CSP origins for the callable, App Check and
  reCAPTCHA, plus TTL as code;
- the `functions:assistant:assistantChat` deploy, then the runtime-identity check as in section
  5: `gcloud run services describe assistantchat --region=me-central1
  --format='value(spec.template.spec.serviceAccountName)'` prints `pi-assistant@…`, otherwise
  delete it and stop;
- the web build with `NEXT_PUBLIC_ASSISTANT_ENABLED=true` and `NEXT_PUBLIC_RECAPTCHA_SITE`;
- the §10.1 checklist re-run;
- the version pre-check below, then flipping `enabled` to `true`;
- a one-question smoke as a viewer, with its metered cost read back. The meter reports USD;
  write it as `AED x.xx (USD y.yy)` at 3.6725.

Its off path is the instant off above, then deleting `assistantChat`.

**Version pre-check (before flipping `enabled`).** The assistant refuses every question with
`prompt_version_mismatch` (or `price_table_mismatch`) when the config does not match the
deployed code. The value seeded in section 4 can be stale: each prompt change bumps it. Run this
in the exact checkout you deployed `assistantChat` from:

```bash
git rev-parse --short HEAD    # the deployed commit; note it
grep -o 'PROMPT_VERSION = "[^"]*"' apps/assistant/src/flows/prompt.ts
grep -o '"version": *"[^"]*"' apps/assistant/config/prices.json
```

In the Firebase console, set `assistant_config/current.promptVersion` to exactly the quoted
`PROMPT_VERSION` value, and `priceTableVersion` to exactly the quoted `version` value. Copy each
one; do not retype it.

**Verify:** both fields equal the grep output character for character, and `enabled` is still
`false`. Only then flip `enabled`.

**Off:** set `enabled` to `false`. A mismatch only refuses questions, so nothing is spent.
