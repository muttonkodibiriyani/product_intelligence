"""UAT cases: Canonical catalog and taxonomy (CAT-*)."""

from uat.registry import pending, uat


@uat("CAT-01", "m0")
def test_cat_01_product_versus_offer() -> None:
    """Product versus offer.

    Requirement: Separate canonical product, sellable variant, source listing, seller offer and
                 time-stamped observation.
    Accept: One variant sold by two sellers has separate offers and a shared product identity.
    """
    pending()


@uat("CAT-02", "m0")
def test_cat_02_identifiers() -> None:
    """Identifiers.

    Requirement: Store internal article codes, source SKUs, GTINs and manufacturer identifiers
                 with issuer and validation state.
    Accept: Leading zeros survive; reused or conflicting identifiers do not auto-merge products.
    """
    pending()


@uat("CAT-03", "m0")
def test_cat_03_variant_identity() -> None:
    """Variant identity.

    Requirement: Represent size, color, shade, scent, capacity, flavor, concentration, condition
                 and pack count as applicable.
    Accept: A 50 ml fragrance and 100 ml fragrance remain distinct variants.
    """
    pending()


@uat("CAT-04", "m0")
def test_cat_04_family_relationships() -> None:
    """Family relationships.

    Requirement: Link product families, variants, multipacks, kits, bundles, successors and
                 reformulations explicitly.
    Accept: A successor can share a family but never overwrite the predecessor's history.
    """
    pending()


@uat("CAT-05", "m0")
def test_cat_05_typed_attributes() -> None:
    """Typed attributes.

    Requirement: Use category-specific typed fields, controlled units and schema versions rather
                 than free text alone.
    Accept: Adding candle wick count leaves apparel size and electronics voltage validation
            unchanged.
    """
    pending()


@uat("CAT-06", "m0")
def test_cat_06_multilingual_catalog() -> None:
    """Multilingual catalog.

    Requirement: Preserve original names and descriptions alongside translations,
                 transliterations and normalized search fields.
    Accept: A translation update does not alter the original source evidence.
    """
    pending()


@uat("CAT-07", "m0")
def test_cat_07_multiple_taxonomies() -> None:
    """Multiple taxonomies.

    Requirement: Maintain source taxonomy, universal taxonomy and Alshaya taxonomy with
                 versioned many-to-many mappings.
    Accept: A category change can be viewed as originally classified or restated under the new
            mapping.
    """
    pending()


@uat("CAT-08", "m0")
def test_cat_08_configurable_depth() -> None:
    """Configurable depth.

    Requirement: Support arbitrary practical taxonomy depth and category-specific required
                 attributes.
    Accept: A six-level category can be configured without truncation to the four-level demo.
    """
    pending()


@uat("CAT-09", "m3")
def test_cat_09_manual_enrichment() -> None:
    """Manual enrichment.

    Requirement: Allow controlled business tags, category corrections, article mappings and
                 review notes.
    Accept: Overrides retain author, reason and scope and survive subsequent automated runs.
    """
    pending()


@uat("CAT-10", "m0")
def test_cat_10_attribute_provenance() -> None:
    """Attribute provenance.

    Requirement: Tag every important value as observed, supplied, normalized, inferred or
                 manually corrected.
    Accept: Users can distinguish an inferred material from a material explicitly stated on the
            page.
    """
    pending()
