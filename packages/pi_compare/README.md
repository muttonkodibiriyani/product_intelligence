# pi-compare

Pure contracts and normalisers for the evidence-backed cross-retailer comparison projection.

The package is deliberately independent of collection and serving. It preserves each retailer
SKU and raw value, adds canonical display/comparison values with provenance, and makes absence,
unknown, conflict and invalid states explicit. It also owns exact Decimal discount arithmetic,
the non-boolean retailer presence matrix, profile-driven attribute validation and the append-only
image-description sidecar contract.

It does not fetch retailer pages, infer inventory quantities, convert currencies, merge source
records or let generated image text affect product identity.

```bash
uv run ruff check packages/pi_compare
uv run mypy packages/pi_compare/src packages/pi_compare/tests
uv run pytest packages/pi_compare/tests
```

The family projection builder, read API and web view land in later slices described in
[`docs/design/cross-retailer-comparison.md`](../../docs/design/cross-retailer-comparison.md).
