# Requirements v2 attribute spec (frozen copy)

Source: the owner's requirements artifact "PI · Requirements, every product field, and every
screen (v2)", tm8 artifact `01a0fc4d-c4b7-7f41-a3aa-65ae1ae534d8`, extracted from its embedded
`const S = {...}` block on 2026-10-02.

| File | Holds |
| --- | --- |
| `requirements_v2_attributes.json` | `S.a.attributes`: the 143 attributes (key, group, level, verticals, type, example, requirement, source, note, detail_only). |
| `requirements_v2_structure.json` | `S.a` without the attributes: the three-level hierarchy, grouping rules, group names, storage rules, the capture principle and what detail-only means. |

`src/pi_capture/_attributes.py` is generated from the attributes file by
`scripts/gen_registry.py`; `tests/test_registry.py` fails when the two drift apart. Edit the JSON
(only to mirror a new requirements version), regenerate, commit both.
