"""The response envelope, error shape and wire types every endpoint shares (design §5)."""

from __future__ import annotations

import string
from datetime import datetime
from typing import Any

from pydantic import Field

from pi_dataset import ContractModel
from pi_metrics import METRIC_VERSION, Caveat, CaveatCode, Cohort, Metric, Reason, Status

API_VERSION = "1.21.0"


class Localized(ContractModel):
    en: str
    ar: str


REASON_TEXT: dict[Reason, Localized] = {
    Reason.CAPABILITY_OFF: Localized(
        en="This dataset does not collect what this view needs.",
        ar="مجموعة البيانات هذه لا تجمع ما يحتاجه هذا العرض.",
    ),
    Reason.FIELD_NOT_COLLECTED: Localized(
        en="The field this view needs is not collected.",
        ar="الحقل الذي يحتاجه هذا العرض غير مُجمَّع.",
    ),
    Reason.RETAILER_BLOCKED: Localized(
        en="A selected retailer could not be collected.",
        ar="تعذّر جمع بيانات أحد المتاجر المحددة.",
    ),
    Reason.RETAILER_PARTIAL: Localized(
        en="A selected retailer is only partly collected.",
        ar="بيانات أحد المتاجر المحددة مجمّعة جزئياً فقط.",
    ),
    Reason.COHORT_TOO_SMALL: Localized(
        en="Fewer than 5 comparable items: no summary is shown.",
        ar="أقل من 5 عناصر قابلة للمقارنة: لا يُعرض ملخص.",
    ),
    Reason.MATCHES_UNREVIEWED: Localized(
        en="The product matches here have not been reviewed yet.",
        ar="لم تتم مراجعة مطابقات المنتجات هنا بعد.",
    ),
    Reason.NO_MATCH: Localized(
        en="No matched products between these retailers.",
        ar="لا توجد منتجات متطابقة بين هذين المتجرين.",
    ),
    Reason.NOT_IN_SCOPE: Localized(
        en="This is outside the data you can see.",
        ar="هذا خارج نطاق البيانات المتاحة لك.",
    ),
    Reason.CURRENCY_MISMATCH: Localized(
        en="The retailers price in different currencies; there is no conversion.",
        ar="المتاجر تسعّر بعملات مختلفة؛ ولا يوجد تحويل.",
    ),
    Reason.NOT_APPLICABLE: Localized(
        en="This view does not apply to this kind of catalogue.",
        ar="هذا العرض لا ينطبق على هذا النوع من الكتالوجات.",
    ),
    Reason.WAS_PRICE_UNVERIFIED: Localized(
        en="A selected retailer's was-prices are unverified, so its promotions are not measured.",
        ar="أسعار ما قبل الخصم لدى أحد المتاجر المحددة غير موثّقة، لذا لا تُقاس عروضه.",
    ),
}

