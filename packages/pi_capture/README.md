# pi-capture

The offline, "parse later" half of the capture principle: a page is stored whole, and this
package says what the page should have told us and what it actually did.

* `spec/requirements_v2_attributes.json` — the 143 requirement attributes, copied from the
  requirements artifact (see `spec/README.md` for provenance).
* `pi_capture.registry` — the attributes as typed Python (`ATTRIBUTES`, generated into
  `_attributes.py` by `scripts/gen_registry.py`), lookups (`by_key`, `for_group`, `for_level`,
  `page_sourced`, `applicable`) and `type_spec`, which parses the spec's type strings
  (`enum ar|en`, `text(14)`, `bigint null`, `text[]`).
* `pi_capture.model` — `Reading` (one attribute read from one page: state, raw text beside the
  normalised value, where on the page it came from) and `ProductCapture` (one page, one visit).
  States are explicit: `observed`, `not_shown`, `blocked`, `parse_failed`, `not_applicable`.
  Money and other exact numbers are `Decimal`; floats are refused. JSON round-trips exactly.
* `pi_capture.generic` — pure extractors for the machine-readable blocks most shops publish:
  JSON-LD, OpenGraph and other metas, microdata, `__NEXT_DATA__`, React Server Component chunks,
  and `find_json_objects` for JSON buried in script text. `readings_from_generic` maps them onto
  registry keys; `generic_facts` keeps the published facts that have no registry key yet
  (availability, seller, condition).
* `pi_capture.coverage` — per retailer, per applicable page-sourced attribute: how many pages
  showed it, hid it, blocked us, or could not be read. JSON and a plain Markdown table.

Regenerate the registry after editing the spec:

```sh
uv run python packages/pi_capture/scripts/gen_registry.py
```

A test fails if the generated module and the spec drift apart. Nothing in this package
performs network access.
