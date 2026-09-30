# UAT suite

- One pytest case per pilot-scope requirement in `docs/requirements/traceability.csv`
  (127 IDs), grouped by ID prefix in `cases/test_<prefix>.py`. The owner deviations
  SRC-08/SEC-05 also have cases asserting their replacement control (ADR-0003/0005).
- One file per acceptance scenario UAT-01..UAT-36 (`docs/requirements/uat_scenarios.csv`:
  IDs, titles and requirement links only) as `test_uat_XX_<slug>.py`, decorated with
  `@scenario("UAT-02", "m2", reqs=(...))`. Scenarios outside the pilot (food/dine-in,
  electronics, later-scope-only) pass `out_of_scope="<reason>"`
  and are skipped, not deleted. The pilot market is UAE; keep fixtures market-parameterised.

```python
@uat("PRC-01", "m1")  # requirement ID, milestone that delivers it
def test_prc_01_price_types() -> None:
    """Price types. ..."""
    pending()  # strict xfail until implemented
```

- **Implementing a case:** replace `pending()` with the scenario (recorded fixtures only,
  no live-site calls) and pass `implemented=True`. A pending case that passes is an
  `XPASS(strict)` failure, so the flag cannot drift.
- **Milestone:** adjust the second argument if delivery moves; markers `m0`..`m5` select
  cases (`make uat M=m1`).
- **Traceability gate** (`test_traceability.py`, part of the normal `pytest` run): fails if
  a pilot-scope ID has no case, a case cites an unknown ID or milestone, a register
  scenario has no `test_uat_XX_*.py` (or its `reqs` differ from the register links), a
  scenario's milestone is earlier than its linked requirement cases, a pilot case's
  docstring no longer contains its CSV requirement/acceptance text (whitespace-insensitive), or
  `docs/requirements/uat_status.md` is stale. Regenerate it with `make uat-status`.