CAVEAT_TEXT: dict[CaveatCode, Localized] = {
    CaveatCode.RETAILER_PARTIAL: Localized(
        en="{retailer} is only partly collected.", ar="بيانات {retailer} مجمّعة جزئياً."
    ),
    CaveatCode.EARLY_EXCLUDED: Localized(
        en="{count} early sample {count:item is|items are} not counted.",
        ar="عناصر العينة المبكرة غير المحتسبة: {count}.",
    ),
    CaveatCode.LAUNCHES_WITHHELD: Localized(
        en=(
            "{count} {count:item|items} first seen after an incomplete run"
            " {count:is|are} not shown as launches."
        ),
        ar="عناصر ظهرت لأول مرة بعد جمع غير مكتمل ولا تُعرض كإطلاقات: {count}.",
    ),
    CaveatCode.REMOVED_UNCONFIRMED: Localized(
        en="{count} {count:removal is|removals are} unconfirmed and shown as not observed.",
        ar="حالات إزالة غير مؤكدة وتُعرض كغير مرصودة: {count}.",
    ),
    CaveatCode.NOT_OBSERVED_EXCLUDED: Localized(
        en="{count} {count:item was|items were} not observed and {count:is|are} left out.",
        ar="عناصر لم تُرصد واستُبعدت: {count}.",
    ),
    CaveatCode.HISTORY_OFF: Localized(
        en="History is not collected: only the latest date is shown.",
        ar="لا يُجمع السجل: يُعرض آخر تاريخ فقط.",
    ),
    CaveatCode.RATING_SCALE_MIXED: Localized(
        en=(
            "{count} {count:rating|ratings} at {retailer} {count:uses|use} another scale"
            " and {count:is|are} left out."
        ),
        ar="تقييمات في {retailer} تستخدم مقياساً آخر واستُبعدت: {count}.",
    ),
    CaveatCode.SIZE_LABELS_DIFFER: Localized(
        en=(
            "{count} {count:item has|items have} equal sizes labelled differently:"
            " {base} vs {other}."
        ),
        ar="عناصر بأحجام متساوية وتسميات مختلفة ({base} مقابل {other}): {count}.",
    ),
    CaveatCode.CHANNEL_DIFFERS: Localized(
        en="The two sides are different channels: {base} vs {other}.",
        ar="الجانبان قناتان مختلفتان: {base} مقابل {other}.",
    ),
    CaveatCode.SIZE_LABELS_DIFFER_TOTAL: Localized(
        en=(
            "{count} {count:item has|items have} equal sizes labelled differently across"
            " {pairs} label {pairs:pair|pairs}; the most frequent are listed."
        ),
        ar=(
            "عناصر بأحجام متساوية وتسميات مختلفة: {count}، عبر أزواج من التسميات عددها {pairs}؛"
            " نعرض الأكثر تكرارًا."
        ),
    ),
    CaveatCode.WAS_PRICE_UNVERIFIED: Localized(
        en=(
            "{retailer}'s was-prices are unverified: its discounts and promotions are not"
            " shown or measured."
        ),
        ar="أسعار ما قبل الخصم لدى {retailer} غير موثّقة: لا تُعرض خصوماته وعروضه ولا تُقاس.",
    ),
    CaveatCode.WAS_PRICE_STATED: Localized(
        en="{retailer}'s discounts use the was-prices it states itself; PI has not checked them.",
        ar="خصومات {retailer} محسوبة من أسعار ما قبل الخصم التي يذكرها بنفسه، ولم يتحقق منها PI.",
    ),
    CaveatCode.SNAPSHOT_IMPORT_DATE: Localized(
        en="{retailer}: snapshot imported {date}, capture date unknown.",
        ar="{retailer}: لقطة بيانات مستوردة بتاريخ {date}، وتاريخ جمعها غير معروف.",
    ),
    CaveatCode.PARENT_LISTINGS_INCLUDED: Localized(
        en=(
            "{retailer}'s products may include parent listings that repeat their variants,"
            " so its counts can overstate distinct products."
        ),
        ar=(
            "قد تتضمن منتجات {retailer} قوائم رئيسية تكرّر متغيراتها،"
            " فقد تزيد أعداده عن المنتجات الفعلية."
        ),
    ),
    CaveatCode.STALE_SOURCE: Localized(
        en=(
            "{retailer} was last collected on {asOf}: its latest figures are from that date,"
            " older than the other retailers'."
        ),
        ar=(
            "آخر جمع لبيانات {retailer} كان في {asOf}: أحدث أرقامه من ذلك التاريخ،"
            " وهي أقدم من بيانات المتاجر الأخرى."
        ),
    ),
    CaveatCode.INVALID_PRICE_EXCLUDED: Localized(
        en=(
            "{count} {retailer} {count:item had|items had} a price of 0.01 or less, withheld"
            " as invalid and left out of every figure."
        ),
        ar=(
            "عروض لدى {retailer} بسعر 0.01 أو أقل، حُجب سعرها لعدم صحته واستُبعد من كل الأرقام:"
            " {count}."
        ),
    ),
    CaveatCode.UNMAPPED_CATEGORY: Localized(
        en=(
            "{count} {retailer} {count:item|items} could not be placed in a common category"
            " and {count:is|are} listed as unmapped, not in any row."
        ),
        ar=(
            "منتجات لدى {retailer} تعذّر تصنيفها في فئة مشتركة،"
            " فهي مدرجة كغير مصنّفة لا في أي صف: {count}."
        ),
    ),
    CaveatCode.BREADCRUMB_MISSING: Localized(
        en=(
            "{count} {retailer} {count:item has|items have} no category breadcrumb in this data,"
            " so only the broad category is known; fine categories need a future export."
        ),
        ar=(
            "منتجات لدى {retailer} بلا تسلسل فئات في هذه البيانات، فلا تُعرف إلا فئتها العامة؛"
            " الفئات الدقيقة تتطلب تصديرًا لاحقًا: {count}."
        ),
    ),
}


class CaveatView(ContractModel):
    code: CaveatCode
    params: dict[str, str]
    en: str
    ar: str


class _Plural(string.Formatter):
    """``{n:one|other}`` picks by the count param, which is a decimal string."""

    def format_field(self, value: Any, format_spec: str) -> str:
        one, bar, other = format_spec.partition("|")
        if bar:
            return one if value == "1" else other
        return str(super().format_field(value, format_spec))


_PLURAL = _Plural()


def render(caveat: Caveat) -> CaveatView:
    """English counts agree in number; Arabic ends in ``…: n``, which reads right for any n."""
    text = CAVEAT_TEXT[caveat.code]
    return CaveatView(
        code=caveat.code,
        params=caveat.params,
        en=_PLURAL.vformat(text.en, (), caveat.params),
        ar=_PLURAL.vformat(text.ar, (), caveat.params),
    )


class ApiMeta(ContractModel):
    api_version: str = API_VERSION
    endpoint: str
    metric_version: str = METRIC_VERSION
    generation: str
    cutoff: datetime
    market: str
    currency: str
    scope: str
    filters: dict[str, Any]


class Envelope[T](ContractModel):
    status: Status
    data: T | None
    reason: Reason | None = None
    detail: Localized | None = None
    cohort: Cohort | None = None
    caveats: tuple[CaveatView, ...] = ()
    meta: ApiMeta


class ResolvedFrom(ContractModel):
    """An old product id answered with the products it names now (``pi_api.ids``)."""

    requested_id: str
    #: ``data`` is the first; two after a split, supported retailers first.
    current_ids: tuple[str, ...] = Field(min_length=1, max_length=2)


class ProductEnvelope[T](Envelope[T]):
    """``/products/{id}``, its history and the admin view: ``resolvedFrom`` is set when the id
    in the path is an old one (null on an exact match). Clients rewrite their link to
    ``currentIds``."""

    resolved_from: ResolvedFrom | None = None


def envelope[T](metric: Metric[T], meta: ApiMeta) -> Envelope[T]:
    return Envelope[T](
        status=metric.status,
        data=metric.data,
        reason=metric.reason,
        detail=None if metric.reason is None else REASON_TEXT[metric.reason],
        cohort=metric.cohort,
        caveats=tuple(render(c) for c in metric.caveats),
        meta=meta,
    )


class ErrorDetail(ContractModel):
    code: str
    message: str


class ErrorBody(ContractModel):
    error: ErrorDetail


def error_body(code: str, message: str) -> dict[str, Any]:
    return ErrorBody(error=ErrorDetail(code=code, message=message)).model_dump(mode="json")
