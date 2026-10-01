"""The response envelope, error shape and wire types every endpoint shares (design §5)."""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from typing import Annotated, Any

from pydantic import Field, PlainSerializer

from pi_dataset import ContractModel
from pi_metrics import METRIC_VERSION, Caveat, CaveatCode, Cohort, Metric, Reason, Status

API_VERSION = "1.2.0"
_CONTROLS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")


def strip_controls(text: str) -> str:
    """Retailer and operator text is returned raw except C0/C1 controls (``\\t\\n`` kept)."""
    return _CONTROLS.sub("", unicodedata.normalize("NFC", text))


#: Text written by a retailer, operator or the matcher: raw, controls stripped, tagged in OpenAPI.
SourceText = Annotated[
    str,
    PlainSerializer(strip_controls, return_type=str),
    Field(json_schema_extra={"x-pi-source-text": True}),
]


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
}

CAVEAT_TEXT: dict[CaveatCode, Localized] = {
    CaveatCode.RETAILER_PARTIAL: Localized(
        en="{retailer} is only partly collected.", ar="بيانات {retailer} مجمّعة جزئياً."
    ),
    CaveatCode.EARLY_EXCLUDED: Localized(
        en="{count} early sample items are not counted.",
        ar="لم تُحتسب {count} من عناصر العينة المبكرة.",
    ),
    CaveatCode.LAUNCHES_WITHHELD: Localized(
        en="{count} items first seen after an incomplete run are not shown as launches.",
        ar="{count} عناصر ظهرت لأول مرة بعد جمع غير مكتمل لا تُعرض كإطلاقات.",
    ),
    CaveatCode.REMOVED_UNCONFIRMED: Localized(
        en="{count} removals are unconfirmed and shown as not observed.",
        ar="{count} حالات إزالة غير مؤكدة وتُعرض كغير مرصودة.",
    ),
    CaveatCode.NOT_OBSERVED_EXCLUDED: Localized(
        en="{count} items were not observed and are left out.",
        ar="{count} عناصر لم تُرصد واستُبعدت.",
    ),
    CaveatCode.HISTORY_OFF: Localized(
        en="History is not collected: only the latest date is shown.",
        ar="لا يُجمع السجل: يُعرض آخر تاريخ فقط.",
    ),
    CaveatCode.RATING_SCALE_MIXED: Localized(
        en="{count} ratings at {retailer} use another scale and are left out.",
        ar="{count} تقييمات في {retailer} تستخدم مقياساً آخر واستُبعدت.",
    ),
    CaveatCode.SIZE_LABELS_DIFFER: Localized(
        en="{count} items have equal sizes labelled differently: {base} vs {other}.",
        ar="{count} عناصر بأحجام متساوية وتسميات مختلفة: {base} مقابل {other}.",
    ),
    CaveatCode.CHANNEL_DIFFERS: Localized(
        en="The two sides are different channels: {base} vs {other}.",
        ar="الجانبان قناتان مختلفتان: {base} مقابل {other}.",
    ),
    CaveatCode.SIZE_LABELS_DIFFER_TOTAL: Localized(
        en=(
            "{count} items have equal sizes labelled differently across {pairs} label pairs;"
            " the most frequent are listed."
        ),
        ar=(
            "{count} عناصر بأحجام متساوية وتسميات مختلفة عبر {pairs} أزواج من التسميات؛"
            " نعرض الأكثر تكرارًا."
        ),
    ),
}


class CaveatView(ContractModel):
    code: CaveatCode
    params: dict[str, str]
    en: str
    ar: str


def render(caveat: Caveat) -> CaveatView:
    text = CAVEAT_TEXT[caveat.code]
    return CaveatView(
        code=caveat.code,
        params=caveat.params,
        en=text.en.format_map(caveat.params),
        ar=text.ar.format_map(caveat.params),
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
