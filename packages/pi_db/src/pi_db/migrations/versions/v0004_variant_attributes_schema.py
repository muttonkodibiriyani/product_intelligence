"""``variant.attributes_schema``: which vertical profile version wrote ``variant.attributes``.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-01

ADR-0008 step 2 (PR-E). ``variant.attributes`` is written only through a ``pi_profiles``
``VerticalProfile.validate_attributes`` call, and the row records that profile's ref
(``beauty@1``) next to it, so a reader always knows which attribute model the jsonb follows.
Append-only: one nullable column and two CHECKs, no data rewrite. Nothing writes
``variant.attributes`` before this revision, so every existing row is ``'{}'`` and the pairing
CHECK validates without touching data; a row that isn't fails the upgrade loudly.
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

#: ``<name>@<version>``; the same literal as ``pi_profiles.REF_PATTERN`` (a test pins the two).
REF_PATTERN = r"^[a-z][a-z0-9_]{1,62}@[1-9][0-9]{0,8}$"

REF_CONSTRAINT = "variant_attributes_schema_ref_check"
PAIRING_CONSTRAINT = "variant_attributes_schema_check"


def upgrade() -> None:
    op.execute("ALTER TABLE variant ADD COLUMN attributes_schema text")
    op.execute(
        f"ALTER TABLE variant ADD CONSTRAINT {REF_CONSTRAINT}"
        f" CHECK (attributes_schema ~ '{REF_PATTERN}')"
    )
    # Non-empty attributes need a schema; a schema with empty attributes is fine (the profile
    # was applied and nothing was published).
    op.execute(
        f"ALTER TABLE variant ADD CONSTRAINT {PAIRING_CONSTRAINT}"
        " CHECK (attributes = '{}'::jsonb OR attributes_schema IS NOT NULL)"
    )


def downgrade() -> None:
    # Dropping the column drops both CHECKs with it.
    op.execute("ALTER TABLE variant DROP COLUMN attributes_schema")
