from typing import Any

import pytest

from pi_compare import (
    AttributeObservation,
    AttributeSpec,
    EvidencePointer,
    ValueState,
    validate_attribute,
    validate_attributes,
)
from pi_dataset.profiles import AttributeDef


def definition(
    key: str,
    kind: str = "text",
    *,
    capability: bool = True,
    values: list[dict[str, Any]] | None = None,
) -> AttributeDef:
    return AttributeDef.model_validate(
        {
            "key": key,
            "level": "product",
            "type": kind,
            "values": values,
            "label": {"en": key},
            "facet": False,
            "block": "summary",
            "capability": capability,
        }
    )


PAGE = EvidencePointer(source="page", field="jsonld", excerpt="retailer value")


def observed(value: object, evidence: EvidencePointer = PAGE) -> tuple[AttributeObservation, ...]:
    return (AttributeObservation(raw=value, evidence=evidence),)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("captured", "capability", "expected"),
    [
        (True, True, ValueState.UNKNOWN),
        (False, True, ValueState.NOT_OBSERVED),
        (True, False, ValueState.NOT_OBSERVED),
    ],
)
def test_missing_is_explicit(captured: bool, capability: bool, expected: ValueState) -> None:
    spec = AttributeSpec(definition=definition("finish", capability=capability))
    assert validate_attribute(spec, (), captured=captured).state is expected


@pytest.mark.parametrize(
    ("spec", "raw", "canonical"),
    [
        (AttributeSpec(definition=definition("finish")), " Matte ", "Matte"),
        (AttributeSpec(definition=definition("spf", "decimal")), "30.0", "30.0"),
        (AttributeSpec(definition=definition("vegan", "bool")), True, True),
        (
            AttributeSpec(
                definition=definition(
                    "gender",
                    "enum",
                    values=[{"id": "unisex", "label": {"en": "Unisex"}}],
                )
            ),
            "unisex",
            "unisex",
        ),
        (
            AttributeSpec(
                definition=definition(
                    "skinTypes",
                    "text_list",
                    values=[{"id": "dry", "label": {"en": "Dry"}}],
                )
            ),
            ["dry"],
            ["dry"],
        ),
        (
            AttributeSpec(definition=definition("measure", "object"), allowed_units=("ml", "g")),
            {"value": "10", "unit": "ml"},
            {"value": "10", "unit": "ml"},
        ),
        (
            AttributeSpec(definition=definition("fee", "money"), allowed_currencies=("AED",)),
            {"amount": "10.00", "minor": 1000, "currency": "AED"},
            {"amount": "10.00", "minor": 1000, "currency": "AED"},
        ),
    ],
)
def test_typed_values(spec: AttributeSpec, raw: object, canonical: object) -> None:
    cell = validate_attribute(spec, observed(raw), captured=True)
    assert cell.state is ValueState.OBSERVED
    assert cell.canonical == (canonical,)


@pytest.mark.parametrize(
    ("spec", "raw", "error"),
    [
        (AttributeSpec(definition=definition("spf", "decimal")), 30.0, "decimal_not_string"),
        (
            AttributeSpec(
                definition=definition(
                    "gender",
                    "enum",
                    values=[{"id": "unisex", "label": {"en": "Unisex"}}],
                )
            ),
            "other",
            "not_allowed_enum",
        ),
        (
            AttributeSpec(definition=definition("measure", "object"), allowed_units=("ml",)),
            {"value": "10", "unit": "oz"},
            "unit_not_allowed",
        ),
        (
            AttributeSpec(definition=definition("fee", "money"), allowed_currencies=("AED",)),
            {"amount": "10.00", "minor": 1000, "currency": "USD"},
            "currency_not_allowed",
        ),
    ],
)
def test_invalid_type_enum_unit_and_currency(spec: AttributeSpec, raw: object, error: str) -> None:
    cell = validate_attribute(spec, observed(raw), captured=True)
    assert cell.state is ValueState.INVALID
    assert error in cell.errors


