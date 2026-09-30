"""UAT cases: Price and promotion normalization (PRC-*)."""

from uat.registry import pending, uat


@uat("PRC-01", "m1")
def test_prc_01_price_types() -> None:
    """Price types.

    Requirement: Store current displayed, retailer-stated regular, promotional, member, coupon,
                 subscription and installment prices separately.
    Accept: A monthly installment is never ranked as the full product selling price.
    """
    pending()


@uat("PRC-02", "m1")
def test_prc_02_reference_price_provenance() -> None:
    """Reference-price provenance.

    Requirement: Label retailer-stated regular prices separately from previously observed prices
                 and statutory reference prices.
    Accept: A reported discount identifies its exact reference-price basis.
    """
    pending()


@uat("PRC-03", "m1")
def test_prc_03_money_precision() -> None:
    """Money precision.

    Requirement: Store original currency, decimal precision and amount without binary rounding
                 artifacts or forced two-decimal assumptions.
    Accept: Currency and rounding fixtures preserve three-decimal and zero-decimal examples.
    """
    pending()


@uat("PRC-04", "m1")
def test_prc_04_tax_basis() -> None:
    """Tax basis.

    Requirement: Store tax included, excluded or unknown with jurisdiction and source evidence
                 where available.
    Accept: Tax-unknown offers cannot silently enter a tax-aligned comparison.
    """
    pending()


@uat("PRC-05", "m1")
def test_prc_05_unit_normalization() -> None:
    """Unit normalization.

    Requirement: Convert comparable weights, volumes, counts and pack quantities into a declared
                 base unit.
    Accept: 200 g at 80 yields 40 per 100 g; missing quantity yields unknown, not zero.
    """
    pending()


@uat("PRC-06", "m1")
def test_prc_06_dimension_compatibility() -> None:
    """Dimension compatibility.

    Requirement: Prevent unsupported mass-volume, dose, quality and cross-category equivalence
                 conversions.
    Accept: A milliliter price cannot become a gram price without an approved conversion basis.
    """
    pending()


@uat("PRC-07", "m3")
def test_prc_07_fx_conversion() -> None:
    """FX conversion.

    Requirement: Preserve original prices and apply dated, sourced exchange rates only in a
                 derived comparison layer.
    Accept: Historical converted prices reproduce with the same FX date and rate version.
    """
    pending()


@uat("PRC-09", "m1")
def test_prc_09_promotion_conditions() -> None:
    """Promotion conditions.

    Requirement: Capture eligibility, minimum spend, qualifying quantity, dates, channel, caps,
                 code and exclusions as structured rules.
    Accept: A new-customer coupon cannot be presented as universally available.
    """
    pending()


@uat("PRC-13", "m1")
def test_prc_13_price_ranges() -> None:
    """Price ranges.

    Requirement: Preserve from-prices, variant ranges and quote-only values without inventing a
                 single price.
    Accept: A from-price requires variant selection before exact comparison.
    """
    pending()


@uat("PRC-14", "m1")
def test_prc_14_channel_separation() -> None:
    """Channel separation.

    Requirement: Distinguish delivery, pickup, online, marketplace and explicitly evidenced
                 dine-in prices.
    Accept: Pickup pricing is not labeled dine-in unless the source explicitly establishes that
            basis.
    """
    pending()


@uat("PRC-15", "m1")
def test_prc_15_promotion_timing() -> None:
    """Promotion timing.

    Requirement: Store observed start/end bounds separately from advertised start/end dates.
    Accept: A promotion found between crawls has an interval of first possible detection, not a
            fabricated exact start.
    """
    pending()


@uat("PRC-16", "m1")
def test_prc_16_price_anomalies() -> None:
    """Price anomalies.

    Requirement: Flag impossible discounts, decimal parsing errors, sudden currency changes and
                 extreme movements before publication.
    Accept: A synthetic 100-to-1 parsing defect is quarantined and does not trigger a commercial
            recommendation.
    """
    pending()
