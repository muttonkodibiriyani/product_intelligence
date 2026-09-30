"""Offline parsers for recorded Ulta UAE payloads."""

from __future__ import annotations

import json
from decimal import Decimal
from html.parser import HTMLParser
from typing import Any

from pydantic import ValidationError

from pi_connector_ulta._pi_fetch_stub import ParseError
from pi_connector_ulta.models import ProductRecord

__all__ = ["ParseError", "parse_product_html", "parse_product_json"]


def _reject_constant(value: str) -> None:
    raise ParseError(f"non-finite JSON number is not allowed: {value}")


def parse_product_json(document: str) -> ProductRecord:
    """Parse a recorded product JSON document without binary-float prices."""
    try:
        payload: Any = json.loads(
            document,
            parse_float=Decimal,
            parse_int=int,
            parse_constant=_reject_constant,
        )
    except (json.JSONDecodeError, TypeError) as exc:
        raise ParseError("invalid product JSON") from exc
    try:
        # Input decoding is deliberately non-strict: JSON has no Decimal or enum scalar types.
        # The resulting frozen model is typed and all domain validators still run.
        return ProductRecord.model_validate(payload, strict=False)
    except ValidationError as exc:
        raise ParseError("product JSON violates the Ulta source contract") from exc


class _SourceRecordScriptParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._capturing = False
        self._parts: list[str] = []
        self.documents: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        self._capturing = tag == "script" and attributes.get("id") == "ulta-source-record"
        if self._capturing:
            self._parts = []

    def handle_data(self, data: str) -> None:
        if self._capturing:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._capturing:
            self.documents.append("".join(self._parts))
            self._capturing = False


def parse_product_html(document: str) -> ProductRecord:
    """Parse embedded product state from an already-fetched product page."""
    parser = _SourceRecordScriptParser()
    parser.feed(document)
    parser.close()
    if len(parser.documents) != 1:
        raise ParseError("expected exactly one ulta-source-record script")
    return parse_product_json(parser.documents[0])
