"""Retailer- and operator-authored text on the wire: raw, controls stripped, tagged.

``x-pi-source-text`` in the OpenAPI schema marks every field a page or a person wrote, so the
assistant can wrap it as untrusted and the dashboard knows it is page text. It lives here, below
``pi_metrics`` and ``pi_api``, so a metric's own models can be tagged too (API 1.4.0).
"""

from __future__ import annotations

import re
import unicodedata
from typing import Annotated

from pydantic import Field, PlainSerializer

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
