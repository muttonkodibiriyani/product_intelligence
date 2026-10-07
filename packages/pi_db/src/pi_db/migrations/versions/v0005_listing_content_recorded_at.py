"""``listing_content.recorded_at``: when a content row was recorded, next to when it was observed.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-07

A content row has two times. ``observed_at`` is when the page was seen; ``recorded_at`` is when
the row was written. Re-deriving content from pages already loaded (``offline_import
--content-only``) writes a new row with the page's own ``observed_at``, so a listing can now hold
two rows at one ``observed_at``. The primary key becomes ``(listing_id, observed_at,
recorded_at)``, and readers take the latest row by ``observed_at DESC, recorded_at DESC``.

A replay must still add nothing: a UNIQUE index on ``(listing_id, observed_at, content_hash)``
makes the same content at the same page time one row, whoever writes it and however often.
Writers insert with a target-less ``ON CONFLICT DO NOTHING``, which skips a row that would break
either that index or the key. ``recorded_at`` defaults to ``now()``, fixed for a transaction, so
within one load the first content for a (listing, observed_at) still wins, as under 0004; an
explicit index target would turn that second row into a key violation instead.

The checks are SQL, so ``alembic upgrade --sql`` previews them too. Upgrade STOPs if
``content_hash`` could be NULL, or if any (listing_id, observed_at, content_hash) already holds two
rows: the table is append-only and is never deduplicated by deleting. Downgrade STOPs if any
(listing_id, observed_at) holds two rows, which the 0004 key cannot hold, rather than drop one.

Existing rows: no table records when they were loaded (``listing_content`` has no link to a
crawl run), so they get the migration's time. That is conservative: nothing is dated earlier
than it was known, and an as-known-at read before this migration sees none of them.

Locks: ``ADD COLUMN … DEFAULT now()`` takes the no-rewrite path (``now()`` is stable, stored once
as the column's missing value). Swapping the primary key and building the UNIQUE index scan the
table and build two btrees under ACCESS EXCLUSIVE; writers and readers of ``listing_content``
block for that time.

Append-only is unchanged: the UPDATE/DELETE/TRUNCATE triggers and the INSERT/SELECT grants stay.
"""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

UNIQUE_INDEX = "listing_content_observed_hash_key"


def _stop_if(count_sql: str, message: str) -> None:
    """RAISE (online and in --sql output) when ``count_sql`` counts anything; ``{n}`` is the count.

    No ``%`` placeholder: the --sql renderer doubles it, and plpgsql then rejects the RAISE."""
    head, tail = message.split("{n}")
    op.execute(
        f"""DO $$
DECLARE n bigint;
BEGIN
  SELECT count(*) INTO n FROM ({count_sql}) d;
  IF n > 0 THEN RAISE EXCEPTION USING MESSAGE = 'STOP: {head}' || n || '{tail}'; END IF;
END $$"""
    )


def upgrade() -> None:
    _stop_if(
        "SELECT 1 FROM information_schema.columns WHERE table_schema = 'public'"
        " AND table_name = 'listing_content' AND column_name = 'content_hash'"
        " AND is_nullable <> 'NO'",
        "listing_content.content_hash must be NOT NULL ({n} nullable column)",
    )
    _stop_if(
        "SELECT 1 FROM listing_content GROUP BY listing_id, observed_at, content_hash"
        " HAVING count(*) > 1",
        "{n} (listing_id, observed_at, content_hash) groups hold more than one row;"
        " resolve them by hand before this migration",
    )
    op.execute(
        "ALTER TABLE listing_content ADD COLUMN recorded_at timestamptz NOT NULL DEFAULT now()"
    )
    op.execute(
        "ALTER TABLE listing_content DROP CONSTRAINT listing_content_pkey,"
        " ADD CONSTRAINT listing_content_pkey PRIMARY KEY (listing_id, observed_at, recorded_at)"
    )
    op.execute(
        f"CREATE UNIQUE INDEX {UNIQUE_INDEX} ON listing_content"
        " (listing_id, observed_at, content_hash)"
    )


def downgrade() -> None:
    _stop_if(
        "SELECT 1 FROM listing_content GROUP BY listing_id, observed_at HAVING count(*) > 1",
        "{n} (listing_id, observed_at) pairs hold more than one content row;"
        " the 0004 primary key cannot hold them and no row is deleted to fit it",
    )
    op.execute(f"DROP INDEX {UNIQUE_INDEX}")
    op.execute(
        "ALTER TABLE listing_content DROP CONSTRAINT listing_content_pkey,"
        " ADD CONSTRAINT listing_content_pkey PRIMARY KEY (listing_id, observed_at)"
    )
    op.execute("ALTER TABLE listing_content DROP COLUMN recorded_at")
