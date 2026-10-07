"""``beauty@1``: the attributes beauty publishes today (ADR-0008 §3); ``beauty@2`` adds the
extracted attributes of ADR-0008 §5.

The beauty columns on ``variant`` (shade, finish, concentration, ...) stay where they are and this
profile reads them (ADR-0007 §4.1), so beauty needs no data migration. ``beauty@1`` declares the
product-level keys that ``pi.dataset/v2`` already publishes, under the same wire keys. ``beauty@2``
keeps them unchanged and adds ``sunProtectionFactor``, ``gender``, ``skinTypes``,
``makeupCoverage``, ``productForm``, ``keyIngredients`` and the offer-level
``giftWithPurchase``. Closed vocabularies are ``Literal`` types, so the write path refuses any
other value.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, StringConstraints

from pi_core.types import NonEmptyStr
from pi_dataset import AttributeBlock, AttributeLevel, AttributeType
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


#: ``skinTypes`` and ``makeupCoverage`` ids: closed ``values`` lists on ``text_list`` keys
#: (ADR-0008 §5). The ids are declared, so the literal guard scans for them: they avoid words that
#: code already quotes (``all``, ``medium``, ``full``).
SkinType = Literal["normal", "dry", "oily", "combination", "sensitive", "all_skin_types"]
Coverage = Literal["sheer_coverage", "light_coverage", "medium_coverage", "full_coverage"]
#: The stated SPF as decimal text (``"50"``, ``"30.5"``), never a float.
SpfText = Annotated[str, StringConstraints(pattern=r"^[1-9][0-9]{0,2}(\.[0-9]+)?$")]


def _enum(*values: tuple[str, str, str]) -> tuple[tuple[str, dict[str, str]], ...]:
    return tuple((i, {"en": en, "ar": ar}) for i, en, ar in values)


class BeautyAttributesV2(BeautyAttributesV1):
    sun_protection_factor: Annotated[
        SpfText | None,
        Attr(
            AttributeType.DECIMAL,
            label={"en": "SPF", "ar": "عامل الحماية من الشمس"},
            facet=True,
            block=AttributeBlock.SUMMARY,
        ),
        Field(alias="sunProtectionFactor"),
    ] = None
    gender: Annotated[
        Literal["women", "men", "unisex"] | None,
        Attr(
            AttributeType.ENUM,
            label={"en": "Gender", "ar": "الفئة"},
            facet=True,
            block=AttributeBlock.SUMMARY,
            values=_enum(
                ("women", "Women", "نساء"),
                ("men", "Men", "رجال"),
                ("unisex", "Unisex", "للجنسين"),
            ),
        ),
    ] = None
    skin_types: Annotated[
        tuple[SkinType, ...],
        Attr(
            AttributeType.TEXT_LIST,
            label={"en": "Skin types", "ar": "أنواع البشرة"},
            facet=True,
            block=AttributeBlock.SUMMARY,
            values=_enum(
                ("normal", "Normal", "عادية"),
                ("dry", "Dry", "جافة"),
                ("oily", "Oily", "دهنية"),
                ("combination", "Combination", "مختلطة"),
                ("sensitive", "Sensitive", "حساسة"),
                ("all_skin_types", "All skin types", "جميع أنواع البشرة"),
            ),
        ),
        Field(alias="skinTypes"),
    ] = ()
    makeup_coverage: Annotated[
        tuple[Coverage, ...],
        Attr(
            AttributeType.TEXT_LIST,
            label={"en": "Coverage", "ar": "التغطية"},
            facet=True,
            block=AttributeBlock.SUMMARY,
            values=_enum(
                ("sheer_coverage", "Sheer", "شفافة"),
                ("light_coverage", "Light", "خفيفة"),
                ("medium_coverage", "Medium", "متوسطة"),
                ("full_coverage", "Full", "كاملة"),
            ),
        ),
        Field(alias="makeupCoverage"),
    ] = ()
    product_form: Annotated[
        NonEmptyStr | None,
        Attr(
            AttributeType.TEXT,
            label={"en": "Form", "ar": "القوام"},
            facet=True,
            block=AttributeBlock.SUMMARY,
        ),
        Field(alias="productForm"),
    ] = None
    key_ingredients: Annotated[
        tuple[NonEmptyStr, ...],
        Attr(
            AttributeType.TEXT_LIST,
            label={"en": "Key ingredients", "ar": "المكونات الرئيسية"},
            block=AttributeBlock.SUMMARY,
        ),
        Field(alias="keyIngredients"),
    ] = ()
    #: The retailer's own titles of the gifts that come with this offer (Sephora
    #: ``labels.gift_with_purchase``, Faces "Free Gifts"). A label only: no price change.
    gift_with_purchase: Annotated[
        tuple[NonEmptyStr, ...],
        Attr(
            AttributeType.TEXT_LIST,
            label={"en": "Gift with purchase", "ar": "هدية مع الشراء"},
            level=AttributeLevel.OFFER,
        ),
        Field(alias="giftWithPurchase"),
    ] = ()


BEAUTY_V2 = VerticalProfile(
    name="beauty",
    version=2,
    attributes=BeautyAttributesV2,
    size_labels_comparable=False,
    size_system_required=False,
)
