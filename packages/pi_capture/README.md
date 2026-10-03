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
  Money readings carry `currency` as a field beside the minor-unit amount. Exact numbers are
  `Decimal`; floats, NaN and infinities are refused. A capture records `looked_for`, the keys its
  extractor knows how to read. JSON round-trips exactly: `Decimal` is written as
  `{"$decimal": "…"}` and any scraped object key starting with `$` is escaped with a second `$`,
  so scraped content can never be mistaken for the tag.
* `pi_capture.generic` — pure extractors for the machine-readable blocks most shops publish:
  JSON-LD, OpenGraph and other metas, microdata, `__NEXT_DATA__`, React Server Component chunks,
  and `find_json_objects` for JSON buried in script text. `readings_from_generic` maps them onto
  registry keys; `generic_facts` keeps the published facts that have no registry key yet
  (availability, seller, condition, a price range). `LOOKED_FOR` is the set of keys these
  extractors read. Printed amounts are parsed explicitly: `12,50` is a decimal comma, `1.299,00`
  and `1,299.00` are grouped thousands, `1,299` is ambiguous and refused, `12.500` is read as
  three decimals only for KWD/BHD/OMR, and negative amounts are refused. Grouping is three digits
  a group with a first group of one to three, so `1234,567.00` is refused and in `1234,567` the
  comma can only be the decimal mark. Spaces (plain, no-break, narrow, thin) are thousands
  grouping and nothing else: `1 299,50` reads, `12 50` (fils set as a superscript) and `1 2 3`
  are refused rather than read as 1250 and 123. `loads` refuses an untagged float, NaN or
  Infinity in a capture line.
* `pi_capture.faces` — the first shop-specific extractor (faces.ae, Salesforce Commerce Cloud):
  reads the `dataLayer` `view_item` push, the SFCC data attributes and the rendered fragments
  (shade swatches, MUSE points, tabby/tamara instalments, badges, free-gift button, gallery, VAT
  line, description accordion) first, then lets the generic extractors fill the gaps. Ratings and
  related products render client-side there and are recorded `not_shown`. `faces_facts` keeps
  the availability flags. Tests use synthetic SFCC-shaped HTML only.
* `pi_capture.coverage` — per retailer, per applicable page-sourced attribute: how many pages
  showed it, hid it, blocked us, could not be read, or was never looked for by the extractor.
  JSON and a plain Markdown table.

Regenerate the registry after editing the spec:

```sh
uv run python packages/pi_capture/scripts/gen_registry.py
```

A test fails if the generated module and the spec drift apart. Nothing in this package
performs network access.
