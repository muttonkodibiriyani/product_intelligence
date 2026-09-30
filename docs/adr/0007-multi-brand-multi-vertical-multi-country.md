# ADR-0007: Any brand, retailer, vertical and country: a config-driven platform

- Status: proposed (owner architecture requirement, 30 Sep 2026, relayed by the program coordinator)
- Date: 2026-09-30
- Extends: blueprint §5 (data model), §6 (collection), §8 (matching), §9–10 (analytics and web app)
- Carries over unchanged: ADR-0003 (ladder), ADR-0005 (pilot rulings), ADR-0006 (access rulings and amendments)
- Inputs: the Reviewer's hard-code audit (findings C1–C6, D1, E2–E4, I1–I4, M1–M2, as cited below)
- Runbook: `docs/runbooks/onboard-new-site.md`

## Context
The pilot compares two beauty retailers in one country (Ulta UAE and Sephora UAE, ADR-0005). The
owner requires the platform to work for **any** brands and retailers, in **any** country, and for
**any** comparison: brand vs brand, retailer vs retailer, and many vs many. That covers food
(restaurant and QSR menus) as well as non-food (beauty, apparel, and so on).

Most of the core is already generic:
- the family → variant → listing → observation chain;
- `source_context` (country, channel, `location_context`, locale);
- the `pi_fetch` `Connector` Protocol;
- `Money` with ISO 4217 exponents;
- the `Channel` enum, which already has `delivery`, `pickup` and `dine_in_evidenced`.

The Reviewer's audit found the pilot-specific parts that are hard-coded:
- **Markets.** The `Market` enum (`SA`, `AE`) has its own currency and time-zone tables. The
  `Locale` enum is `en`/`ar` only. The pacer defaults to `Asia/Dubai`. The currency-exponent table
  is partial (C1–C5).
- **Variants.** `variant` has beauty-only columns, and brand aliases live in code (D1).
- **Dataset.** The published `pi.dataset/v1` has exactly two retailers keyed `"u"`/`"s"`, one
  market (AED/AE only), a fixed beauty category list, and SQL filtering on
  `name LIKE 'sephora%' OR 'ulta%'` (E2–E4, I1–I2).
- **Matching.** `pi_match` is written as "Ulta vs Sephora", with beauty-only rules (M1–M2).
- **Per-source settings.** They are kept as Python mappings (`FetchPolicy.browsers`,
  `robots_modes`, `page_interval_s`, `residential_proxy`) and in tool environment variables.
- **Access.** There is no per-user scoping of data (I4).

Adding a site, a vertical or a country must not mean forking code, and must not loosen any access
rule.

## Decision

### 1. Markets, locales and currencies are data
- **Country** is an ISO 3166-1 alpha-2 code on the source context, not an enum member. Currency
  (ISO 4217) and time zone (IANA) come from the source context or register, not from lookup tables
  in `pi_core`.
- **Locale** is a BCP 47 tag (`en-AE`, `ar-SA`, `fr-FR`). Right-to-left comes from the script, via
  a set of RTL languages (`ar`, `he`, `fa`, `ur`, …).
- **Currency exponents:** `pi_core` carries the full ISO 4217 table (for example KWD, BHD and OMR
  have 3 decimal places; JPY has 0).
- **No hidden defaults:** there is no `Asia/Dubai` default. A context without a time zone is
  invalid. The `Accept-Language` value comes from the context locale, with a fallback list set in
  config.
- **Compatibility:** `Market` and `Locale` stay as deprecated aliases until every caller has moved.
  AE behaviour does not change.

### 2. Source register (configuration, not code)
Every source is declared in a versioned register file, `config/sources/<source_key>.yaml`, one
file per source. The file is reviewed like code and contains **no secrets**: a secret appears only
as a Secret Manager resource name.

A loader validates the file with a pydantic model and upserts `source` and `source_context` rows.
Changes are append-only: a changed context closes `valid_to` and opens a new row, so history stays
attributable. `pi_fetch.FetchPolicy` is **built from the register**; hand-written mappings and tool
environment variables are no longer the source of truth.

