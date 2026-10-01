# Design: ML layer (scaffold only, gated)

| | |
|---|---|
| Status | Proposed. **Scaffold only: no model, no training and no prediction exists or ships in this PR.** |
| Owner | AI Assistant Engineer |
| Task | M5 (01a0f475-acf2) |
| Code | `packages/pi_metrics/src/pi_metrics/gated.py`, tests in `packages/pi_metrics/tests/test_gated.py` |
| Requirements | ANL-06, ANL-13, ANL-14, ANL-15, ANL-16, ANL-17; UAT-31. KPI-26..30: TODO, see §6 |
| Related | `docs/design/price-suggestions.md` (the rule-based layer that ships now) |

## 1. What and why

The owner wants the product to show where ML will go: price-change detection, elasticity,
forecasting and optimal price. **None of these can be built honestly from today's data.** The
snapshot has one retailer and a few daily dates, and no internal cost or sales. This design:

1. lists each model with the **exact inputs** it needs and why;
2. defines one API shape, **`needs_data`**, that the frontend renders as an honest locked card
   showing what is missing and how much of it exists;
3. counts `have` from the real snapshot where the snapshot can show it, and reports `0` where the
   platform has no source.

**No fabricated predictions anywhere.** The gated type has no field that could carry a
prediction, and `needs_data` is its only state (a test pins both). The rule-based price
suggestions (`price-suggestions.md`) are the only pricing output, and they are labelled
"rule-based, not ML".

## 2. The gated state

```jsonc
{
  "state": "needs_data",            // the only value
  "model": "forecast",              // price_change_detection | elasticity | forecast | optimal_price
  "requirements": ["ANL-15"],
  "needs": [
    {"kind": "history_snapshots", "required": 90, "have": 3, "model": null},
    {"kind": "backtest",          "required": 1,  "have": 0, "model": null}
  ],
  "gatesVersion": "2026-10-01.1"
}
```

| `kind` | Unit | `have` today |
|---|---|---|
| `history_snapshots` | daily dates in the snapshot's series (`meta.dates`) | counted |
| `retailers` | supported retailers in the market with at least one collected price | counted |
| `internal_sales` | days of internal sales at product-location-day grain (ANL-14) | 0, no source |
| `internal_cost` | an internal unit-cost feed at product-location grain (ANL-14) | 0, no source |
| `analyst_labels` | analyst dispositions on flagged movements (ANL-13) | 0, no source |
| `experiment` | a credible experiment or causal-control design for the period (ANL-16) | 0, none |
| `backtest` | a recorded backtest that beats the naive baseline | 0, none |
| `upstream_model` | another model in a ready state (`model` names it) | 0, none is |

Frontend rendering: one locked card per model with the title, a "Needs data" chip, and per need
`have / required` with a progress bar. No placeholder chart, sample curve or "coming soon"
number. The text comes from the `kind`, never from a model output.

## 3. Models and their gates

Thresholds are initial and conservative; each one changes only with a `gatesVersion` bump and a
decision-log entry.

### 3.1 Price-change detection (ANL-13; builds on ANL-06)

*Rule-based repricing events (ANL-06) need only two dates. The ML model ranks **unexpected**
movements and separates source defects from commercial changes.*

| Need | Required | Why |
|---|---|---|
| `history_snapshots` | 28 | four weekly cycles per offer, to learn a normal pattern |
| `analyst_labels` | 200 | dispositions (real change vs source defect) to train and evaluate against; ANL-13 asks for "an analyst disposition" per anomaly |
| `backtest` | 1 | precision at the review-queue size beats the rule baseline (any change > X %) |

### 3.2 Elasticity (ANL-16, needs ANL-14)

*How demand responds to price. Public prices alone cannot give an asserted elasticity (ANL-16's
acceptance criterion; UAT-31).*

| Need | Required | Why |
|---|---|---|
| `internal_sales` | 365 | a year of product-location-day sales, to cover seasonality and promotions |
| `history_snapshots` | 365 | own and competitor prices over the same year |
| `retailers` | 2 | competitor price as a control |
| `experiment` | 1 | price tests or a causal design; observational correlation is not elasticity |
| `backtest` | 1 | holdout error beats a no-response baseline |

### 3.3 Forecast (ANL-15)

*Forecast selected metrics (e.g. the price index or promotion share) only after minimum-history
and backtesting gates, with uncertainty and a comparison with simple baselines.*

| Need | Required | Why |
|---|---|---|
| `history_snapshots` | 90 | about a quarter of daily points, enough for weekly seasonality and a rolling-origin backtest |
| `backtest` | 1 | beats the naive and seasonal-naive baselines, with calibrated intervals |

Forecasting **sales** would also need `internal_sales`. That is out of scope until ANL-14 exists.

### 3.4 Optimal price (ANL-17, needs ANL-14 and §3.2)

*Scenario planning: price alternatives with costs, constraints, assumptions and sensitivity.
Results are labelled "modeled" and need human approval before any action.*

| Need | Required | Why |
|---|---|---|
| `upstream_model` (elasticity) | 1 | an optimum needs a response curve |
| `internal_cost` | 1 feed | margin needs unit cost |
| `internal_sales` | 365 | the volume base for the scenario |
| `backtest` | 1 | scenario error on held-out price changes |

Until then, the only price output is the **rule-based** suggestion, which states the target band
and guardrails and makes no outcome claim.

## 4. Why `needs_data` is the only state

A `ready` state would need a model output schema, uncertainty fields, a model version, an eval
report and a review. Adding it now would invite a placeholder. When a model's gates are met, its
own design PR adds a separate reviewed state and endpoint. `gated()` keeps answering
`needs_data` for every model; since `backtest` is a gate for every model and none is recorded,
that answer stays true.

## 5. Wiring later (Deep Coder)

* `GET /v1/models` → `[Gated, …]` (all four, `all_gated`), and `GET /v1/models/{model}` →
  `Gated`. No query parameters. Cache with the snapshot generation.
* The response is not a `Metric` envelope. There is no cohort or value, only the counts above, so
  it needs no `metricVersion`; `gatesVersion` versions the thresholds.
* No source text: every string is an enum or an ANL ID. The assistant may expose it later as a
  tool for "why can't you forecast X?" answers.

## 6. Open items

* **KPI-26..30: TODO.** The requirements register is not in this public repository; the KPIs are
  cited by ID only and mapped by the coordinator. No register wording is copied here.
* `internal_*` and `analyst_labels` get real counts when ANL-14 (internal joins) and the anomaly
  review queue exist; until then they are `0` by construction.
* The thresholds in §3 want a data-science review before any model work starts.
