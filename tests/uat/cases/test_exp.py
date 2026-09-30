"""UAT cases: User experience and collaboration (EXP-*)."""

from uat.registry import pending, uat


@uat("EXP-01", "m3")
def test_exp_01_search_workspace() -> None:
    """Search workspace.

    Requirement: Search by text, identifier, category, brand, attribute, retailer, geography and
                 date.
    Accept: Users can find both current and historical products and see their coverage status.
    """
    pending()


@uat("EXP-02", "m3")
def test_exp_02_comparison_builder() -> None:
    """Comparison builder.

    Requirement: Guide users through match type, units, channel, geography, date, tax, currency
                 and eligibility.
    Accept: Invalid comparisons are blocked or explicitly labeled exploratory.
    """
    pending()


@uat("EXP-03", "m3")
def test_exp_03_product_workspace() -> None:
    """Product workspace.

    Requirement: Provide product family, variants, offers, evidence, match rationale and
                 historical charts in one view.
    Accept: Any displayed price is reachable from a chart point in two drill-down steps.
    """
    pending()


@uat("EXP-04", "m3")
def test_exp_04_saved_datasets() -> None:
    """Saved datasets.

    Requirement: Create static or rule-based folders with explicit cohort version, owner and
                 sharing permissions.
    Accept: Dynamic sets show membership changes; frozen sets do not change on recrawl.
    """
    pending()


@uat("EXP-05", "m3")
def test_exp_05_role_dashboards() -> None:
    """Role dashboards.

    Requirement: Provide brand, pricing, merchandising, marketing, research, executive and data-
                 operations views.
    Accept: Each role sees relevant metrics without bypassing entitlement filters.
    """
    pending()


@uat("EXP-06", "m3")
def test_exp_06_drill_through() -> None:
    """Drill-through.

    Requirement: Connect portfolio KPIs to markets, categories, individual matches and source
                 observations.
    Accept: A summary number can be reconciled to its exported constituent records.
    """
    pending()


@uat("EXP-07", "m3")
def test_exp_07_alerts() -> None:
    """Alerts.

    Requirement: Configure change, promotion, availability, match-quality and freshness alerts
                 with threshold and recipient scope.
    Accept: Deduplication, cooldown, acknowledgment and clear resolution are tested.
    """
    pending()


@uat("EXP-10", "m3")
def test_exp_10_accessible_ui() -> None:
    """Accessible UI.

    Requirement: Provide keyboard navigation, readable charts, accessible tables and Arabic
                 right-to-left layouts.
    Accept: Core search, comparison and export flows pass the agreed accessibility checklist.
    """
    pending()


@uat("EXP-11", "m4")
def test_exp_11_exports() -> None:
    """Exports.

    Requirement: Export filtered rows, charts, metric definitions and evidence references with
                 permission controls.
    Accept: Exported totals equal the dashboard under the same cutoff and filter set.
    """
    pending()


@uat("EXP-12", "m3")
def test_exp_12_no_data_experience() -> None:
    """No-data experience.

    Requirement: Explain no results, stale results, restricted access, incomplete history and
                 incompatible comparisons.
    Accept: Empty charts cannot be mistaken for zero prices or zero competitors.
    """
    pending()