```yaml
source_key: ulta_ae                 # stable id, also Connector.source_key
name: Ulta Beauty UAE
kind: web                           # web | app | feed | aggregator | offline (SourceKind)
vertical: beauty                    # beauty | food_menu | apparel | ... (§4)
role: retailer                      # retailer | brand | aggregator
base_url: https://www.ulta.ae/
hosts: {page: www.ulta.ae, image: <image CDN host>}   # images are fetched direct, never proxied
connector: {package: pi_connector_ulta, min_version: 0.1.0}
contexts:
  - country: AE                     # ISO 3166-1 alpha-2
    currency: AED                   # ISO 4217; must be in the pi_core exponent table
    time_zone: Asia/Dubai           # IANA; required, no default
    locales: [en-AE]                # BCP 47; each locale is its own source_context
    channel: online                 # pi_core Channel
    location_context: {}            # food: branch or delivery zone (§4.2)
access:
  rung_max_allowed: 5               # 0, 1, 2, 4 or 5; 3 is rejected by pi_core
  browser: {engine: webkit, device: desktop, headless: true}   # pinned; no automatic fallback
  page_interval_s: 5.0              # floor 1.0 (MIN_INTERVAL_FLOOR_S); >= 5.0 when proxied
  off_peak: {start: "01:00", end: "06:00"}   # local time of the context
  robots_mode: obey                 # obey (default) | tag_only (only if APPROVED_DEVIATIONS allows)
  proxy:                            # null for every source not in PROXY_SOURCES
    approval_ref: ADR-0006 Amendment 2
    secret_ref: projects/productintelligence-beeb3/secrets/pi-proxy-iproyal-ae/versions/<n>  # pinned, never latest
    byte_cap_gb: "1.8"              # a Decimal string, never a float
cadence: on_demand                  # the only accepted value (blueprint §6.4)
approvals:                          # informational: decision refs, cross-checked against code (below)
  - ADR-0006 Amendment 1 (WebKit pinned)
  - ADR-0006 Amendment 2 (rung 5, ulta.ae only)
```

**Deviations are gated in code, not in YAML.** A YAML edit on its own must never be able to approve
anything. Every owner-approved deviation from the defaults is recorded in a reviewed, code-level
table, `pi_fetch.policy.APPROVED_DEVIATIONS: {source_key: {deviation: decision_ref}}`. This uses the
same reasoning as `PROXY_SOURCES`.

Deviation kinds today:
- `robots_tag_only`: `sephora_me`, ADR-0005 decision 2;
- `residential_proxy`: `ulta_ae`, ADR-0006 Amendment 2.

The register may ask for a deviation, but the loader grants it only when **all** of these hold:
- the source and deviation are in `APPROVED_DEVIATIONS`;
- the YAML's `approval_ref` (or `approvals` entry) equals the table's `decision_ref`;
- for a proxy, the source is also in `PROXY_SOURCES`.

A test asserts that the `residential_proxy` entries equal `PROXY_SOURCES`. Tests also assert that
a register file asking for `tag_only` or a `proxy` for any other source is rejected, even when its
`approvals` list names a plausible decision. The `approvals` list is documentation and a
cross-check; it never grants anything.

The loader rejects anything the guardrails forbid, so a config change cannot loosen them. Each rule
is a test:
- **Rung 3:** `rung_max_allowed: 3` is rejected, using pi_core `LadderRung.is_permitted` (not
  redefined).
- **Robots:** `robots_mode: tag_only` is rejected unless `APPROVED_DEVIATIONS` grants
  `robots_tag_only` to that source. Today only Sephora ME has it (ADR-0005).
