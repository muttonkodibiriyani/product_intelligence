"""UAT cases: Reliability and commercial acceptance (OPS-*)."""

from uat.registry import pending, uat


@uat("OPS-01", "m5")
def test_ops_01_separate_slas() -> None:
    """Separate SLAs.

    Requirement: Specify availability, collection completion, data freshness, data accuracy and
                 incident response separately.
    Accept: A source outage counts against data-service reporting even when the UI remains
            available.
    """
    pending()


@uat("OPS-02", "m5")
def test_ops_02_performance_envelope() -> None:
    """Performance envelope.

    Requirement: Agree source count, location contexts, variants, observations, concurrent users
                 and query workload before setting targets.
    Accept: Load tests run against the signed workload envelope rather than a demo dataset.
    """
    pending()


@uat("OPS-03", "m5")
def test_ops_03_service_targets() -> None:
    """Service targets.

    Requirement: Negotiate measurable dashboard, API, ingestion, alert and recovery targets with
                 exclusions disclosed.
    Accept: Every SLA has a measurement window, percentile, owner and breach remedy.
    """
    pending()


@uat("OPS-05", "m3")
def test_ops_05_no_silent_truncation() -> None:
    """No silent truncation.

    Requirement: Prohibit undisclosed SKU, row, query, export or history limits within the
                 contracted envelope.
    Accept: Oversized datasets fail visibly or paginate fully with accurate record counts.
    """
    pending()


@uat("OPS-07", "m0")
def test_ops_07_change_management() -> None:
    """Change management.

    Requirement: Publish connector and platform release notes, regression evidence and rollout
                 or rollback procedures.
    Accept: Breaking changes receive agreed notice and a supported migration path.
    """
    pending()


@uat("OPS-09", "m4")
def test_ops_09_operational_observability() -> None:
    """Operational observability.

    Requirement: Monitor collection queues, parser drift, match quality, pipeline delay, query
                 latency and cost.
    Accept: Alerts distinguish source, ingestion, matching and serving failures with actionable
            ownership.
    """
    pending()
