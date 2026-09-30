"""invite_user against an in-memory stand-in for firebase_admin.auth (no network, no Firebase)."""

from dataclasses import dataclass, field
from typing import Any

import invite_user
import pytest


class UserNotFoundError(Exception):
    pass


@dataclass
class User:
    uid: str
    email: str
    custom_claims: dict[str, Any] | None = None


@dataclass
class FakeAuth:
    """The slice of firebase_admin.auth the script uses, recording every call."""

    users: dict[str, User] = field(default_factory=dict)
    revoked: list[str] = field(default_factory=list)
    UserNotFoundError: type[Exception] = UserNotFoundError

    def get_user_by_email(self, email: str) -> User:
        if email not in self.users:
            raise UserNotFoundError(email)
        return self.users[email]

    def create_user(self, *, email: str, email_verified: bool, disabled: bool) -> User:
        assert not email_verified
        assert not disabled
        user = User(uid=f"uid-{len(self.users)}", email=email)
        self.users[email] = user
        return user

    def set_custom_user_claims(self, uid: str, claims: dict[str, Any] | None) -> None:
        next(u for u in self.users.values() if u.uid == uid).custom_claims = claims

    def revoke_refresh_tokens(self, uid: str) -> None:
        self.revoked.append(uid)


EMAIL = "someone@example.test"


def test_mask_hides_all_but_the_first_letter() -> None:
    assert invite_user.mask(EMAIL) == "s***@example.test"


def test_new_user_gets_role_and_reset_email_and_output_is_masked() -> None:
    auth = FakeAuth()
    sent: list[str] = []
    line = invite_user.invite(EMAIL, "viewer", sent.append, allow_existing=False, auth=auth)
    assert auth.users[EMAIL].custom_claims == {"role": "viewer"}
    assert sent == [EMAIL]
    assert auth.revoked == []
    assert "created role=viewer" in line
    assert "reset-email=sent" in line
    assert EMAIL not in line


def test_no_email_skips_the_reset_email() -> None:
    line = invite_user.invite(EMAIL, "viewer", None, allow_existing=False, auth=FakeAuth())
    assert "reset-email=skipped" in line


def test_existing_account_is_refused_without_the_flag() -> None:
    auth = FakeAuth(users={EMAIL: User("u1", EMAIL, {"role": "viewer"})})
    sent: list[str] = []
    with pytest.raises(invite_user.RefusedError):
        invite_user.invite(EMAIL, "admin", sent.append, allow_existing=False, auth=auth)
    assert auth.users[EMAIL].custom_claims == {"role": "viewer"}
    assert sent == []


def test_role_change_on_existing_account_revokes_tokens_and_keeps_other_claims() -> None:
    auth = FakeAuth(users={EMAIL: User("u1", EMAIL, {"role": "viewer", "org": "x"})})
    line = invite_user.invite(EMAIL, "admin", None, allow_existing=True, auth=auth)
    assert auth.users[EMAIL].custom_claims == {"role": "admin", "org": "x"}
    assert auth.revoked == ["u1"]
    assert "was viewer; tokens revoked" in line


def test_same_role_on_existing_account_does_not_revoke() -> None:
    auth = FakeAuth(users={EMAIL: User("u1", EMAIL, {"role": "viewer"})})
    invite_user.invite(EMAIL, "viewer", None, allow_existing=True, auth=auth)
    assert auth.revoked == []


def test_revoke_drops_only_the_role_and_revokes_tokens() -> None:
    auth = FakeAuth(users={EMAIL: User("u1", EMAIL, {"role": "admin", "org": "x"})})
    line = invite_user.revoke(EMAIL, auth=auth)
    assert auth.users[EMAIL].custom_claims == {"org": "x"}
    assert auth.revoked == ["u1"]
    assert EMAIL not in line


def test_revoke_clears_claims_entirely_when_role_was_the_only_one() -> None:
    auth = FakeAuth(users={EMAIL: User("u1", EMAIL, {"role": "viewer"})})
    invite_user.revoke(EMAIL, auth=auth)
    assert auth.users[EMAIL].custom_claims is None


@dataclass
class Response:
    status_code: int
    body: dict[str, Any]

    def json(self) -> dict[str, Any]:
        return self.body


@dataclass
class FakeSession:
    response: Response
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    def post(self, url: str, **kwargs: Any) -> Response:
        self.calls.append((url, kwargs))
        return self.response


def test_send_reset_email_posts_a_password_reset_for_the_project() -> None:
    session = FakeSession(Response(200, {}))
    invite_user.send_reset_email(session, "proj", EMAIL, "https://app.example/")
    url, kwargs = session.calls[0]
    assert url == invite_user.SEND_OOB
    assert kwargs["json"]["requestType"] == "PASSWORD_RESET"
    assert kwargs["json"]["targetProjectId"] == "proj"
    assert kwargs["json"]["continueUrl"] == "https://app.example/"
    assert kwargs["headers"] == {"X-Goog-User-Project": "proj"}


def test_send_reset_email_raises_with_the_api_message() -> None:
    session = FakeSession(Response(400, {"error": {"message": "EMAIL_NOT_FOUND"}}))
    with pytest.raises(RuntimeError, match="EMAIL_NOT_FOUND"):
        invite_user.send_reset_email(session, "proj", EMAIL, "https://app.example/")
