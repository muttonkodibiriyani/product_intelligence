# pi_profiles

`VerticalProfile` plugins (ADR-0007 §4, ADR-0008 §3). A profile is a versioned attribute model
plus its size rules, registered as `<name>@<version>`. Only `beauty@1` exists so far;
`food_menu@1` and `apparel@1` follow in ADR-0008 step 6.

One attribute model per profile is the single source for:

- **the wire declaration.** `profile.declaration()` is the snapshot's `meta.profile` and
  `meta.attributeSet`. A test pins it to the committed
  `pi_dataset/contracts/profiles/<ref>.json`, so code and contract can't drift. `pi_dataset`
  never imports this package.
- **the write path.** `get_profile(ref).validate_attributes(raw)` is the only way to produce
  `variant.attributes`. It is strict: unknown keys, Python field names instead of wire keys,
  and wrong types are all refused, and nothing is coerced. It returns canonical jsonb, with
  defaults dropped so that `{}` means "none". Store it with `variant.attributes_schema = ref`;
  migration 0004 enforces the pairing.

Beauty keeps its typed `variant` columns (shade, finish, concentration and so on), so
`beauty@1` needed no data migration.

## Adding a profile version

1. Write an `AttributeModel` subclass. Every field is `Annotated[T, Attr(...)]`, and its wire
   key is the alias if there is one, otherwise the field name.
2. Register it in `registry.PROFILES`.
3. Commit its declaration JSON under `pi_dataset/contracts/profiles/`. The tests fail until the
   two match.

A published version is immutable. Changing keys or types means a new version.
