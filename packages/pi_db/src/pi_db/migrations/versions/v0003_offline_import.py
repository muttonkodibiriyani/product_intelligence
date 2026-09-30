"""Fetch method ``offline_import``: catalogue feeds imported from a file (tools/offline_import).

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-30

A customer or partner hands us a CSV/XLSX/JSON feed; nothing is fetched from the source's site,
so the method sits on rung 0 (SITE_DATA) with the other first-party data methods. 0001 is
applied in production and stays frozen; the new value and the widened method<->rung CHECK live
here. Values are literals on purpose, as in 0001.
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

# fetch_method values added by this revision, in pi_core declaration order (appended).
NEW_FETCH_METHODS: tuple[str, ...] = ("offline_import",)

# The full method -> rung map after this revision (0001's map plus the additions).
FETCH_METHOD_RUNG_BEFORE: dict[str, int] = {
    "site_api": 0,
    "embedded_json": 0,
    "sitemap": 0,
    "plain_http": 1,
    "playwright": 2,
    "egress_variation": 4,
    "residential_proxy": 5,
}
FETCH_METHOD_RUNG: dict[str, int] = FETCH_METHOD_RUNG_BEFORE | {"offline_import": 0}

# 0001 declared the CHECK inline without a name; PostgreSQL named it evidence_check (a
# table-level CHECK over two columns). This revision gives it an explicit name.
OLD_CONSTRAINT = "evidence_check"
CONSTRAINT = "evidence_method_rung_check"


def _method_rung_check(mapping: dict[str, int]) -> str:
    cases = " ".join(f"WHEN '{m}' THEN {r}" for m, r in mapping.items())
    return f"CHECK (ladder_rung_used = CASE fetch_method::text {cases} END)"


def _replace_check(drop: str, add: str, mapping: dict[str, int]) -> None:
    # One transaction: DROP takes ACCESS EXCLUSIVE on evidence until commit, so the ADD's scan of
    # existing rows runs under that lock too (evidence is small; the pause is brief).
    op.execute(f"ALTER TABLE evidence DROP CONSTRAINT {drop}")
    op.execute(f"ALTER TABLE evidence ADD CONSTRAINT {add} {_method_rung_check(mapping)}")


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE: a new label cannot be used in the transaction that added it,
    # so it is committed on its own before anything else runs.
    with op.get_context().autocommit_block():
        for value in NEW_FETCH_METHODS:
            op.execute(f"ALTER TYPE fetch_method ADD VALUE IF NOT EXISTS '{value}'")
    _replace_check(OLD_CONSTRAINT, CONSTRAINT, FETCH_METHOD_RUNG)


def downgrade() -> None:
    # Restores 0001's CHECK, byte for byte and under its original name. Evidence rows are
    # append-only history and are left alone: 0001's CASE yields NULL for a label it does not
    # know, so existing offline_import rows still pass it.
    # PostgreSQL cannot drop an enum label, so 'offline_import' stays in fetch_method after the
    # downgrade (a re-upgrade is a no-op thanks to IF NOT EXISTS); 0001's own downgrade drops
    # the whole type.
    _replace_check(CONSTRAINT, OLD_CONSTRAINT, FETCH_METHOD_RUNG_BEFORE)