def test_conflicting_observations_are_not_silently_resolved() -> None:
    spec = AttributeSpec(definition=definition("finish"))
    cell = validate_attribute(
        spec,
        (*observed("matte"), *observed("dewy")),
        captured=True,
    )
    assert cell.state is ValueState.CONFLICT
    assert cell.raw == ("matte", "dewy")


def test_model_value_requires_model_identity_version_and_confidence() -> None:
    spec = AttributeSpec(definition=definition("finish"))
    evidence = EvidencePointer(source="model", field="description", excerpt="soft matte")
    cell = validate_attribute(spec, observed("matte", evidence), captured=True)
    assert cell.state is ValueState.INVALID
    assert "model_evidence_missing_identity_or_confidence" in cell.errors


def test_complete_model_provenance_is_accepted() -> None:
    evidence = EvidencePointer(
        source="model",
        field="description",
        excerpt="soft matte",
        model_name="attribute-reader",
        model_version="2026-10-01",
        confidence="0.91",
    )
    cell = validate_attribute(
        AttributeSpec(definition=definition("finish")),
        observed("matte", evidence),
        captured=True,
    )
    assert cell.state is ValueState.OBSERVED


@pytest.mark.parametrize(
    ("spec", "raw", "error"),
    [
        (AttributeSpec(definition=definition("finish")), " ", "not_nonempty_text"),
        (AttributeSpec(definition=definition("spf", "decimal")), "no", "invalid_decimal"),
        (AttributeSpec(definition=definition("spf", "decimal")), "NaN", "nonfinite_decimal"),
        (AttributeSpec(definition=definition("fee", "money")), "10", "money_not_object"),
        (
            AttributeSpec(definition=definition("fee", "money")),
            {"amount": "wrong", "minor": 1, "currency": "AED"},
            "invalid_money",
        ),
        (AttributeSpec(definition=definition("vegan", "bool")), "yes", "not_boolean"),
        (
            AttributeSpec(definition=definition("claims", "text_list")),
            [],
            "not_nonempty_text_list",
        ),
        (
            AttributeSpec(
                definition=definition(
                    "claims",
                    "text_list",
                    values=[{"id": "vegan", "label": {"en": "Vegan"}}],
                )
            ),
            ["other"],
            "list_value_not_allowed",
        ),
        (AttributeSpec(definition=definition("measure", "object")), "10 ml", "not_object"),
    ],
)
def test_other_invalid_attribute_shapes(spec: AttributeSpec, raw: object, error: str) -> None:
    cell = validate_attribute(spec, observed(raw), captured=True)
    assert cell.state is ValueState.INVALID
    assert error in cell.errors


def test_all_151_declared_fields_are_emitted_and_validated() -> None:
    specs = tuple(AttributeSpec(definition=definition(f"field{i}")) for i in range(151))
    observations = {f"field{i}": observed(f"value-{i}") for i in range(151)}
    report = validate_attributes(specs, observations, captured=frozenset(observations))

    assert len(report.cells) == 151
    assert report.completeness == "1.000000"
    assert report.counts[ValueState.OBSERVED] == 151
    assert report.issues == ()


def test_report_counts_missing_states_and_undeclared_values() -> None:
    specs = (
        AttributeSpec(definition=definition("known")),
        AttributeSpec(definition=definition("uncaptured")),
    )
    report = validate_attributes(
        specs,
        {"known": observed("yes"), "stray": observed("no")},
        captured=frozenset({"known"}),
    )
    assert report.completeness == "0.500000"
    assert report.counts[ValueState.OBSERVED] == 1
    assert report.counts[ValueState.NOT_OBSERVED] == 1
    assert [(issue.key, issue.code) for issue in report.issues] == [
        ("stray", "undeclared_attribute")
    ]


def test_empty_profile_is_complete_and_duplicate_specs_are_refused() -> None:
    report = validate_attributes((), {}, captured=frozenset())
    assert report.completeness == "1.000000"
    spec = AttributeSpec(definition=definition("finish"))
    with pytest.raises(ValueError, match="repeat a key"):
        validate_attributes((spec, spec), {}, captured=frozenset())
