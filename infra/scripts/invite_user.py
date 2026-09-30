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
"""

import argparse
import sys

import firebase_admin
import google.auth
import google.auth.transport.requests
from firebase_admin import auth

ROLES = ("admin", "viewer")
SEND_OOB = "https://identitytoolkit.googleapis.com/v1/accounts:sendOobCode"


def mask(email: str) -> str:
    local, _, domain = email.partition("@")
    return f"{local[:1]}***@{domain}"


def send_reset_email(
    session: google.auth.transport.requests.AuthorizedSession,
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


def invite(
    email: str,
    role: str,
    project: str,
    continue_url: str,
    session: google.auth.transport.requests.AuthorizedSession | None,
) -> str:
    try:
        user = auth.get_user_by_email(email)
        state = "existing"
    except auth.UserNotFoundError:
        user = auth.create_user(email=email, email_verified=False, disabled=False)
        state = "created"
    claims = dict(user.custom_claims or {})
    claims["role"] = role
    auth.set_custom_user_claims(user.uid, claims)
    sent = "skipped"
    if session is not None:
        send_reset_email(session, project, email, continue_url)
        sent = "sent"
    return f"{mask(email)} uid={user.uid} {state} role={role} reset-email={sent}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--project", required=True)
    parser.add_argument("--role", choices=ROLES, default="viewer")
    parser.add_argument(
        "--no-email", action="store_true", help="create user + claim only; send the email later"
    )
    parser.add_argument("--continue-url", default="https://productintelligence-beeb3.web.app/")
    args = parser.parse_args()

    emails = [line.strip() for line in sys.stdin if line.strip()]
    if not emails or any("@" not in e for e in emails):
        print("expected one email per line on stdin", file=sys.stderr)
        return 2

    firebase_admin.initialize_app(options={"projectId": args.project})
    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    session = google.auth.transport.requests.AuthorizedSession(creds)
    mailer = None if args.no_email else session
    failed = 0
    for email in emails:
        try:
            print(invite(email, args.role, args.project, args.continue_url, mailer))
        except Exception as exc:
            failed += 1
            print(f"{mask(email)} FAILED: {exc}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
