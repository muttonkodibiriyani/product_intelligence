"""Qualify ``field_state`` in ``pi_field_state_valid`` so dumps restore.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-30

``pg_restore`` runs with ``search_path = ''``. The function is ``LANGUAGE sql`` and is inlined
into the ``offer_observation`` CHECK, so the bare ``NULL::field_state`` failed to resolve at
``ATTACH PARTITION`` and a plain ``pg_dump``/``pg_restore`` of the database failed (found by
Infra's backup restore test). ``public.field_state`` resolves under any search_path. The function
stays ``LANGUAGE sql`` without ``SET search_path``, which would stop it being inlined.

The other functions need nothing: ``pi_ensure_offer_observation_partition`` sets its own
search_path, and the two trigger functions don't fire during ``COPY``.
"""

from alembic import op

from pi_db.migrations.versions.v0001_schema_v1 import FUNCTIONS_SQL

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

_V0001 = FUNCTIONS_SQL[0].replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1)
_UNQUALIFIED = "enum_range(NULL::field_state)"
_QUALIFIED = "enum_range(NULL::public.field_state)"
assert _V0001.count(_UNQUALIFIED) == 1  # noqa: S101 -- guards the frozen 0001 text at import
FIELD_STATE_VALID_SQL = _V0001.replace(_UNQUALIFIED, _QUALIFIED)


def upgrade() -> None:
    op.execute(FIELD_STATE_VALID_SQL)


def downgrade() -> None:
    op.execute(_V0001)
