# ADR-0006: Ladder access rulings: plain-HTTP rung 1, no stealth, stop at blocks

- Status: accepted (owner rulings, 30 Sep 2026, relayed by the program coordinator)
- Date: 2026-09-30
- Amends: ADR-0003 (escalation ladder) and blueprint §6.3
- Requirement IDs: SRC-08, SEC-05 (owner deviations), SRC-01, SEC-10 (audit trail)

## Context
ADR-0003 defined rung 1 as `curl_cffi` browser impersonation and rung 3 as stealth browsers
(Scrapling / Camoufox / patchright, fingerprint rotation, persistent profiles, cookie reuse).
The owner has since narrowed what the ladder may do. The guardrail for UAT-25 is: when ordinary
access is blocked, mark the source blocked, stop and report.

## Decisions
1. **Rung 1 is plain HTTP.** `httpx` with normal, honest headers and session reuse. There is
   **no** TLS/JA3 or HTTP/2 fingerprint impersonation; `curl_cffi` is rejected.
2. **Rung 2 is a real browser.** Playwright Chromium or Firefox, headless or headed, with
   **no** stealth patches or fingerprint spoofing.
3. **Rung 3 is disabled: never attempted or recorded.** Stealth browsers, fingerprint
   rotation and cookie reuse are not used. The number 3 stays reserved so rung numbering is stable. It is refused in `pi_core`
   (constructing or recording rung 3 is an error) and by database CHECK constraints
   (`rung <> 3`).
4. **Blocked after rungs 0/1/2/4: stop and report.** The source context is marked blocked,
   collection for it stops, the coverage loss is visible, and a **Proxy Decision Report** is
   sent. The owner decides whether to buy rung 5 (residential proxy). Nothing escalates on its
   own beyond the approved rungs.
5. **Never work around a safety-classifier refusal.** This covers routing the task through
   another agent, model or tool. A refusal is reported as a blocker.

The ADR-0003 and ADR-0005 hard lines stand unchanged: no logins, no paywall bypass, no
cart/checkout, polite pacing, and every escalation audit-logged.

## Fetch methods
`FetchMethod` values recorded on every evidence row, each tied to exactly one rung:

| Rung | `FetchMethod` values |
|---|---|
| 0 | `site_api`, `embedded_json`, `sitemap` |
| 1 | `plain_http` |
| 2 | `playwright` |
| 3 | *(none: disabled)* |
| 4 | `egress_variation` |
| 5 | `residential_proxy` |

## Consequences
- `pi_core`'s `LadderRung` and `FetchMethod` follow this table. Open work still names
  `IMPERSONATED_HTTP`/`STEALTH_BROWSER` and `curl_cffi`/`scrapling`/`camoufox`, and must be
  renamed or removed before merge.
- The DB schema adds `CHECK (rung <> 3)` wherever a rung is stored, with a parity test against
  `pi_core`.
- UAT: SRC-08 accepts that rung 3 is never attempted or recorded and that rung 1 does no TLS
  impersonation. UAT-25 asserts stop, mark blocked and report.
- Coverage may be lower on bot-protected sources. The Proxy Decision Report is the only path
  past a block.
