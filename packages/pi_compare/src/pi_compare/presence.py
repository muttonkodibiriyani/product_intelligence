"""Retailer matrix state without false absence claims."""

from __future__ import annotations

from datetime import date

from pi_compare.models import MatrixState, RetailerCell


def retailer_cell(  # noqa: PLR0913 - every input is a named part of the matrix evidence
    *,
    retailer: str,
    as_of: date,
    generation: str,
    accepted_tokens: tuple[str, ...] = (),
    ambiguous_tokens: tuple[str, ...] = (),
    complete_capture: bool,
    completeness_basis: str,
) -> RetailerCell:
    """Derive one cell. Only an explicit complete-capture input permits ``absent``."""
    accepted = tuple(sorted(set(accepted_tokens)))
    ambiguous = tuple(sorted(set(ambiguous_tokens) - set(accepted)))
    if accepted:
        state = MatrixState.PRESENT
        ambiguous = ()
    elif ambiguous:
        state = MatrixState.AMBIGUOUS
    elif complete_capture:
        state = MatrixState.ABSENT
    else:
        state = MatrixState.NOT_OBSERVED
    return RetailerCell(
        retailer=retailer,
        state=state,
        as_of=as_of,
        generation=generation,
        listing_tokens=accepted,
        ambiguous_tokens=ambiguous,
        completeness_basis=completeness_basis,
    )
