# ADR-0004: Market fallback KSA → UAE

- Status: accepted (owner decision)
- Date: 2026-09-30

## Context
The pilot targets KSA. Ulta's Gulf roll-out started in UAE, and a KSA source may be blocked
or incomplete.

## Decision
Every source is attempted for KSA first through all free ladder rungs. If KSA cannot be
collected reliably, that source runs for UAE automatically and the pilot continues on UAE data.
KSA stays `pending` with its reason on the coverage screen and is retried weekly. When both
markets work, both are collected.

## Consequences
The market is configuration on the source context; no code path is KSA-specific.
