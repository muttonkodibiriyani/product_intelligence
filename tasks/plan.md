# Slice 5: 154 typed attributes

Base: `acfed4ae148ce8fb6aed6a07f77975fa1630d99f` (`origin/main`).

## Contract decisions

- Publish an additive, versioned 154-definition manifest: the 145 requirement-registry keys, eight non-overlapping `beauty@2` keys, and `variant_relationships`.
- Project exactly 154 slots for every master, offer, and variant target. A seventh `not_applicable` state marks definitions belonging to another target level; the six required evidence states remain distinct.
- Preserve `/api/v1/products/{id}`. Add a generation-bound, cursor-paged `/api/v1/products/{id}/attributes` endpoint.
- Reject unknown manifest keys and malformed cursors. Do not silently drop, substitute, coerce, or infer values.
- Expose typed JSON values, declared units/currency semantics, target level, and sanitized public field evidence.
- Bound the browser DOM through server paging (25 rows by default, 50 maximum), with English/Arabic labels and RTL-safe/a11y controls.

## Incremental delivery

1. Manifest and projection core
   - Add the immutable manifest and model/state resolver.
   - Write failing contract tests first, including exact cardinality, state distinction, unknown-key rejection, and malformed-value handling.
   - Verify only the focused Python tests; a red result is any cardinality drift, substituted value, accepted unknown key, or state collapse.
2. API and OpenAPI
   - Add the product attribute route, opaque cursor, filters, bounded pagination, and schema examples.
   - Verify focused API tests plus generated OpenAPI drift checks; a red result is legacy response drift, unstable paging, stale cursor acceptance, or missing schema types.
3. Web matrix
   - Add typed client models, query hook, paged matrix, EN/AR/RTL content, keyboard/a11y semantics, and bounded rendering.
   - Verify component tests, typecheck, and production build; a red result is over-limit DOM rows, lost state labels, inaccessible controls, or a client/schema mismatch.
4. Coverage receipt and whole-repository verification
   - Add deterministic fixture coverage reporting for masters/offers/variants.
   - Run formatting, lint, unit/integration tests, contract/OpenAPI checks, and production web build from a clean exact head.
5. Delivery
   - Commit and push a dedicated branch, open and link a separate PR, wait for exact-head CI, review the diff, then squash-merge with the expected head.
   - Deploy the merged API image and frontend from exact digests, then verify live API and browser behavior. If Cloud/Firebase credentials remain unavailable, stop only at that external boundary and record the precise blocker.

## Scope boundaries

- No synthetic business values, unit conversions, bulk export, datastore migration, or replacement of existing Product Detail fields.
- No claim that live retailer catalog coverage is proven unless the deterministic report runs against an available saved catalog.
- Slice 6 comparison behavior remains out of scope.
