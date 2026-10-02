"""What every transport returns, before block detection, redaction and evidence storage."""

from collections.abc import Mapping
from typing import Protocol

from pydantic import Field

from pi_core import PiModel
from pi_fetch.types import CapturedJson, FetchRequest


class TransportError(Exception):
    """The request did not complete (DNS, connect, timeout, browser crash). Not a block."""


class RawResponse(PiModel):
    """A completed response, unredacted: ``headers`` keeps every pair, cookies included."""

    final_url: str
    status: int = Field(ge=100, le=599)
    headers: tuple[tuple[str, str], ...]
    body: bytes
    content_type: str | None
    captured_json: tuple[CapturedJson, ...] = ()
    elapsed_ms: int = Field(ge=0)


class Transport(Protocol):
    """Sends exactly one request per call: no retries, no challenge handling."""

    def send(self, request: FetchRequest, headers: Mapping[str, str]) -> RawResponse:
        """Fetch ``request`` with the fetch layer's ``headers``; raise ``TransportError``."""
        ...

    def close(self) -> None:
        """Release connections or the browser."""
        ...
