"""Draft → canonical pi_core records, once the pipeline knows the ids.

The pipeline writes the evidence and upserts the listing first, then calls ``to_canonical``.
The canonical model is built with full validation (``model_validate``), never by
``model_construct`` or ``model_copy(update=...)``, so every pi_core rule runs again.
"""

from datetime import datetime
from typing import Any, overload

from pi_core import CollectionContext, ListingRecord, OfferObservation
from pi_core.types import DbId
from pi_fetch.connector import ListingDraft, OfferDraft


def _fields(draft: ListingDraft | OfferDraft) -> dict[str, Any]:
    # Shallow: nested pi_core models (images, instalment plan) are already validated and frozen.
    return {name: getattr(draft, name) for name in type(draft).model_fields}


@overload
def to_canonical(
    draft: ListingDraft, *, source_id: DbId, evidence_id: DbId, source_listing_id: None = None
) -> ListingRecord: ...


@overload
def to_canonical(
    draft: OfferDraft,
    *,
    source_id: None = None,
    evidence_id: DbId,
    source_listing_id: DbId,
    ingested_at: datetime,
    context: CollectionContext,
) -> OfferObservation: ...


def to_canonical(  # noqa: PLR0913 - keyword-only, one id set per draft kind
    draft: ListingDraft | OfferDraft,
    *,
    source_id: DbId | None = None,
    evidence_id: DbId,
    source_listing_id: DbId | None = None,
    ingested_at: datetime | None = None,
    context: CollectionContext | None = None,
) -> ListingRecord | OfferObservation:
    """Attach the pipeline-assigned values to a draft and validate the canonical record.

    A listing takes ``source_id`` and ``evidence_id``. An offer takes ``source_listing_id``,
    ``evidence_id``, the pipeline's ``ingested_at`` and the ``context`` it was collected under;
    the observation must belong to that context's run and use its currency.
    """
    values = _fields(draft)
    if isinstance(draft, ListingDraft):
        if source_id is None or any(
            v is not None for v in (source_listing_id, ingested_at, context)
        ):
            msg = "listing conversion requires source_id and evidence_id only"
            raise ValueError(msg)
        return ListingRecord.model_validate(
            values | {"source_id": source_id, "evidence_id": evidence_id}
        )
    if source_id is not None or source_listing_id is None or ingested_at is None or context is None:
        msg = "offer conversion requires source_listing_id, ingested_at and context"
        raise ValueError(msg)
    del values["source_listing_key"]
    observation = OfferObservation.model_validate(
        values
        | {
            "source_listing_id": source_listing_id,
            "evidence_id": evidence_id,
            "ingested_at": ingested_at,
        }
    )
    observation.check_context(context)
    return observation
