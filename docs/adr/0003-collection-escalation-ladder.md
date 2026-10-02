# ADR-0003: Automatic collection escalation ladder, proxy last

- Status: accepted (owner decision, blueprint v1.1); amended by ADR-0006 (rung 1 is plain HTTP, rung 3 disabled, stop and report at blocks)
- Date: 2026-09-30

## Context
Goal is maximum coverage of public catalogue data. Some retailers use bot protection.
Budget is tight. The Alshaya requirements register (SRC-08) asks not to route around blocks;
the owner decided to prioritise coverage instead.

## Decision
Each source context climbs a ladder until data arrives, and remembers its working rung:
0 site data/APIs → 1 curl_cffi impersonation → 2 Playwright → 3 Scrapling/Camoufox/patchright
stealth → 4 egress variation → 5 paid KSA/UAE residential proxy.
*Amended by ADR-0006:* rung 1 is plain HTTP (httpx, no TLS impersonation; `curl_cffi` rejected),
rung 2 uses no stealth patches, and rung 3 is disabled (never attempted or recorded). Where this
ADR says "rungs 0–4", read rungs 0, 1, 2 and 4. If they fail, the source is marked blocked,
collection stops and a Proxy Decision Report goes to the owner. Nothing escalates automatically.
Rung 5 is used only after rungs 0–4 fail and after the owner reviews a Proxy Decision Report
and buys the proxy. Tor is excluded (wrong geography, slow, widely blocked).
Hard lines: no account logins, no password/paywall bypass, no cart/checkout manipulation;
human-like pacing.

## Consequences
Every escalation and all proxy use is written to the audit log, so the collection method of
every observation is transparent. Deviation from SRC-08 is recorded in the traceability matrix.
