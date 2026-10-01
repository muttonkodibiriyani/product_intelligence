"""smoke_app's URL comparison after Back (no browser, no Firebase)."""

from smoke_app import same_view

BASE = "https://example.web.app/app/en/explore/"


def test_space_encodings_are_the_same_view() -> None:
    # The script narrows with %20; the app's Back link (URLSearchParams) writes +.
    assert same_view(f"{BASE}?brand=The%20Ordinary", f"{BASE}?brand=The+Ordinary")


def test_key_order_does_not_matter() -> None:
    assert same_view(f"{BASE}?brand=A&retailer=x", f"{BASE}?retailer=x&brand=A")


def test_different_filters_or_page_are_not_the_same_view() -> None:
    assert not same_view(f"{BASE}?brand=The+Ordinary", f"{BASE}?brand=The+Inkey")
    assert not same_view(f"{BASE}?brand=A", f"{BASE}?brand=A&brand=B")
    assert not same_view(f"{BASE}?brand=A", "https://example.web.app/app/en/product/?brand=A")
