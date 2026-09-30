"""Base classes for pi_core records."""

from typing import ClassVar, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pi_core.enums import FieldState


class PiModel(BaseModel):
    """Immutable record. Unknown keys are an error so a typo can never drop data silently."""

    model_config = ConfigDict(frozen=True, extra="forbid", validate_default=True)


class FieldStateModel(PiModel):
    """A record whose optional observed fields carry an explicit null reason (DQ-02).

    For every name in ``TRACKED_FIELDS``: the value is ``None`` exactly when ``field_state`` holds
    a reason for it. A null without a reason and a reason next to a value are both rejected.
    """

    TRACKED_FIELDS: ClassVar[frozenset[str]] = frozenset()

    field_state: dict[str, FieldState] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_field_state(self) -> Self:
        unknown = sorted(set(self.field_state) - self.TRACKED_FIELDS)
        if unknown:
            msg = f"field_state names untracked fields: {unknown}"
            raise ValueError(msg)
        for name in sorted(self.TRACKED_FIELDS):
            is_null = getattr(self, name) is None
            has_reason = name in self.field_state
            if is_null and not has_reason:
                msg = f"{name} is null without a field_state reason"
                raise ValueError(msg)
            if has_reason and not is_null:
                msg = f"{name} has a value and a field_state reason"
                raise ValueError(msg)
        return self
