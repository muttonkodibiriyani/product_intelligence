"""Raw evidence behind every parsed value (``evidence``; DAT-04, ADR-0003).

``ladder_rung_used`` and ``fetch_method`` are recorded per evidence row, not only per run, because
a run can escalate part-way through and every observation must trace to the method that got it.
"""

from datetime import datetime
from typing import Self
from uuid import UUID

from pydantic import Field, HttpUrl, model_validator

from pi_core.base import PiModel
from pi_core.context import CollectionContext, check_rung
from pi_core.enums import FetchMethod, LadderRung
from pi_core.ids import stable_id
from pi_core.types import ContentHash, NonEmptyStr, UtcDatetime, content_hash_of


class Evidence(PiModel):
    """One retrieved payload: where it came from, when, how, and its content hash."""

    crawl_run_id: UUID
    url: HttpUrl
    content_hash: ContentHash
    storage_uri: NonEmptyStr
    retrieved_at: UtcDatetime
    http_status: int = Field(ge=100, le=599)
    ladder_rung_used: LadderRung
    fetch_method: FetchMethod
    retention_until: UtcDatetime | None = None

    @model_validator(mode="after")
    def _check_invariants(self) -> Self:
        check_rung(self.ladder_rung_used, self.fetch_method)
        if self.retention_until is not None and self.retention_until <= self.retrieved_at:
            msg = "retention_until must be after retrieved_at"
            raise ValueError(msg)
        return self

    @property
    def id(self) -> UUID:
        """Stable id: the same bytes from the same URL in the same run are one evidence row."""
        return stable_id("evidence", self.crawl_run_id, self.url, self.content_hash)

    @classmethod
    def from_payload(  # noqa: PLR0913 - keyword-only, mirrors the evidence columns
        cls,
        context: CollectionContext,
        *,
        url: str,
        payload: bytes,
        storage_uri: str,
        retrieved_at: datetime,
        http_status: int,
    ) -> Self:
        """Build evidence for ``payload`` fetched under ``context``, hashing it here."""
        return cls.model_validate(
            {
                "crawl_run_id": context.crawl_run_id,
                "url": url,
                "content_hash": content_hash_of(payload),
                "storage_uri": storage_uri,
                "retrieved_at": retrieved_at,
                "http_status": http_status,
                "ladder_rung_used": context.ladder_rung_used,
                "fetch_method": context.fetch_method,
            }
        )
