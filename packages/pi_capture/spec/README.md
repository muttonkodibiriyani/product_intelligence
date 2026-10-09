# Requirements v2 attribute spec (frozen copy)

Source: the owner's requirements artifact "PI · Requirements, every product field, and every
screen (v2)", tm8 artifact `01a0fc4d-c4b7-7f41-a3aa-65ae1ae534d8`, extracted from its embedded
`const S = {...}` block on 2026-10-02.

| File | Holds |
| --- | --- |
| `requirements_v2_attributes.json` | `S.a.attributes`: the 143 attributes (key, group, level, verticals, type, example, requirement, source, note, detail_only), plus one local addition (below). |
| `requirements_v2_structure.json` | `S.a` without the attributes: the three-level hierarchy, grouping rules, group names, storage rules, the capture principle and what detail-only means. |

`src/pi_capture/_attributes.py` is generated from the attributes file by
`scripts/gen_registry.py`; `tests/test_registry.py` fails when the two drift apart. Edit the JSON
(only to mirror a new requirements version, or for a ruled local addition listed here),
regenerate, commit both.

Local additions (144 attributes in all):

- `listing_live_date` (lifecycle, style, page): the retailer go-live date a rival publishes for
  its own listing (Bloomingdale's `c_prd_live_date`, Ounass `onlineDateWithStock`). Added on
  the coordinator's ruling of 2026-10-09 because the v2 `launch_date` is ours only (source
  feed) and its note forbids a rival's date in the same column. Shown as "retailer go-live
  date", never "launch date".