- **Proxy fields:** a `proxy` block is rejected unless all of these hold:
  - it has `approval_ref`, `secret_ref` and `byte_cap_gb`;
  - `APPROVED_DEVIATIONS` grants `residential_proxy` to the source;
  - `secret_ref` is a **pinned** version: it matches pi_fetch's own `_SECRET_RESOURCE_RE` (imported,
    never copied) and is not `versions/latest` (#35);
  - `byte_cap_gb` is a `Decimal` greater than 0;
  - `page_interval_s` is at least 5.0 (the same rule `FetchPolicy` enforces for residential-proxy
    sources).

  `rung_max_allowed: 5` without a `proxy` block is rejected. Proxy bytes already used
  (`prior_bytes`) are **not** a register field: they stay a required runtime input on every run
  (`ResidentialProxy.prior_bytes`), read from the provider dashboard.
- **Proxy code gate (C6):** `pi_fetch.proxy.PROXY_SOURCES` **stays a code-level safety gate**. The
  register cannot enable a proxy on its own: a source that is not in `PROXY_SOURCES` is refused
  whatever its YAML says. Adding a proxied source takes all three of:
  - the owner's approval and purchase after a per-site Proxy Decision Report;
  - an ADR amendment (as ADR-0006 Amendment 2 did for ulta.ae);
  - a reviewed code change to `PROXY_SOURCES`.
- **Cadence:** any value other than `on_demand` is rejected. A schedule needs a new owner decision
  and an ADR.
- **Engine:** a list of engines, or any fallback list, is rejected. Each source has exactly one
  pinned engine (ADR-0006 Amendment 1).
- **Validity:** an unknown currency, a missing or unknown time zone, and a locale that is not valid
  BCP 47 are all rejected.

**Defaults for a new source** are the strictest settings:
- `robots_mode: obey`;
- `proxy: null`;
- `rung_max_allowed: 2`;
- `page_interval_s: 1.0` with jitter;
- `cadence: on_demand`.

An approval given for one source (the Sephora robots deviation, the Ulta engine pin, Algolia route
and proxy) never carries over to another source.

### 3. Generic connector framework and "new connector" template
The `pi_fetch.Connector` Protocol (discover → requests_for → parse, pure parse, no network I/O in
connector packages) stays the one contract. Two additions:

- **`pi_connector_kit`**: shared, pure helpers that parse bytes already fetched:
  - JSON-LD `Product`, `Offer`, `Menu`/`MenuItem` and `BreadcrumbList` extraction;
  - embedded-state extraction (`__NEXT_DATA__` and similar state blobs);
  - sitemap and sitemap-index parsing for `discover`;
  - locale-aware price-text parsing to `Money`, with Arabic-Indic digits and currency symbols;
  - availability-text mapping that never infers `out_of_stock` from missing data;
  - size and portion parsing that keeps the original text.

  The kit imports no network modules; the `pi_fetch.guard` AST scan covers it.
- **`templates/pi_connector_template/`**: a package skeleton copied by
  `make new-connector SOURCE=<source_key> VERTICAL=<vertical>`. It contains:
  - `connector.py` with `source_key`, `connector_version`, `vertical` and the three methods as
    stubs that raise `NotImplementedError`;
  - `tests/test_contract.py`, which imports the shared contract suite;
  - `tests/fixtures/README.md` with the recording and redaction rules;
  - a `README.md` template covering recon links, coverage gaps and approvals;
  - a `pyproject.toml` wired into the workspace, mypy and coverage.

**Connector contract suite**: one parametrised suite that every connector runs against its own
fixtures. It checks that:
- parse is deterministic, and a replay gives identical output;
- the network-import guard passes;
- a result with `block` set is never parsed;
- partial data gives `not_observed`/`blocked`, never `out_of_stock` or `removed`;
- every offer links to a listing;
- money is in the context currency;
- fixtures contain no `Cookie`/`Set-Cookie`, no auth headers and no key-shaped strings (plus
  gitleaks);
- vertical attributes validate against the vertical's profile (§4).

### 4. Vertical profiles and the attribute model
**Attribute model decision (D1, M2).** Vertical-specific attributes live in
**`variant.attributes jsonb`, schema-validated per vertical**. We considered three options:

| Option | Verdict |
|---|---|
| Typed columns per vertical on `variant` (or one extension table per vertical) | Rejected. Every new vertical needs a core migration; the table widens with columns that are null for most rows; and it moves towards a fork per vertical. |
| EAV (`variant_attribute(variant_id, key, value)`) | Rejected. Values lose their types, validation moves into the application with nothing enforcing it, queries turn into pivots, and bad keys are easy to write. |
| **`variant.attributes jsonb` + a versioned per-vertical schema** | **Chosen.** New verticals need no core migration, writes are validated, and typed read models are available through views. |

How the jsonb is kept honest:
- **Versioning:** each vertical has a versioned pydantic model (`food_menu@1`), and the version is
  stored in a new `variant.attributes_schema` column.
- **Write path:** writes validate against that model.
- **Database check:** a `CHECK` makes sure `attributes_schema` is present whenever `attributes` is
  non-empty.
- **Provenance:** `attr_provenance` records which evidence each field came from.
- **Typed reads:** per-vertical SQL views (`variant_food_menu_v`, `variant_apparel_v`) project the
  jsonb into typed columns, with expression indexes where queries need them.
- **Migration:** the migration is append-only (it adds columns; no data is rewritten).
- **Existing columns:** the beauty columns on `variant` (shade, finish, concentration, and so on)
  stay. The `beauty@1` profile reads them, so there is no data migration.

**`VerticalProfile` plugins.** One plugin per vertical bundles everything vertical-specific:
- the attribute model and its version;
- the normalisers (size, portion, colour, size system);
- the match rules (§5);
- the category taxonomy root;
- the UI facets and product-page blocks (§6).

Profiles are registered by name (`beauty`, `food_menu`, `apparel`). Brand aliases move out of code
into data: a `brand.aliases` table plus a reviewed seed file. So a new vertical is a new profile,
not a copy of any package. The shared core model covers every vertical:
- brand, family, variant, listing, offer, promotion, evidence and match edge;
- the common variant fields: `gtin`, `mpn`, `size_value`/`size_unit`, `pack_count` and
  `is_set`/`set_contents`.

#### 4.1 Beauty (exists)
Blueprint §5.3 unchanged: shade/code/family/hex, finish, size, pack, concentration, refill, mini,
set and claims. Mass and volume are never auto-converted.

#### 4.2 Food menu (restaurants and QSR)
| Concept | Where it lives |
|---|---|
| Menu item (for example, "Big Mac") | `product_family`, with the restaurant brand as its brand |
| Size or portion (small/medium/large, 6/9/20 pieces, grams) | `variant`. Uses `size_value`/`size_unit` when published (g, ml, pieces), plus `attributes.portion_label` as published |
| Combo or meal | `variant` with `is_set = true`. `set_contents` lists the components as `{family ref or name, qty, choice_group}`, with choice groups ("any drink, medium") kept explicit |
| Modifiers and add-ons | `attributes.modifiers` (name, price delta as a money string, default flag). A modifier becomes its own variant only if it is sold on its own |
| Nutrition and allergens | `attributes.nutrition` and `attributes.allergens` as published, with the source basis kept |
| Channel: delivery, pickup, dine-in | `source_context.channel` (`delivery`, `pickup`, `dine_in_evidenced`). A dine-in price is recorded **only with evidence**: the brand's own dine-in menu page or a menu document it publishes. Otherwise it is `not_observed`, never copied from delivery |
| Branch or location | `source_context.location_context` = `{branch_id, city, area, lat, lon, delivery_zone}`, one context per branch or zone that is priced differently. Prices are never averaged across branches |
| Aggregators (delivery apps) | `source.kind = aggregator`, with `seller_id` = the restaurant branch. Delivery fees, service fees and minimum order go in the offer's `attributes.fees`, never in `price_current` |
| Time-of-day menus (breakfast) | `attributes.daypart`. An item missing from the current daypart menu is `not_observed`, not `removed` |

Units: the basis is per item. Unit prices (per piece or per 100 g) are derived only when the portion
is published.

#### 4.3 Apparel
| Concept | Where it lives |
|---|---|
| Style | `product_family`, with `attributes.style_code` when published |
| Colour | `attributes.colour` as published, plus a normalised `colour_family`. The swatch image uses `listing_image.role = swatch` |
| Size run | One `variant` per colour × size. `attributes.size_label` and `attributes.size_system` (EU/UK/US/alpha/numeric) are kept as published. The run is the set of sibling variants, and per-size availability is the offer on each variant. **Size systems are never auto-converted** |
| Fit | `attributes.fit` (slim, regular, relaxed, …) as published, plus a normalised value |
| Material | `attributes.material` as a composition list `{fibre, pct}` as published, with the original text kept |

### 5. N-way matching
**Any number of sources (M1).** `pi_match` matches **any pair of sources** in a market. Results are
keyed by `(source_a, source_b)` with a canonical order. For N sources, every pair is scored:
- candidates are blocked by brand, GTIN and category, so the cost grows with overlap rather than
  N²·catalogue;
- CLI text, file names and reports are neutral ("source A"/"source B", or the register names),
  never "Ulta"/"Sephora".

Cross-market pairs (the same retailer in AE and SA) are a later, explicit option. They follow the
same rules.

**Shared engine.** Candidate generation, scoring, buckets, the writer to `match_edge` and the
`review_state` semantics are shared. Rejected and locked edges are never rewritten.

**Cross-cutting rules:**
- **No transitive exact identity** (blueprint §8.2). A many-way comparison row shows offers A, B
  and C side by side as an exact row **only if every pair among them has an exact edge**. If not,
  the row is shown as partial.
- **No cross-vertical matches** (hard rule).
- **GTIN** confirms exact only when no hard rule conflicts, as today.
- **Per (vertical, category):** thresholds and gold sets are set per vertical and category, and the
  CI precision gate runs per vertical. A new vertical has auto-accept off until its gold set exists.

**Per-vertical rules** come from the `VerticalProfile` (§4):

| Vertical | Exact | Family | Size-normalised | Substitute |
|---|---|---|---|---|
| Beauty | Today's rules (§8.4): brand, name, shade code, size, concentration and pack. Minis, refills and sets are separate | Same product, different shade or size | Per ml or g | Human-approved |
| Food menu | Same brand, item and portion, and for combos the same components and choice groups. Across channels or branches of one brand this is the **same variant** under different contexts, not a match edge | Same item, different portion | Per piece or per 100 g, only when published | **The main cross-brand relation** (Big Mac ↔ Whopper): a human-approved `substitute` within a comparable category ("beef burger, single"), never auto-accepted |
| Apparel | Same brand, style code (or GTIN), colour, and size in the same size system | Same style, different colour or size | n/a | Human-approved |

### 6. Analytics, dataset contract and UI: parameterised, nothing hard-coded
**Comparisons are data.** A saved `ComparisonSet` is:
- two or more **sides**, each a filter over `{source, brand, country, category, vertical, channel,
  location}`;
- a basis (`exact`, `size_normalized`, `family` or `substitute`);
- a time window.

"Ulta UAE vs Sephora UAE", "McDonald's vs Burger King, Dubai delivery" and "five retailers × three
brands" are all rows of the same kind. The metric layer (`metric_def`) takes these as dimensions,
and each metric states which verticals it applies to.

**Dataset contract v2 (E2–E4, I1–I2)** replaces `pi.dataset/v1`:
- **Schema:** a JSON Schema in `docs/contracts/` with an explicit `schema: "pi.dataset/v2"`
  version field. The producers (`demo_export`, later the pipeline), the upload validator
  (`infra/scripts/publish_dataset.py`) and the dashboard all test against it.
- **Retailers:** `retailers[]` holds N entries (id = register `source_key`, display name, logo,
  country, status). Offers are keyed by retailer id; the fixed `"u"`/`"s"` slots go away.
- **Markets:** `markets[]` holds `{country, currency, time_zone, locales}`, and the validator
  accepts more than one.
- **Currency:** every offer carries its own `currency`.
- **Money** is a decimal **string** plus integer minor units at the currency exponent
  (`{"amount": "129.00", "minor": 12900, "currency": "AED"}`), never a JSON float.
- **Categories** come from the vertical profile's taxonomy, not a fixed list.
- **Layout:** `datasets/<market>/<scope>/latest.json` plus immutable dated snapshots. `<scope>` is
  a `ComparisonSet` id or a vertical/category slice.
- **Transition:** v1 stays readable until the dashboard moves to v2.
- **No name matching:** producers never select sources by string pattern (such as
  `name LIKE 'ulta%'`). They select from the register.

**Currency in views.** Values are shown in each side's native currency. Cross-country views convert
with the pinned `fx_rate` for the observation date and label the rate. Nothing is converted
silently.

**UI:**
- Labels, logos and colours come from the register.
- Direction (RTL/LTR) and number formats come from the locale.
- Facets and product-page blocks come from the vertical profile:
  - beauty: swatches;
  - apparel: size run and colour;
  - food: portion, combo, channel and branch.
- The dashboard's A-vs-B pickers are driven by the contract's `retailers[]` and `markets[]`.

**Literal guard.** A test fails if a source key, brand name or country code appears as a literal in
analytics, export or web-app code outside config, fixtures and contracts.

### 7. Per-user data scoping (I4): optional, designed now, built on demand
The pilot has one audience, so data is not scoped per user. Today (#23) any invited user
with the `role` claim `admin` or `viewer` may read `datasets/**` (`infra/storage.rules`). If
clients start seeing different markets or brands, access is scoped as follows:
- **Claim:** a second Firebase custom claim sits next to `role`:
  `scopes = {markets: [...], brands: [...], sources: [...]}`. It is set by
  `infra/scripts/invite_user.py` and mirrored in `user_entitlement`.
- **Fail closed:** once PR-F is in force, a `viewer` without a `scopes` claim reads **no** dataset;
  missing scopes never means full access. Full access is an explicit claim
  (`scopes = {all: true}`) or the `admin` role. PR-F backfills `scopes` for every existing user
  before the rules switch, and an emulator test covers the no-claim deny.
- **Enforcement:** the Storage and Firestore rules narrow `datasets/**` to the
  `datasets/<market>/<scope>/` paths that the claims cover. The assistant's tools filter by the
  same claims.
- **Tests:** emulator tests cover allow and deny for each claim shape.

The v2 dataset layout (§6) is chosen so these rules are path-based and need no reshaping later. The
trigger for building it is the first second audience whose scope differs (PR-F).

### 8. Guardrails carry over unchanged
ADR-0003, ADR-0005 and ADR-0006 (with both amendments) apply exactly as written to every new
source, vertical and country:
- the ladder is rungs 0, 1, 2 and 4; rung 3 is never attempted;
- rung 5 is off for every source **except** those in `PROXY_SOURCES` under an ADR amendment
  (today only `ulta_ae`, ADR-0006 Amendment 2, which is why §2's example sets it to 5). A new
  proxied source needs its own amendment, the owner's approval and purchase, and reviewed
  `PROXY_SOURCES`/`APPROVED_DEVIATIONS` entries (§2);
- robots.txt is obeyed with the fail-closed status matrix;
- collection stops at the first challenge: no solving, no retry, and no switch of engine, user
  agent or egress;
- no logins, cookie reuse, cart or checkout;
- no TLS impersonation or stealth;
- pacing is at most 1 req/s per host with jitter, off-peak;
- cadence is on-demand only;
- classifier refusals are reported, never routed around.

The owner approvals that exist today are **per source** and do not generalise. Each one is a
code-level entry for one source (`APPROVED_DEVIATIONS`, `PROXY_SOURCES`), and the register
reference is cross-checked against it (§2).

A new country may bring its own legal or consumer-data constraints. Onboarding a new country records
them as an owner decision before any collection. Reviews still carry no PII.

## Migration path from today's code
The work is done in small PRs. Each one keeps current behaviour: all tests stay green, AE/AED
output is unchanged, beauty matcher outputs are byte-identical on the gold fixtures, and the Ulta
and Sephora connectors give identical parse output on their fixtures.

| PR | Scope | Task | Gate |
|---|---|---|---|
| PR-A | Markets as data (§1): pi_core Country, currency and time zone from context; BCP 47 locale with an RTL set; full ISO 4217 exponents; no `Asia/Dubai` default; `Accept-Language` fallback from config. Tests include KWD (3 dp) and a non-Gulf market. `PROXY_SOURCES` is unchanged | 01a0f47a-951e | Can land before this ADR is approved |
| PR-B | Dataset contract v2 (§6): JSON Schema, `retailers[]`, `markets[]`, per-offer currency, money as string plus minor units, `datasets/<market>/<scope>/` | 01a0f47a-9741 | ADR approved |
| PR-C | `demo_export` parameterised: selects from the register, emits v2, no `"u"`/`"s"` and no `LIKE` | 01a0f47a-993c | PR-B |
| PR-D | N-way matching (§5): any source pair in a market, `(source_a, source_b)` keys, neutral CLI | 01a0f47a-9b5a | ADR approved |
| PR-E | `VerticalProfile` plugins (beauty first, then food_menu and apparel) plus `variant.attributes_schema` (append-only migration) and brand aliases as data (§4) | 01a0f47a-9d64 | ADR approved |
| PR-F | Per-user scope claims (§7) | 01a0f47a-9f9b | Only if a differently scoped audience appears |
| Dashboard | Pickers driven by the contract | 01a0f47a-a213 | PR-B |
| Follow-up (not yet filed) | Source register and loader (§2) with the code-level `APPROVED_DEVIATIONS` table and its tests; `FetchPolicy.from_register()`; `tools/ulta_snapshot` reads the register | — | ADR approved |
| Follow-up (not yet filed) | Connector kit, template, contract suite and `make new-connector` (§3). Shared code moves out of the Ulta and Sephora connectors with golden-fixture parity | — | Register |
| Follow-up | First non-beauty source, via the onboarding runbook, own register entry and recon | — | Owner go |

## Consequences
- **Adding a site** is a register entry plus a connector from the template, with no change to
  shared code. A site that needs a deviation (robots `tag_only`, or a proxy) also needs, on purpose:
  - a reviewed `APPROVED_DEVIATIONS` entry (and a `PROXY_SOURCES` entry for a proxy);
  - an ADR amendment;
  - the owner's approval.
- **Adding a vertical** is a `VerticalProfile`, with no fork and no change to the core tables.
- **Adding a country** is register data plus an owner decision on local constraints.
- **Enforcement:** access rules are enforced when config loads as well as in `pi_fetch`, so a config
  mistake fails closed.
- **Labelling:** per-vertical gold sets add labelling work before anything is auto-accepted in a
  new vertical.
- **Food volume:** food-menu data multiplies contexts (branches × channels × locales). Onboarding
  estimates the count and its cost before any run.
- **jsonb trade-off:** jsonb attributes give up some column-level typing in exchange for
  extensibility without forks. Validation on write, `attributes_schema` versioning and typed views
  keep that trade-off bounded.
- **Dashboard:** it must move to contract v2. v1 stays readable during the move.

## Alternatives considered
- **A package fork per vertical or per site** (`pi_match_food`, `pi_core_apparel`): rejected. The
  rules drift, fixes are duplicated, and it breaks "one contract".
- **Typed columns or EAV for attributes:** rejected (see §4).
- **Proxy enablement by config alone:** rejected. A proxy costs money and sits closest to the
  access-control line, so it keeps a code gate that requires review, on top of the register entry
  (C6).
- **Keeping per-source Python settings** (today's approach): rejected. Approvals end up scattered
  across code and environment variables, and a guardrail could be loosened somewhere nobody reviews.
