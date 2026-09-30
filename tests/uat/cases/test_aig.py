"""UAT cases: AI assistant and model governance (AIG-*)."""

from uat.registry import pending, uat


@uat("AIG-01", "m4")
def test_aig_01_grounded_questions() -> None:
    """Grounded questions.

    Requirement: Answer natural-language questions only from authorized datasets and governed
                 metric definitions.
    Accept: Each numerical answer references its query, cohort, cutoff and supporting records.
    """
    pending()


@uat("AIG-02", "m4")
def test_aig_02_deterministic_calculations() -> None:
    """Deterministic calculations.

    Requirement: Execute arithmetic and aggregation through tested query or metric services, not
                 free-form language generation.
    Accept: AI totals exactly match the governed analytics output for test questions.
    """
    pending()


@uat("AIG-03", "m4")
def test_aig_03_uncertainty_behavior() -> None:
    """Uncertainty behavior.

    Requirement: Separate observed facts, derived metrics, estimates and forecasts; abstain on
                 insufficient coverage.
    Accept: An unanswered history period is labeled unavailable rather than invented.
    """
    pending()


@uat("AIG-04", "m4")
def test_aig_04_prompt_injection_controls() -> None:
    """Prompt-injection controls.

    Requirement: Treat source pages, descriptions and documents as untrusted data and isolate
                 them from instructions.
    Accept: Malicious page text cannot access credentials, alter permissions or trigger
            unauthorized actions.
    """
    pending()


@uat("AIG-05", "m4")
def test_aig_05_read_only_tools() -> None:
    """Read-only tools.

    Requirement: Limit AI to allowlisted, scoped read-only queries and approved report drafting.
    Accept: Tests show no arbitrary SQL writes, commerce actions or cross-tenant retrieval.
    """
    pending()


@uat("AIG-06", "m4")
def test_aig_06_model_evaluation() -> None:
    """Model evaluation.

    Requirement: Evaluate language accuracy, numerical correctness, attribution, bias and access
                 isolation on held-out tasks.
    Accept: Release requires the agreed test thresholds and documented failure analysis.
    """
    pending()


@uat("AIG-07", "m4")
def test_aig_07_version_and_rollback() -> None:
    """Version and rollback.

    Requirement: Track model, prompt, embeddings and extraction versions with rollback and human
                 review.
    Accept: A changed model can be reverted without losing source observations or manual
            matches.
    """
    pending()


@uat("AIG-08", "m4")
def test_aig_08_training_restrictions() -> None:
    """Training restrictions.

    Requirement: Prohibit use of Alshaya confidential data for external model training unless
                 explicitly authorized.
    Accept: Processing contracts and configuration match the approved data-use policy.
    """
    pending()
