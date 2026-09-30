"""Firestore and Storage security rules, exercised against the Firebase emulators over REST.

Runs only under the emulators (they set FIRESTORE_EMULATOR_HOST / FIREBASE_STORAGE_EMULATOR_HOST):

    npx firebase-tools@14 emulators:exec --config infra/firebase.json --project demo-pi \
        --only firestore,storage "uv run pytest infra/tests -m emulator"

Nothing is seeded: a read the rules allow on a missing object is 404, a denied one is 403, so the
status code alone says which way the rules decided.
"""

import base64
import json
import os
import time
from typing import Any
from urllib.parse import quote

import httpx
import pytest

PROJECT = os.environ.get("GCLOUD_PROJECT", "demo-pi")
BUCKET = f"{PROJECT}.appspot.com"
FIRESTORE = os.environ.get("FIRESTORE_EMULATOR_HOST")
STORAGE = os.environ.get("FIREBASE_STORAGE_EMULATOR_HOST")

# A skip mark, not a module-level skip: `-m "not emulator"` / `-m browser` then deselect these
# tests instead of reporting a collection skip (CI refuses skips in those runs).
pytestmark = [
    pytest.mark.emulator,
    pytest.mark.skipif(
        not (FIRESTORE and STORAGE), reason="Firebase emulators not running (see module docstring)"
    ),
]

ALLOWED = 404  # rules allowed the read; the object just doesn't exist
DENIED = 403


def _b64(data: dict[str, Any]) -> str:
    return base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")


def token(**claims: Any) -> str:
    """Unsigned ID token; the emulators accept alg=none."""
    now = int(time.time())
    payload = {
        "iss": f"https://securetoken.google.com/{PROJECT}",
        "aud": PROJECT,
        "sub": "u1",
        "user_id": "u1",
        "iat": now,
        "auth_time": now,
        "exp": now + 3600,
        "email": "u1@example.test",
        "firebase": {"sign_in_provider": "password", "identities": {}},
        **claims,
    }
    return f"{_b64({'alg': 'none', 'typ': 'JWT'})}.{_b64(payload)}."


USERS: dict[str, str | None] = {
    "anonymous": None,
    "signed-in, no role": token(),
    "signed-in, unknown role": token(role="guest"),
    "viewer": token(role="viewer"),
    "admin": token(role="admin"),
}
INVITED = {"viewer", "admin"}


def firestore_get(path: str, who: str) -> int:
    url = f"http://{FIRESTORE}/v1/projects/{PROJECT}/databases/(default)/documents/{path}"
    tok = USERS[who]
    headers = {"Authorization": f"Bearer {tok}"} if tok else {}
    return httpx.get(url, headers=headers, timeout=10).status_code


def firestore_write(path: str, who: str) -> int:
    url = f"http://{FIRESTORE}/v1/projects/{PROJECT}/databases/(default)/documents/{path}"
    tok = USERS[who]
    headers = {"Authorization": f"Bearer {tok}"} if tok else {}
    body = {"fields": {"x": {"stringValue": "y"}}}
    return httpx.patch(url, headers=headers, json=body, timeout=10).status_code


def storage_get(name: str, who: str) -> int:
    quoted = quote(name, safe="")
    url = f"http://{STORAGE}/v0/b/{BUCKET}/o/{quoted}?alt=media"
    tok = USERS[who]
    headers = {"Authorization": f"Firebase {tok}"} if tok else {}
    return httpx.get(url, headers=headers, timeout=10).status_code


def storage_write(name: str, who: str) -> int:
    """A multipart upload, as the web SDK sends one (a bare POST body hangs the emulator)."""
    url = f"http://{STORAGE}/v0/b/{BUCKET}/o"
    boundary = "pi-rules-test"
    body = (
        f"--{boundary}\r\nContent-Type: application/json; charset=utf-8\r\n\r\n"
        f"{json.dumps({'name': name})}\r\n"
        f"--{boundary}\r\nContent-Type: application/json\r\n\r\n{{}}\r\n--{boundary}--"
    )
    tok = USERS[who]
    headers = {
        "X-Goog-Upload-Protocol": "multipart",
        "Content-Type": f"multipart/related; boundary={boundary}",
    }
    if tok:
        headers["Authorization"] = f"Firebase {tok}"
    return httpx.post(
        url, params={"name": name}, headers=headers, content=body.encode(), timeout=10
    ).status_code


@pytest.mark.parametrize("who", list(USERS))
def test_firestore_demo_collections_are_readable_only_by_invited_roles(who: str) -> None:
    assert firestore_get("demo_meta/current", who) == (ALLOWED if who in INVITED else DENIED)


# The assistant's meter and config are written only by its service account (Admin SDK).
ASSISTANT_PATHS = [
    "assistant_config/current",
    "assistant_usage_counters/total|2026-09",
    "assistant_reservations/r1",
]


@pytest.mark.parametrize("who", list(USERS))
@pytest.mark.parametrize(
    "path", ["users/u1", "demometa/current", "x_demo_meta/current", *ASSISTANT_PATHS]
)
def test_firestore_non_demo_collections_are_denied_to_everyone(path: str, who: str) -> None:
    assert firestore_get(path, who) == DENIED


@pytest.mark.parametrize("who", list(USERS))
@pytest.mark.parametrize("path", ["demo_meta/current", "users/u1", *ASSISTANT_PATHS])
def test_firestore_clients_never_write(path: str, who: str) -> None:
    assert firestore_write(path, who) == DENIED


@pytest.mark.parametrize("who", list(USERS))
def test_storage_datasets_are_readable_only_by_invited_roles(who: str) -> None:
    status = storage_get("datasets/uae/latest.json", who)
    assert status == (ALLOWED if who in INVITED else DENIED)


@pytest.mark.parametrize("who", list(USERS))
@pytest.mark.parametrize("name", ["private/x.json", "datasetsX/latest.json", "latest.json"])
def test_storage_outside_datasets_is_denied_to_everyone(name: str, who: str) -> None:
    assert storage_get(name, who) == DENIED


@pytest.mark.parametrize("who", list(USERS))
@pytest.mark.parametrize("name", ["datasets/uae/latest.json", "uploads/x.json"])
def test_storage_clients_never_write(name: str, who: str) -> None:
    assert storage_write(name, who) == DENIED
