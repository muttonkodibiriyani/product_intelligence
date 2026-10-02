"""One-off Gulf-egress access probe for sephora.me (AE) and ulta.ae (task 01a0f3d2-fb2d).

Ordinary access only (ADR-0005 and the owner's ladder ruling): plain HTTP with normal headers
(rung 1) and a real Playwright browser (rung 2) from Cloud Run in ``me-central1`` (rung 4).
No TLS impersonation, no stealth browser, no challenge solving, no cookie reuse.
"""
