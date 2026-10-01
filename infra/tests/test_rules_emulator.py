"""Firestore and Storage security rules, exercised against the Firebase emulators over REST.

Runs only under the emulators (they set FIRESTORE_EMULATOR_HOST / FIREBASE_STORAGE_EMULATOR_HOST):

    npx firebase-tools@14.27.0 emulators:exec --config infra/firebase.json --project demo-pi \
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
    "kill switch": token(role="killswitch"),
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


# The assistant's meter and config are written only by its service account (Admin SDK); the
# kill-switch account may only turn the assistant off (tests at the end of this module).
ASSISTANT_PATHS = [
    "assistant_config/current",
    # Real ids look like "total|2026-09"; rules match the collection, and a raw "|" in the
    # emulator REST path hangs the request, so a plain id stands in.
    "assistant_usage_counters/total-2026-09",
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


# --- Budget-alert kill switch (docs/design/ai-assistant.md §9.4) --------------------------------

CONFIG = "assistant_config/current"
OFF = {"enabled": False, "disabledBy": "budget_alert:92%:2026-10"}


def _fields(data: dict[str, Any]) -> dict[str, Any]:
    def value(item: Any) -> dict[str, Any]:
        if isinstance(item, bool):
            return {"booleanValue": item}
        return {"stringValue": str(item)}

    return {key: value(item) for key, item in data.items()}


def _doc_url(path: str) -> str:
    return f"http://{FIRESTORE}/v1/projects/{PROJECT}/databases/(default)/documents/{path}"


def seed_config() -> None:
    """Write the config as the emulator's rule-bypassing owner."""
    body = {"fields": _fields({"enabled": True, "model": "gemini-flash", "promptVersion": "p1"})}
    response = httpx.patch(
        _doc_url(CONFIG), headers={"Authorization": "Bearer owner"}, json=body, timeout=10
    )
    response.raise_for_status()


def update_config(data: dict[str, Any], tok: str | None, path: str = CONFIG) -> int:
    """A masked update, as the kill switch sends it (only the listed fields change)."""
    params = {"updateMask.fieldPaths": list(data), "currentDocument.exists": "true"}
    headers = {"Authorization": f"Bearer {tok}"} if tok else {}
    return httpx.patch(
        _doc_url(path), params=params, headers=headers, json={"fields": _fields(data)}, timeout=10
    ).status_code


def test_kill_switch_can_turn_the_assistant_off() -> None:
    seed_config()
    assert update_config(OFF, USERS["kill switch"]) == 200


@pytest.mark.parametrize("who", [w for w in USERS if w != "kill switch"])
def test_only_the_kill_switch_account_may_turn_it_off(who: str) -> None:
    seed_config()
    assert update_config(OFF, USERS[who]) == DENIED


@pytest.mark.parametrize(
    "data",
    [
        {"enabled": True, "disabledBy": "budget_alert:92%:2026-10"},
        {"enabled": False, "disabledBy": "owner said so"},
        {"enabled": False},
        {**OFF, "model": "gemini-pro"},
        {**OFF, "promptVersion": "p2"},
    ],
    ids=["turn-on", "free-text-reason", "no-reason", "change-model", "change-prompt"],
)
def test_kill_switch_can_change_nothing_else(data: dict[str, Any]) -> None:
    seed_config()  # the seeded config has no disabledBy, so "no-reason" must be refused
    assert update_config(data, USERS["kill switch"]) == DENIED


def test_kill_switch_needs_a_password_sign_in() -> None:
    seed_config()
    custom = token(role="killswitch", firebase={"sign_in_provider": "custom", "identities": {}})
    assert update_config(OFF, custom) == DENIED


@pytest.mark.parametrize("path", ["assistant_config/next", *ASSISTANT_PATHS[1:]])
def test_kill_switch_cannot_write_other_documents(path: str) -> None:
    assert update_config(OFF, USERS["kill switch"], path) == DENIED


def test_kill_switch_cannot_read_or_delete_the_config() -> None:
    seed_config()
    tok = USERS["kill switch"]
    assert firestore_get(CONFIG, "kill switch") == DENIED
    headers = {"Authorization": f"Bearer {tok}"}
    assert httpx.delete(_doc_url(CONFIG), headers=headers, timeout=10).status_code == DENIED


# Everything else is denied to the kill-switch identity. It is also in USERS, so every rule test
# above runs for it; this names the paths it could plausibly reach for.
KILL_SWITCH_ELSEWHERE = [
    "demo_meta/current",
    "users/ks",
    "users/u1/assistant_threads/t1",
    "users/u1/assistant_threads/t1/messages/m1",
    "assistant_config/next",
    *ASSISTANT_PATHS,
]


@pytest.mark.parametrize("path", KILL_SWITCH_ELSEWHERE)
def test_kill_switch_can_read_and_write_nothing_else_in_firestore(path: str) -> None:
    tok = USERS["kill switch"]
    assert firestore_get(path, "kill switch") == DENIED
    assert firestore_write(path, "kill switch") == DENIED
    headers = {"Authorization": f"Bearer {tok}"}
    assert httpx.delete(_doc_url(path), headers=headers, timeout=10).status_code == DENIED


@pytest.mark.parametrize("collection", ["assistant_config", "demo_meta", "users"])
def test_kill_switch_cannot_list_collections(collection: str) -> None:
    headers = {"Authorization": f"Bearer {USERS['kill switch']}"}
    assert httpx.get(_doc_url(collection), headers=headers, timeout=10).status_code == DENIED


@pytest.mark.parametrize("name", ["datasets/uae/latest.json", "reports/ks/r.pdf", "x.json"])
def test_kill_switch_can_read_and_write_nothing_in_storage(name: str) -> None:
    assert storage_get(name, "kill switch") == DENIED
    assert storage_write(name, "kill switch") == DENIED
