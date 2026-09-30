# UAT suite

One pytest case per pilot-scope requirement in `docs/requirements/traceability.csv`
(127 IDs), grouped by ID prefix in `cases/test_<prefix>.py`.

```python
@uat("PRC-01", "m1")              # requirement ID, milestone that delivers it
def test_prc_01_price_types() -> None:
    """Price types. ..."""
    pending()                     # strict xfail until implemented
```

- **Implementing a case:** replace `pending()` with the scenario (recorded fixtures only,
  no live-site calls) and pass `implemented=True`. A pending case that passes is an
  `XPASS(strict)` failure, so the flag cannot drift.
- **Milestone:** adjust the second argument if delivery moves; markers `m0`..`m5` select
  cases (`make uat M=m1`).
- **Traceability gate** (`test_traceability.py`, part of the normal `pytest` run): fails if
  a pilot-scope ID has no case, a case cites an unknown ID or milestone, or
  `docs/requirements/uat_status.md` is stale. Regenerate it with `make uat-status`.
