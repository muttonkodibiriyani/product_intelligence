# Recon: Ulta Beauty Middle East Android app (`com.ub.mena`)

- **Status:** stopped at the official-package acquisition gate; no app binary was installed or run.
- **Date:** 2026-09-30
- **Scope:** guest-only observation of the official, unmodified Android app with a user-installed
  mitmproxy CA. No account, login, cart, checkout, patching, root, system-CA installation, hooking,
  Frida, decompilation, certificate-pinning bypass or third-party APK archive was allowed.
- **Decision:** the app route is not approved for collection or bulk use. The owner must receive this
  finding before any further attempt.

Every result below is labelled **verified**, **not observed**, or **known from the separate web
probe**. No app endpoint is inferred from the web implementation.

## 1. Outcome

The official Google Play listing is public and identifies the package, title and publisher, but
Google Play does not provide a login-free APK download. No first-party APK download published by
Ulta or Alshaya was found. Third-party APK archives were explicitly prohibited. Therefore there was
no compliant way to obtain a binary whose certificate could be checked with `apksigner` against the
official Play signer.

Per the owner's stop rule, the study ended there. It did **not** substitute a shared/anonymous Google
account, a third-party archive, a modified package or a different app. Consequently:

- app certificate trust of a user-installed CA is **not observed**;
- certificate pinning or proxy refusal is **not observed**;
- runtime hosts, SNI, endpoints, request fields and authentication are **not observed**;
- no app traffic sample, credential, token or identifier was captured; and
- no claim is made that the app shares the web storefront's endpoints.

## 2. Official-package provenance gate

The following token-free metadata was read from the official Google Play listing:

```text
package: com.ub.mena
title: Ulta Beauty Middle East
developer: M.H. Alshaya Co. W.L.L.
store: Google Play
```

The approved signer-baseline plan was to read Ulta's first-party
`/.well-known/assetlinks.json` through stock Playwright WebKit, obeying `robots.txt`, then compare its
`sha256_cert_fingerprints` entry for `com.ub.mena` with
`apksigner verify --print-certs` on a Play-delivered APK. This was not executed because no permitted,
login-free official APK was available to compare. Fetching a signer baseline alone would not make a
third-party download an approved package source.

The next compliant input is an official Play-delivered APK/APKS bundle supplied through an
owner-controlled handoff without an account login, or a first-party Alshaya download. Before any
installation it must satisfy all of these checks:

1. package name is exactly `com.ub.mena`;
2. `apksigner verify --print-certs` succeeds for every installed APK;
3. the signer SHA-256 equals the first-party App Links statement for `com.ub.mena`; and
4. the package is unmodified and no archive/repacking service is involved.

## 3. Emulator and proxy preflight

The worker host had no `/dev/kvm` and exposed no `vmx`/`svm` CPU flag, so a local accelerated Android
emulator was ruled out. With owner approval, one ephemeral GCE `n2-standard-2` VM was created in
`me-central1-a` with nested virtualization, Ubuntu, a 20 GiB `pd-standard` auto-delete boot disk, an
ephemeral IP, no attached service account or scopes, and automatic deletion after six hours.

Nested KVM was **verified** on the VM (`/dev/kvm` present; four `vmx` occurrences). The VM was deleted
as soon as the package gate failed, before installing Android, mitmproxy or the app:

| Item | Result |
|---|---|
| Billable runtime | 113 seconds |
| Estimated metered cost | about **$0.004**; expected billed total **< $0.01** |
| Approved hard cap | $2.00 |
| Remaining VM / boot disk | **0 / 0**, verified after deletion |
| Project SSH metadata | temporary key removed |
| Credentials on VM | none; the read-only local key was never copied |

Enabling the Compute Engine API was required and is free; it remains enabled. No other cloud
resource remains from the study.

Had the package gate passed, the first runtime test would have installed only the mitmproxy CA in
the Android **user** certificate store. Failure to trust that CA would have been classified as proxy
refusal and stopped the study within minutes. A system-CA install, root or pinning bypass was never
an available fallback.

## 4. Hosts, endpoints, fields, auth and pacing

There are no observed app rows to report because the app was not run.

| Surface | App observation | Separate web-probe baseline |
|---|---|---|
| Catalogue API host | **not observed** | `www.ulta.ae` first-party calls |
| Product endpoint | **not observed** | `/graphql` |
| Listing/discovery endpoint | **not observed** | `/en/query-index.json` |
| Promotion endpoint | **not observed** | `/promotion-schedule.json` |
| Product/variant IDs | **not observed** | present in first-party GraphQL payloads |
| Current/original price | **not observed** | present in first-party GraphQL payloads |
| Stock and variants | **not observed** | present in first-party GraphQL payloads |
| Images | **not observed** | present in first-party GraphQL payloads |
| Promotions | **not observed** | web promotion schedule identified |
| Content, ratings, EN/AR | **not observed** | requires the web fixture/connector study |
| App authentication | **not observed** | web route is logged-out catalogue access |

The web baseline above comes from the separate Gulf probe and ADR-0006 Amendment 1. It is included
only as the requested comparison target. It is not evidence about the app.

App reachability from Gulf egress and its safe pacing ceiling are **not observed**. If the study is
resumed with an approved package, start at one interaction/request per second or slower with jitter,
perform only a few guest catalogue interactions, and stop on a block, challenge, classifier refusal,
pinning or proxy refusal. Any later rate must be justified from observed app behaviour; this study
does not authorize bulk use.

## 5. Safety and data handling

- No retailer request was made by an installed app.
- No login, Google account, Ulta account, cart or checkout was used.
- No APK was downloaded from a third party.
- No CA was installed and no TLS interception occurred.
- No token, cookie, authorization header, API key, device identifier or customer data was captured.
- There are no raw app samples to retain or redact. The only sample in this report is the trimmed,
  token-free official Play metadata in section 2.
- No safety classifier refused an action. The stop was the owner's package-provenance rule.

## 6. Recommendation

Keep the app route **paused**. The web route already exposes first-party GraphQL, query-index and
promotion data through the approved stock-WebKit method, subject to `robots.txt` for each path and
the ADR-0006 guardrails. The app study should resume only if the owner supplies a permitted official
binary that can pass the signer checks in section 2. If it resumes, user-CA trust is the first test;
failure ends the attempt without another route.

## Sources

- Official Google Play listing: <https://play.google.com/store/apps/details?id=com.ub.mena>
- Android emulator acceleration (Linux/KVM):
  <https://developer.android.com/studio/run/emulator-acceleration>
- GCE nested virtualization: <https://cloud.google.com/compute/docs/instances/nested-virtualization/overview>
- Access and collection decisions: [ADR-0006](../adr/0006-ladder-access-rulings.md)
- Existing storefront recon: [Ulta ME recon](ulta_me.md)
