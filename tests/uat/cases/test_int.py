"""UAT cases: Integration and portability (INT-*)."""

from uat.registry import pending, uat


@uat("INT-02", "m4")
def test_int_02_batch_contract() -> None:
    """Batch contract.

    Requirement: Deliver versioned manifests with batch IDs, counts, checksums, schemas and
                 watermarks.
    Accept: Corrupt or incomplete deliveries are rejected and safely replayed.
    """
    pending()


@uat("INT-03", "m4")
def test_int_03_incremental_feed() -> None:
    """Incremental feed.

    Requirement: Supply full snapshots, deltas, correction events and tombstones with stable
                 keys.
    Accept: A consumer can rebuild the same current state from snapshot plus deltas.
    """
    pending()


@uat("INT-05", "m4")
def test_int_05_internal_data_mapping() -> None:
    """Internal data mapping.

    Requirement: Map approved article, brand, store and category codes without replacing source
                 systems of record.
    Accept: Mapping changes are versioned and internal prices remain internally authoritative.
    """
    pending()


@uat("INT-07", "m4")
def test_int_07_service_identities() -> None:
    """Service identities.

    Requirement: Use separate least-privilege identities, secret vaults and rotation for each
                 integration.
    Accept: No shared employee password or secret is embedded in an exported dataset.
    """
    pending()


@uat("INT-08", "m4")
def test_int_08_api_reliability() -> None:
    """API reliability.

    Requirement: Define limits, retry behavior, idempotency, deprecation and supported schema
                 versions.
    Accept: Consumer retry tests pass without duplicated history or silent truncation.
    """
    pending()


@uat("INT-09", "m4")
def test_int_09_exit_migration() -> None:
    """Exit migration.

    Requirement: Export client-owned taxonomies, approved matches, notes and metric definitions
                 in documented formats.
    Accept: An exit rehearsal verifies data rights, completeness and reconciliation.
    """
    pending()
