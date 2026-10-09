# pi-compare

Pure contracts and normalisers for the evidence-backed cross-retailer comparison projection.

The package is deliberately independent of collection and serving. It preserves each retailer
SKU and raw value, adds canonical display/comparison values with provenance, and makes absence,
unknown, conflict and invalid states explicit. It also owns exact Decimal discount arithmetic,
the non-boolean retailer presence matrix, profile-driven attribute validation and the append-only
image-description sidecar contract.

`build_projection` adds the deterministic read model over `pi.dataset/v3` and an optional
`pi.matches/v1` file. Approved/locked exact or family evidence and a retailer's own family id
form families; proposed edges only produce auditable `ambiguous` cells. The caller must provide
an explicit completeness decision and basis for every retailer before the builder can emit
`absent`. Each listing retains every SKU, raw/canonical axis, context-level current/original
price, Decimal discount, public availability state, first-observed launch evidence and capture
timestamp.

It does not fetch retailer pages, infer inventory quantities, convert currencies, merge source
records or let generated image text affect product identity.

```bash
uv run ruff check packages/pi_compare
uv run mypy packages/pi_compare/src packages/pi_compare/tests
uv run pytest packages/pi_compare/tests
```

The family projection builder, read API and web view land in later slices described in
[`docs/design/cross-retailer-comparison.md`](../../docs/design/cross-retailer-comparison.md).
