"""``pi.similar/v1``: per product and retailer, the closest products at the other retailers.

This file is a similarity signal, **not** an identity claim. Nothing in it is a match edge, and
compare, price gap, index and match KPIs never read it (design §1). Every list is labelled
``similar, not the same product`` by ``kind``.
"""

from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import ConfigDict, Field, StringConstraints, model_validator
from pydantic.alias_generators import to_camel

from pi_core import PiModel
from pi_similar.signals import MIN_SIGNALS, Signal

SCHEMA = "pi.similar/v1"
#: A score or signal in ``[0, 1]`` as text at four decimal places ("0.7400", "1.0000").
UnitText = Annotated[str, StringConstraints(pattern=r"^(0\.\d{4}|1\.0000)$")]
NonEmpty = Annotated[str, StringConstraints(min_length=1)]


class SimilarModel(PiModel):
    """camelCase on the wire, like the dataset and matches contracts."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        validate_default=True,
        alias_generator=to_camel,
        populate_by_name=True,
    )


class Signals(SimilarModel):
    """Each signal, or null when it is absent for this pair (never imputed)."""

    text: UnitText | None
    image: UnitText | None
    price: UnitText | None
    attributes: UnitText | None

    def present(self) -> frozenset[Signal]:
        return frozenset(s for s in Signal if getattr(self, s.value) is not None)


class Competitor(SimilarModel):
    product: NonEmpty
    retailer: NonEmpty
    score: UnitText
    signals: Signals
    reasons: tuple[NonEmpty, ...]
    same_brand: bool

    @model_validator(mode="after")
    def _enough_signals(self) -> Self:
        present = self.signals.present()
        if len(present) < MIN_SIGNALS or not ({Signal.TEXT, Signal.IMAGE} & present):
            msg = f"{self.product}: needs {MIN_SIGNALS} signals, one of them text or image"
            raise ValueError(msg)
        return self


class Similar(SimilarModel):
    """The competitors of one product as one retailer sells it, best first."""

    product: NonEmpty
    retailer: NonEmpty
    competitors: tuple[Competitor, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _others_only(self) -> Self:
        for found in self.competitors:
            if found.retailer == self.retailer:
                msg = f"{self.product}: a competitor at the same retailer {self.retailer}"
                raise ValueError(msg)
            if found.product == self.product:
                msg = f"{self.product}: a product is never its own competitor"
                raise ValueError(msg)
        ranks = [(-Decimal(c.score), c.retailer, c.product) for c in self.competitors]
        if ranks != sorted(ranks):
            msg = f"{self.product}: competitors must be ordered by score, then retailer and id"
            raise ValueError(msg)
        return self


class Meta(SimilarModel):
    scope: NonEmpty
    #: A recorded input of the run, never read from a clock.
    generated_at: NonEmpty
    #: Signal name to the exact model and revision that produced it.
    models: dict[NonEmpty, NonEmpty]
    weights_version: NonEmpty
    weights: dict[NonEmpty, NonEmpty]
    #: The most competitors kept per other retailer.
    k: int = Field(ge=1)


class SimilarFile(SimilarModel):
    schema_id: Literal["pi.similar/v1"] = Field(alias="schema")
    kind: Literal["similar_not_same_product"] = "similar_not_same_product"
    meta: Meta
    similar: tuple[Similar, ...]

    @model_validator(mode="after")
    def _unique_and_bounded(self) -> Self:
        seen: set[tuple[str, str]] = set()
        for entry in self.similar:
            key = (entry.product, entry.retailer)
            if key in seen:
                msg = f"{key}: listed twice"
                raise ValueError(msg)
            seen.add(key)
            per_retailer: dict[str, int] = {}
            for found in entry.competitors:
                per_retailer[found.retailer] = per_retailer.get(found.retailer, 0) + 1
            if any(count > self.meta.k for count in per_retailer.values()):
                msg = f"{key}: more than k={self.meta.k} competitors at one retailer"
                raise ValueError(msg)
        return self


def load_similar(raw: str | bytes) -> SimilarFile:
    return SimilarFile.model_validate_json(raw)


def dump_similar(found: SimilarFile) -> str:
    return found.model_dump_json(by_alias=True, indent=2) + "\n"
