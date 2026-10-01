"""URL helpers for smoke_app, kept free of third-party imports so they are unit-tested in CI."""

from urllib.parse import parse_qs, urlsplit


def same_view(a: str, b: str) -> bool:
    """Same path and same decoded query: the app writes a space as + where quote() writes %20."""
    ua, ub = urlsplit(a), urlsplit(b)
    return (ua.path, parse_qs(ua.query)) == (ub.path, parse_qs(ub.query))
