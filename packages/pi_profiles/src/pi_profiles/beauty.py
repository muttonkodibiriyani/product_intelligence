"""``beauty@1``: the attributes beauty publishes today (ADR-0008 §3).

The beauty columns on ``variant`` (shade, finish, concentration, ...) stay where they are and this
profile reads them (ADR-0007 §4.1), so beauty needs no data migration. The model declares the
product-level keys that ``pi.dataset/v2`` already publishes, under the same wire keys.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from pi_core.types import NonEmptyStr
from pi_dataset import AttributeBlock, AttributeType
from pi_profiles.base import Attr, AttributeModel, VerticalProfile


class BeautyAttributesV1(AttributeModel):
    finish: Annotated[
        NonEmptyStr | None,
        Attr(
            AttributeType.TEXT,
            label={"en": "Finish", "ar": "اللمسة النهائية"},
            facet=True,
            block=AttributeBlock.SUMMARY,
        ),
    ] = None
    concentration: Annotated[
        NonEmptyStr | None,
        Attr(
            AttributeType.TEXT,
            label={"en": "Concentration", "ar": "التركيز"},
            facet=True,
            block=AttributeBlock.SUMMARY,
        ),
    ] = None
    shade_families: Annotated[
        tuple[NonEmptyStr, ...],
        Attr(
            AttributeType.TEXT_LIST,
            label={"en": "Shade families", "ar": "عائلات الدرجات"},
            facet=True,
            block=AttributeBlock.SWATCHES,
        ),
        Field(alias="shadeFamilies"),
    ] = ()


BEAUTY_V1 = VerticalProfile(
    name="beauty",
    version=1,
    attributes=BeautyAttributesV1,
    size_labels_comparable=False,
    size_system_required=False,
)
