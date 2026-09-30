"""UAT cases: Matching and comparison policy (MAT-*)."""

from uat.registry import pending, uat


@uat("MAT-01", "m2")
def test_mat_01_match_classes() -> None:
    """Match classes.

    Requirement: Support identical variant, identical family, normalized-size comparison and
                 business-approved substitute as distinct relationships.
    Accept: Each comparison visibly labels its match class.
    """
    pending()


@uat("MAT-02", "m2")
def test_mat_02_deterministic_constraints() -> None:
    """Deterministic constraints.

    Requirement: Enforce critical identity constraints before probabilistic matching.
    Accept: Different fragrance concentration or electronics model cannot be an exact match.
    """
    pending()


@uat("MAT-03", "m2")
def test_mat_03_candidate_generation() -> None:
    """Candidate generation.

    Requirement: Suggest candidate matches using identifiers, text, attributes and permitted
                 images.
    Accept: Candidate rank and supporting attributes are available for analyst inspection.
    """
    pending()


@uat("MAT-04", "m2")
def test_mat_04_confidence_calibration() -> None:
    """Confidence calibration.

    Requirement: Calibrate separate match-confidence scores by category, language and match
                 class.
    Accept: Report precision and coverage on labeled holdout samples, not a single unvalidated
            AI score.
    """
    pending()


@uat("MAT-05", "m2")
def test_mat_05_human_review() -> None:
    """Human review.

    Requirement: Allow reviewers to accept, reject, lock, split, merge and replace matches with
                 reasons.
    Accept: A locked human decision is not overwritten by a model update.
    """
    pending()


@uat("MAT-06", "m2")
def test_mat_06_unmatched_state() -> None:
    """Unmatched state.

    Requirement: Keep unmatched and ambiguous products available in assortment views without
                 forcing a comparison.
    Accept: Low-confidence candidates remain unmatched in price indices.
    """
    pending()


@uat("MAT-07", "m2")
def test_mat_07_hard_negatives() -> None:
    """Hard negatives.

    Requirement: Store rejected pairs and prohibit their automatic recreation until an
                 authorized review changes the decision.
    Accept: A rejected large-to-small candle pair does not reappear after recrawling.
    """
    pending()


@uat("MAT-08", "m2")
def test_mat_08_versioned_match_graph() -> None:
    """Versioned match graph.

    Requirement: Store effective dates, reviewer, algorithm version and lineage for every match
                 edge.
    Accept: A report can use the match policy known at publication or a labeled restatement.
    """
    pending()


@uat("MAT-09", "m2")
def test_mat_09_no_false_transitivity() -> None:
    """No false transitivity.

    Requirement: Avoid treating business substitutes or family relationships as transitive exact
                 identity.
    Accept: A similar-to-B and B-similar-to-C does not automatically make A identical to C.
    """
    pending()


@uat("MAT-10", "m2")
def test_mat_10_comparison_cohorts() -> None:
    """Comparison cohorts.

    Requirement: Save exact comparison universes with product, market, channel, time window,
                 fees, tax and eligibility rules.
    Accept: A saved cohort produces reproducible results with a pinned data cutoff.
    """
    pending()


@uat("MAT-11", "m2")
def test_mat_11_time_alignment() -> None:
    """Time alignment.

    Requirement: Enforce a maximum observation-age difference and a freshness threshold for
                 comparable offers.
    Accept: A current offer is not ranked against a stale competitor without a visible warning
            or exclusion.
    """
    pending()


@uat("MAT-12", "m2")
def test_mat_12_quality_governance() -> None:
    """Quality governance.

    Requirement: Track match precision, recall where measurable, coverage and reviewer
                 disagreement by vertical.
    Accept: Release reports expose category-level quality and unresolved review volume.
    """
    pending()
