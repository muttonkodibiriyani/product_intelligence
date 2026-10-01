"""Firebase ID token verification, in-process and fail-closed (design §4).

Tokens arrive only as ``Authorization: Bearer``; cookies are never read. Google's public
certificates are fetched over HTTPS and cached for their ``max-age``. Any doubt is a rejection.
"""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Callable, Mapping
from enum import StrEnum
from typing import Protocol

import httpx
import jwt
from cryptography.x509 import load_pem_x509_certificate

from pi_core import PiModel

CERTS_URL = (
    "https://www.googleapis.com/robot/v1/metadata/x509/securetoken@system.gserviceaccount.com"
)
_MAX_AGE = re.compile(r"max-age=(\d+)")
#: Clock skew tolerated on ``iat``/``exp``/``auth_time``, in seconds.
LEEWAY = 60


class Role(StrEnum):
    VIEWER = "viewer"
    ADMIN = "admin"


class Principal(PiModel):
    uid: str
    role: Role


class AuthError(Exception):
    """``status`` is 401 (no valid token) or 403 (valid token, no known role)."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


class CertSource(Protocol):
    def certificates(self) -> Mapping[str, str]:
        """``kid`` → PEM certificate, current for Google's signing keys."""
        ...


class HttpCertSource:
    """Fetches the certificates and keeps them for the response's ``max-age``."""

    def __init__(
        self,
        url: str = CERTS_URL,
        clock: Callable[[], float] = time.monotonic,
        client: httpx.Client | None = None,
    ) -> None:
        self._url = url
        self._client = client or httpx.Client(timeout=5.0, follow_redirects=False)
        self._clock = clock
        self._lock = threading.Lock()
        self._certs: Mapping[str, str] = {}
        self._expires = 0.0

    def certificates(self) -> Mapping[str, str]:
        with self._lock:
            if self._clock() >= self._expires:
                response = self._client.get(self._url)
                response.raise_for_status()
                certs = response.json()
                if not isinstance(certs, dict) or not all(
                    isinstance(k, str) and isinstance(v, str) for k, v in certs.items()
                ):
                    msg = "unexpected certificate document"
                    raise ValueError(msg)
                match = _MAX_AGE.search(response.headers.get("cache-control", ""))
                self._certs = certs
                self._expires = self._clock() + (int(match.group(1)) if match else 300)
            return self._certs


class TokenVerifier:
    def __init__(
        self, project_id: str, certs: CertSource, now: Callable[[], float] = time.time
    ) -> None:
        self._project_id = project_id
        self._certs = certs
        self._now = now

    def verify(self, authorization: str | None) -> Principal:
        token = _bearer(authorization)
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError:
            raise _unauthenticated("malformed token") from None
        if header.get("alg") != "RS256":
            raise _unauthenticated("unexpected token algorithm")
        try:
            pem = self._certs.certificates().get(str(header.get("kid")))
        except (httpx.HTTPError, ValueError):
            raise _unauthenticated("signing keys unavailable") from None
        if pem is None:
            raise _unauthenticated("unknown signing key")
        key = load_pem_x509_certificate(pem.encode()).public_key()
        try:
            claims = jwt.decode(
                token,
                key=key,  # type: ignore[arg-type]
                algorithms=["RS256"],
                audience=self._project_id,
                issuer=f"https://securetoken.google.com/{self._project_id}",
                leeway=LEEWAY,
                options={"require": ["exp", "iat", "aud", "iss", "sub", "auth_time"]},
            )
        except jwt.PyJWTError:
            raise _unauthenticated("invalid token") from None
        now = self._now()
        sub, auth_time = claims.get("sub"), claims.get("auth_time")
        if not isinstance(sub, str) or not 0 < len(sub) <= 128:
            raise _unauthenticated("invalid subject")
        if not isinstance(auth_time, int) or auth_time > now + LEEWAY:
            raise _unauthenticated("invalid auth_time")
        if claims["iat"] > now + LEEWAY:
            raise _unauthenticated("token issued in the future")
        role = claims.get("role")
        if role not in {r.value for r in Role}:
            raise AuthError(403, "forbidden", "no role for this account")
        return Principal(uid=sub, role=Role(role))


def _bearer(authorization: str | None) -> str:
    if not authorization:
        raise _unauthenticated("missing bearer token")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip() or " " in token.strip():
        raise _unauthenticated("missing bearer token")
    return token.strip()


def _unauthenticated(message: str) -> AuthError:
    return AuthError(401, "unauthenticated", message)
