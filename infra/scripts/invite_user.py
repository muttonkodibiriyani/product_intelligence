# /// script
# requires-python = ">=3.12"
# dependencies = ["firebase-admin>=6.5", "google-auth>=2.30", "requests>=2.32"]
# ///
"""Invite demo users: create (no password), set the role claim, send the reset email.

Emails are read from stdin, one per line, so they never land in argv, shell history or the repo.
Nobody sets or sees a password: the invitee chooses one from Firebase's own reset email.
Output shows masked emails only.

    GOOGLE_APPLICATION_CREDENTIALS=<sa-key.json> uv run --script infra/scripts/invite_user.py \
        --project productintelligence-beeb3 --role admin < emails.txt

Existing accounts are refused unless --existing is passed. Changing a role revokes the user's
refresh tokens; --revoke removes the role and revokes tokens (the account is kept).
"""

import argparse
import sys
from collections.abc import Callable
from functools import partial
from types import ModuleType
from typing import Any, Protocol

ROLES = ("admin", "viewer")
SEND_OOB = "https://identitytoolkit.googleapis.com/v1/accounts:sendOobCode"


def mask(email: str) -> str:
    local, _, domain = email.partition("@")
    return f"{local[:1]}***@{domain}"


class Session(Protocol):
    """The slice of google.auth's AuthorizedSession this script uses."""

    def post(self, url: str, **kwargs: Any) -> Any: ...


def send_reset_email(
    session: Session,
    project: str,
    email: str,
    continue_url: str,
) -> None:
    body = {
        "requestType": "PASSWORD_RESET",
        "email": email,
        "targetProjectId": project,
        "continueUrl": continue_url,
    }
    resp = session.post(SEND_OOB, json=body, headers={"X-Goog-User-Project": project}, timeout=30)
    if resp.status_code != 200:
        msg = resp.json().get("error", {}).get("message", resp.status_code)
        raise RuntimeError(f"sendOobCode failed: {msg}")


class RefusedError(Exception):
    """The requested change is not allowed without an explicit flag."""


def invite(
    email: str,
    role: str,
    send_email: Callable[[str], None] | None,
    *,
    allow_existing: bool,
    auth: ModuleType | Any,
) -> str:
    try:
        user = auth.get_user_by_email(email)
    except auth.UserNotFoundError:
        user = auth.create_user(email=email, email_verified=False, disabled=False)
        state = "created"
    else:
        # Never silently grant a role to an account someone else may control.
        if not allow_existing:
            raise RefusedError("account already exists; re-run with --existing if intended")
        state = "existing"
    claims = dict(user.custom_claims or {})
    previous = claims.get("role")
    claims["role"] = role
    auth.set_custom_user_claims(user.uid, claims)
    revoked = ""
    if previous is not None and previous != role:
        # Old ID tokens keep the old claim for up to 1 h; force a fresh sign-in.
        auth.revoke_refresh_tokens(user.uid)
        revoked = f" (was {previous}; tokens revoked)"
    sent = "skipped"
    if send_email is not None:
        send_email(email)
        sent = "sent"
    return f"{mask(email)} uid={user.uid} {state} role={role}{revoked} reset-email={sent}"


def revoke(email: str, *, auth: ModuleType | Any) -> str:
    """Remove the role claim and revoke refresh tokens; the account itself is kept."""
    user = auth.get_user_by_email(email)
    claims = {k: v for k, v in (user.custom_claims or {}).items() if k != "role"}
    auth.set_custom_user_claims(user.uid, claims or None)
    auth.revoke_refresh_tokens(user.uid)
    return f"{mask(email)} uid={user.uid} role removed, tokens revoked"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--project", required=True)
    parser.add_argument("--role", choices=ROLES, default="viewer")
    parser.add_argument(
        "--no-email", action="store_true", help="create user + claim only; send the email later"
    )
    parser.add_argument(
        "--existing", action="store_true", help="allow acting on accounts that already exist"
    )
    parser.add_argument(
        "--revoke", action="store_true", help="remove access: drop the role and revoke tokens"
    )
    parser.add_argument("--continue-url", default="https://productintelligence-beeb3.web.app/")
    args = parser.parse_args()

    emails = [line.strip() for line in sys.stdin if line.strip()]
    if not emails or any("@" not in e for e in emails):
        print("expected one email per line on stdin", file=sys.stderr)
        return 2

    import firebase_admin  # noqa: PLC0415 (lazy: unit tests run without Firebase installed)
    import google.auth  # noqa: PLC0415
    import google.auth.transport.requests  # noqa: PLC0415
    from firebase_admin import auth  # noqa: PLC0415

    firebase_admin.initialize_app(options={"projectId": args.project})
    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    session = google.auth.transport.requests.AuthorizedSession(creds)
    mailer: Callable[[str], None] | None = None
    if not args.no_email:
        mailer = partial(send_reset_email, session, args.project, continue_url=args.continue_url)
    failed = 0
    for email in emails:
        try:
            if args.revoke:
                print(revoke(email, auth=auth))
            else:
                print(invite(email, args.role, mailer, allow_existing=args.existing, auth=auth))
        except Exception as exc:
            failed += 1
            print(f"{mask(email)} FAILED: {exc}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
