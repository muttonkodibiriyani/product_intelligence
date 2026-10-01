"""Token verification (design §4): every failure is a 401, 403 or 503, never a pass."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from typing import Any

import jwt
import pytest

from api_fixture import CERT, KID, NOW, OTHER_KEY, PROJECT, FakeCerts, claims, token
from pi_api.auth import AuthError, CertificatesUnavailableError, Role, TokenVerifier


def verifier(certs: FakeCerts | None = None) -> TokenVerifier:
    return TokenVerifier(PROJECT, certs or FakeCerts(), now=lambda: NOW)


def status_of(header: str | None, certs: FakeCerts | None = None) -> int:
    with pytest.raises(AuthError) as caught:
        verifier(certs).verify(header)
    return caught.value.status


def test_a_valid_token_gives_the_principal() -> None:
    who = verifier().verify(f"Bearer {token(role='admin', sub='u-9')}")
    assert (who.uid, who.role) == ("u-9", Role.ADMIN)


@pytest.mark.parametrize(
    "header",
    [None, "", "Bearer", "Bearer ", "Basic abc", "bearer", "Token x", "Bearer not.a.jwt"],
)
def test_missing_or_malformed_headers_are_401(header: str | None) -> None:
    assert status_of(header) == 401


@pytest.mark.parametrize(
    "overrides",
    [
        {"aud": "other-project"},
        {"iss": "https://securetoken.google.com/other-project"},
        {"iss": "https://accounts.google.com"},
        {"exp": int(NOW) - 3600},
        {"iat": int(NOW) + 3600},
        {"auth_time": int(NOW) + 3600},
        {"sub": ""},
        {"sub": "x" * 129},
        {"sub": None},
        {"auth_time": None},
        {"exp": None},
    ],
)
def test_bad_claims_are_401(overrides: dict[str, Any]) -> None:
    assert status_of(f"Bearer {token(**overrides)}") == 401


def test_a_token_signed_by_another_key_is_401() -> None:
    assert status_of(f"Bearer {token(key=OTHER_KEY)}") == 401


def test_an_unknown_kid_is_401() -> None:
    assert status_of(f"Bearer {token(kid='rotated-away')}") == 401


def test_alg_none_and_hs256_are_401() -> None:
    unsigned = jwt.encode(claims(), "", algorithm="none", headers={"kid": KID})
    assert status_of(f"Bearer {unsigned}") == 401
    # The classic confusion attack: HMAC keyed with the public certificate.
    assert status_of(f"Bearer {_hs256(CERT.encode())}") == 401


def _hs256(secret: bytes) -> str:
    def part(data: dict[str, Any]) -> bytes:
        return base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=")

    signing = part({"alg": "HS256", "typ": "JWT", "kid": KID}) + b"." + part(claims())
    mac = hmac.new(secret, signing, hashlib.sha256).digest()
    return (signing + b"." + base64.urlsafe_b64encode(mac).rstrip(b"=")).decode()


def test_unavailable_signing_keys_fail_closed_as_retryable_503() -> None:
    class Broken(FakeCerts):
        def certificates(self) -> dict[str, str]:
            raise CertificatesUnavailableError

    assert status_of(f"Bearer {token()}", Broken()) == 503


def test_an_unknown_kid_while_serving_stale_keys_is_503_not_a_sign_out() -> None:
    assert status_of(f"Bearer {token()}", FakeCerts({"other-kid": CERT}, stale=True)) == 503
    assert status_of(f"Bearer {token()}", FakeCerts({"other-kid": CERT})) == 401


def test_an_unreadable_certificate_fails_closed_as_503() -> None:
    assert status_of(f"Bearer {token()}", FakeCerts({KID: "not a pem"})) == 503


@pytest.mark.parametrize("role", [None, "", "owner", "ADMIN"])
def test_a_missing_or_unknown_role_is_403(role: str | None) -> None:
    assert status_of(f"Bearer {token(role=role)}") == 403
