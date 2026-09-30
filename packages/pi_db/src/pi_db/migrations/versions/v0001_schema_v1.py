"""Schema v1: blueprint §5.1 fact store.

Revision ID: 0001
Revises:
Create Date: 2026-09-30

Everything below is frozen once merged. Enum values, vector sizes and the ladder range are
literals on purpose: later changes to ``pi_core`` or ``pi_db`` must come with a new migration,
and the test-suite checks the live database against both.

Runs as the database owner on local PostgreSQL 16 and on Cloud SQL (no superuser needed:
``vector`` is an allow-listed extension and the owner has CREATEROLE there).
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

IMAGE_EMBEDDING_DIM = 768  # SigLIP ViT-B/16
TEXT_EMBEDDING_DIM = 1024  # BGE-M3 dense
LADDER_RUNG_MAX = 5  # pi_core.LadderRung.PAID_PROXY
APP_ROLE = "pi_app"

# Postgres enum type -> values, in pi_core declaration order.
PI_CORE_ENUMS: dict[str, tuple[str, ...]] = {
    "availability_state": (
        "in_stock",
        "low_stock",
        "out_of_stock",
        "not_deliverable",
        "removed",
        "not_observed",
        "blocked",
        "unknown",
    ),
    "field_state": (
        "not_published",
        "not_applicable",
        "restricted",
        "parse_failure",
        "blocked",
        "unknown",
    ),
    "price_type": (
        "full",
        "promotional",
        "member",
        "subscription",
        "installment",
        "range",
        "quote_only",
    ),
    "tax_status": ("included", "excluded", "exempt", "unknown"),
    "channel": (
        "online",
        "marketplace",
        "delivery",
        "pickup",
        "dine_in_evidenced",
        "offline_audit",
    ),
    "match_class": ("exact", "family", "size_normalized", "substitute"),
    "review_state": ("proposed", "approved", "rejected", "locked"),
    "quality_status": ("accepted", "warning", "quarantined", "corrected"),
    "coverage_status": ("supported", "partial", "pending", "paused", "unsupported", "retired"),
}

# Schema-only vocabularies (blueprint §5.1), not modelled in pi_core yet.
SCHEMA_ENUMS: dict[str, tuple[str, ...]] = {
    "source_kind": ("web", "app", "feed", "aggregator", "offline"),
    "image_role": ("main", "alt", "swatch", "model", "texture"),
}

# Pre-created monthly partitions of offer_observation (UTC months, inclusive).
PARTITIONS_FROM = "2026-01-01"
PARTITIONS_TO = "2027-12-01"

# Tables the app may only INSERT into and SELECT from (history is never rewritten).
APPEND_ONLY_TABLES = (
    "evidence",
    "listing_content",
    "review_summary",
    "offer_observation",
    "offer_promotion",
    "audit_log",
    "decision_log",
)
# Tables the app may INSERT, SELECT and UPDATE (registers and slowly changing entities).
MUTABLE_TABLES = (
    "cohort",
    "source",
    "source_context",
    "crawl_run",
    "brand",
    "taxonomy",
    "taxonomy_map",
    "product_family",
    "variant",
    "source_listing",
    "image",
    "listing_image",
    "review",
    "promotion",
    "match_edge",
    "fx_rate",
    "metric_def",
)
TABLES = MUTABLE_TABLES + APPEND_ONLY_TABLES

FUNCTIONS = (
    "pi_field_state_valid(jsonb)",
    "pi_reject_mutation()",
    "pi_ensure_offer_observation_partition(date)",
)

MONEY = "numeric(18,4)"
CURRENCY = "char(3) CHECK ({col} ~ '^[A-Z]{{3}}$')"
RUNG = f"smallint CHECK ({{col}} BETWEEN 0 AND {LADDER_RUNG_MAX})"


def _currency(col: str) -> str:
    return f"{col} {CURRENCY.format(col=col)}"


def _rung(col: str) -> str:
    return f"{col} {RUNG.format(col=col)}"


def _enum_sql(name: str, values: tuple[str, ...]) -> str:
    labels = ", ".join(f"'{v}'" for v in values)
    return f"CREATE TYPE {name} AS ENUM ({labels})"


FUNCTIONS_SQL = [
    # Every value of a field_state map must be a FieldState (DQ-02: missing is data).
    """
    CREATE FUNCTION pi_field_state_valid(fs jsonb) RETURNS boolean
    LANGUAGE sql STABLE AS $$
      SELECT jsonb_typeof(fs) = 'object'
         AND NOT EXISTS (
           SELECT 1 FROM jsonb_each(fs) AS e(key, value)
           WHERE jsonb_typeof(e.value) <> 'string'
              OR NOT (e.value #>> '{}') = ANY (enum_range(NULL::field_state)::text[])
         )
    $$
    """,
    # Defence in depth next to the grants: even the owner cannot rewrite history.
    """
    CREATE FUNCTION pi_reject_mutation() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
      RAISE EXCEPTION '% is append-only; insert a correction instead', TG_TABLE_NAME
        USING ERRCODE = 'insufficient_privilege';
    END
    $$
    """,
    # Creates the UTC monthly partition containing `month` if missing; returns its name.
    """
    CREATE FUNCTION pi_ensure_offer_observation_partition(month date) RETURNS text
    LANGUAGE plpgsql AS $$
    DECLARE
      lower_bound timestamptz := date_trunc('month', month)::timestamp AT TIME ZONE 'UTC';
      upper_bound timestamptz :=
        (date_trunc('month', month) + interval '1 month')::timestamp AT TIME ZONE 'UTC';
      part text := format('offer_observation_p%s', to_char(month, 'YYYYMM'));
    BEGIN
      IF to_regclass(part) IS NULL THEN
        EXECUTE format(
          'CREATE TABLE %I PARTITION OF offer_observation FOR VALUES FROM (%L) TO (%L)',
          part, lower_bound, upper_bound
        );
      END IF;
      RETURN part;
    END
    $$
    """,
]

TABLES_SQL = [
    # ------------------------------------------------------------ registers
    """
    CREATE TABLE cohort (
      id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
      name text NOT NULL UNIQUE,
      description text,
      definition jsonb NOT NULL DEFAULT '{}'
    )
    """,
    """
    CREATE TABLE source (
      id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
      name text NOT NULL UNIQUE,
      kind source_kind NOT NULL,
      base_url text,
      notes text,
      created_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    f"""
    CREATE TABLE source_context (
      id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
      source_id bigint NOT NULL REFERENCES source,
      country char(2) NOT NULL CHECK (country ~ '^[A-Z]{{2}}$'),
      channel channel NOT NULL,
      location_context jsonb NOT NULL DEFAULT '{{}}',
      locale text NOT NULL,
      time_zone text NOT NULL,
      device text NOT NULL DEFAULT 'desktop',
      cohort_id bigint REFERENCES cohort,
      refresh_policy jsonb NOT NULL DEFAULT '{{}}',
      {_rung("ladder_rung_current")} NOT NULL DEFAULT 0,
      {_rung("ladder_rung_max_allowed")} NOT NULL DEFAULT {LADDER_RUNG_MAX - 1},
      coverage_status coverage_status NOT NULL DEFAULT 'pending',
      fallback_of bigint REFERENCES source_context,
      history_start_at timestamptz,
      valid_from timestamptz NOT NULL DEFAULT now(),
      valid_to timestamptz,
      CHECK (ladder_rung_current <= ladder_rung_max_allowed),
      CHECK (valid_to IS NULL OR valid_to > valid_from)
    )
    """,
    f"""
    CREATE TABLE crawl_run (
      id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
      source_context_id bigint NOT NULL REFERENCES source_context,
      connector_version text NOT NULL,
      {_rung("ladder_rung_used")} NOT NULL,
      started_at timestamptz NOT NULL,
      finished_at timestamptz,
      status text NOT NULL DEFAULT 'running'
        CHECK (status IN ('running', 'succeeded', 'partial', 'failed', 'aborted')),
      discovered integer NOT NULL DEFAULT 0 CHECK (discovered >= 0),
      fetched integer NOT NULL DEFAULT 0 CHECK (fetched >= 0),
      parsed integer NOT NULL DEFAULT 0 CHECK (parsed >= 0),
      accepted integer NOT NULL DEFAULT 0 CHECK (accepted >= 0),
      quarantined integer NOT NULL DEFAULT 0 CHECK (quarantined >= 0),
      blocked_count integer NOT NULL DEFAULT 0 CHECK (blocked_count >= 0),
      bytes_via_proxy bigint NOT NULL DEFAULT 0 CHECK (bytes_via_proxy >= 0),
      manifest_uri text,
      CHECK (finished_at IS NULL OR finished_at >= started_at)
    )
    """,
    """
    CREATE TABLE evidence (
      id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
      crawl_run_id bigint NOT NULL REFERENCES crawl_run,
      url text NOT NULL,
      content_hash text NOT NULL,
      storage_uri text NOT NULL,
      retrieved_at timestamptz NOT NULL,
      http_status smallint,
      retention_until timestamptz NOT NULL
    )
    """,
    "CREATE INDEX evidence_content_hash_idx ON evidence (content_hash)",
    # ------------------------------------------------------------ catalogue
    """
    CREATE TABLE brand (
      id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
      name text NOT NULL UNIQUE,
      name_ar text,
      aliases text[] NOT NULL DEFAULT '{}'
    )
    """,
    """
    CREATE TABLE taxonomy (
      id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
      parent_id bigint REFERENCES taxonomy,
      code text NOT NULL UNIQUE,
      name text NOT NULL,
      name_ar text,
      level smallint NOT NULL CHECK (level >= 0)
    )
    """,
    """
    CREATE TABLE taxonomy_map (
      id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
      source_id bigint NOT NULL REFERENCES source,
      category_path_source text NOT NULL,
      taxonomy_id bigint NOT NULL REFERENCES taxonomy,
      confidence numeric(5,4) CHECK (confidence BETWEEN 0 AND 1),
      mapped_by text NOT NULL,
      mapped_at timestamptz NOT NULL DEFAULT now(),
      UNIQUE (source_id, category_path_source)
    )
    """,
    """
    CREATE TABLE product_family (
      id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
      brand_id bigint NOT NULL REFERENCES brand,
      name_normalized text NOT NULL,
      category_universal_id bigint REFERENCES taxonomy,
      created_at timestamptz NOT NULL DEFAULT now(),
      UNIQUE (brand_id, name_normalized)
    )
    """,
    f"""
    CREATE TABLE variant (
      id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
      family_id bigint NOT NULL REFERENCES product_family,
      gtin text CHECK (gtin ~ '^[0-9]{{8,14}}$'),
      mpn text,
      shade text,
      shade_code text,
      shade_family text,
      shade_hex char(7) CHECK (shade_hex ~ '^#[0-9A-Fa-f]{{6}}$'),
      finish text,
      size_value numeric(18,4) CHECK (size_value > 0),
      size_unit text,
      pack_count integer NOT NULL DEFAULT 1 CHECK (pack_count > 0),
      concentration text,
      formulation text,
      is_refill boolean NOT NULL DEFAULT false,
      is_mini boolean NOT NULL DEFAULT false,
      is_set boolean NOT NULL DEFAULT false,
      set_contents jsonb,
      attributes jsonb NOT NULL DEFAULT '{{}}',
      attr_provenance jsonb NOT NULL DEFAULT '{{}}',
      successor_variant_id bigint REFERENCES variant,
      text_embedding vector({TEXT_EMBEDDING_DIM}),
      created_at timestamptz NOT NULL DEFAULT now(),
      CHECK ((size_value IS NULL) = (size_unit IS NULL))
    )
    """,
    "CREATE INDEX variant_gtin_idx ON variant (gtin) WHERE gtin IS NOT NULL",
    """
    CREATE INDEX variant_text_embedding_idx ON variant
      USING hnsw (text_embedding vector_cosine_ops)
    """,
    """
    CREATE TABLE source_listing (
      id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
      source_id bigint NOT NULL REFERENCES source,
      source_listing_key text NOT NULL,
      source_sku text,
      variant_id bigint REFERENCES variant,
      url text NOT NULL,
      name_original text NOT NULL,
      name_ar text,
      lang text,
      category_path_source text,
      first_seen_at timestamptz NOT NULL,
      last_seen_at timestamptz NOT NULL,
      UNIQUE (source_id, source_listing_key),
      CHECK (last_seen_at >= first_seen_at)
    )
    """,
    "CREATE INDEX source_listing_variant_idx ON source_listing (variant_id)",
    # ------------------------------------------------------------ content, images, reviews
    """
    CREATE TABLE listing_content (
      listing_id bigint NOT NULL REFERENCES source_listing,
      observed_at timestamptz NOT NULL,
      description text,
      description_ar text,
      ingredients text,
      how_to_use text,
      benefits text,
      claims text[] NOT NULL DEFAULT '{}',
      badges text[] NOT NULL DEFAULT '{}',
      labels jsonb NOT NULL DEFAULT '{}',
      content_hash text NOT NULL,
      PRIMARY KEY (listing_id, observed_at)
    )
    """,
    "CREATE INDEX listing_content_hash_idx ON listing_content (listing_id, content_hash)",
    f"""
    CREATE TABLE image (
      id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
      content_hash text NOT NULL UNIQUE,
      storage_uri text NOT NULL,
      thumb_uri text,
      width integer CHECK (width > 0),
      height integer CHECK (height > 0),
      phash text,
      embedding vector({IMAGE_EMBEDDING_DIM})
    )
    """,
    "CREATE INDEX image_phash_idx ON image (phash)",
    "CREATE INDEX image_embedding_idx ON image USING hnsw (embedding vector_cosine_ops)",
    """
    CREATE TABLE listing_image (
      id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
      listing_id bigint NOT NULL REFERENCES source_listing,
      variant_id bigint REFERENCES variant,
      image_id bigint NOT NULL REFERENCES image,
      role image_role NOT NULL,
      position smallint NOT NULL DEFAULT 0 CHECK (position >= 0),
      source_url text NOT NULL,
      first_seen_at timestamptz NOT NULL,
      last_seen_at timestamptz NOT NULL,
      UNIQUE (listing_id, image_id, role),
      CHECK (last_seen_at >= first_seen_at)
    )
    """,
    # No reviewer names or other PII, by design (SEC).
    """
    CREATE TABLE review (
      id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
      listing_id bigint NOT NULL REFERENCES source_listing,
      source_review_id text NOT NULL,
      rating numeric(4,2) CHECK (rating >= 0),
      title text,
      body text,
      lang text,
      posted_at timestamptz,
      verified_flag boolean,
      helpful_count integer CHECK (helpful_count >= 0),
      attributes jsonb NOT NULL DEFAULT '{}',
      UNIQUE (listing_id, source_review_id)
    )
    """,
    """
    CREATE TABLE review_summary (
      listing_id bigint NOT NULL REFERENCES source_listing,
      observed_at timestamptz NOT NULL,
      rating_histogram jsonb NOT NULL DEFAULT '{}',
      themes jsonb NOT NULL DEFAULT '{}',
      PRIMARY KEY (listing_id, observed_at)
    )
    """,
    # ------------------------------------------------------------ promotions
    f"""
    CREATE TABLE promotion (
      id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
      source_context_id bigint NOT NULL REFERENCES source_context,
      mechanic text NOT NULL,
      rule jsonb NOT NULL DEFAULT '{{}}',
      qualifying jsonb NOT NULL DEFAULT '{{}}',
      min_spend {MONEY} CHECK (min_spend >= 0),
      {_currency("min_spend_currency")},
      min_qty integer CHECK (min_qty > 0),
      eligibility jsonb NOT NULL DEFAULT '{{}}',
      stacking text,
      code text,
      gift_with_purchase jsonb,
      advertised_from timestamptz,
      advertised_to timestamptz,
      first_seen_at timestamptz NOT NULL,
      last_seen_at timestamptz NOT NULL,
      terms_original text,
      banner_image_id bigint REFERENCES image,
      evidence_id bigint REFERENCES evidence,
      CHECK ((min_spend IS NULL) = (min_spend_currency IS NULL)),
      CHECK (last_seen_at >= first_seen_at)
    )
    """,
    # ------------------------------------------------------------ observations
    # Append-only, UTC-monthly range partitions. Partition key is part of every unique key.
    # idempotency_key is the pipeline's hash of the logical key, so replays are no-ops.
    # correction_of has no FK: FKs into a partitioned table need the partition key too.
    f"""
    CREATE TABLE offer_observation (
      observation_id bigint GENERATED ALWAYS AS IDENTITY,
      idempotency_key text NOT NULL,
      crawl_run_id bigint NOT NULL REFERENCES crawl_run,
      source_context_id bigint NOT NULL REFERENCES source_context,
      source_listing_id bigint NOT NULL REFERENCES source_listing,
      variant_id bigint REFERENCES variant,
      seller_id text,
      observed_at timestamptz NOT NULL,
      ingested_at timestamptz NOT NULL,
      recorded_at timestamptz NOT NULL DEFAULT now(),
      source_effective_from timestamptz,
      source_effective_to timestamptz,
      price_current {MONEY} CHECK (price_current >= 0),
      price_regular_stated {MONEY} CHECK (price_regular_stated >= 0),
      price_promo {MONEY} CHECK (price_promo >= 0),
      price_member {MONEY} CHECK (price_member >= 0),
      price_type price_type,
      {_currency("currency")},
      installment jsonb,
      tax_status tax_status NOT NULL DEFAULT 'unknown',
      unit_price_derived {MONEY} CHECK (unit_price_derived >= 0),
      unit_basis text,
      availability_state availability_state NOT NULL,
      available_variants integer CHECK (available_variants >= 0),
      low_stock_flag boolean,
      delivery_promise text,
      rating_value numeric(4,2) CHECK (rating_value >= 0),
      rating_count integer CHECK (rating_count >= 0),
      rank_in_category integer CHECK (rank_in_category > 0),
      rank_in_search jsonb,
      badges_at_time text[] NOT NULL DEFAULT '{{}}',
      field_state jsonb NOT NULL DEFAULT '{{}}' CHECK (pi_field_state_valid(field_state)),
      evidence_id bigint REFERENCES evidence,
      quality_status quality_status NOT NULL DEFAULT 'accepted',
      correction_of bigint,
      PRIMARY KEY (observation_id, observed_at),
      UNIQUE (idempotency_key, observed_at),
      CHECK (
        currency IS NOT NULL OR num_nonnulls(
          price_current, price_regular_stated, price_promo, price_member, unit_price_derived
        ) = 0
      ),
      CHECK (source_effective_to IS NULL OR source_effective_to >= source_effective_from)
    ) PARTITION BY RANGE (observed_at)
    """,
    """
    CREATE INDEX offer_observation_listing_idx
      ON offer_observation (source_listing_id, observed_at)
    """,
    """
    CREATE INDEX offer_observation_variant_idx
      ON offer_observation (variant_id, observed_at)
    """,
    """
    CREATE INDEX offer_observation_run_idx ON offer_observation (crawl_run_id)
    """,
    # Rows outside pre-created months land here instead of failing the load; create the month
    # with pi_ensure_offer_observation_partition() before rows for it arrive.
    "CREATE TABLE offer_observation_default PARTITION OF offer_observation DEFAULT",
    f"""
    SELECT pi_ensure_offer_observation_partition(m::date)
    FROM generate_series(
      date '{PARTITIONS_FROM}', date '{PARTITIONS_TO}', interval '1 month'
    ) AS m
    """,
    """
    CREATE TRIGGER offer_observation_append_only
      BEFORE UPDATE OR DELETE ON offer_observation
      FOR EACH ROW EXECUTE FUNCTION pi_reject_mutation()
    """,
    """
    CREATE TABLE offer_promotion (
      observation_id bigint NOT NULL,
      observed_at timestamptz NOT NULL,
      promotion_id bigint NOT NULL REFERENCES promotion,
      PRIMARY KEY (observation_id, observed_at, promotion_id),
      FOREIGN KEY (observation_id, observed_at)
        REFERENCES offer_observation (observation_id, observed_at)
    )
    """,
    # ------------------------------------------------------------ matching
    """
    CREATE TABLE match_edge (
      id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
      variant_a bigint NOT NULL REFERENCES variant,
      variant_b bigint NOT NULL REFERENCES variant,
      match_class match_class NOT NULL,
      score numeric(6,5) CHECK (score BETWEEN 0 AND 1),
      rationale jsonb NOT NULL DEFAULT '{}',
      algo_version text NOT NULL,
      review_state review_state NOT NULL DEFAULT 'proposed',
      reviewer text,
      reviewed_at timestamptz,
      valid_from timestamptz NOT NULL DEFAULT now(),
      valid_to timestamptz,
      CHECK (variant_a < variant_b),
      CHECK (valid_to IS NULL OR valid_to > valid_from)
    )
    """,
    """
    CREATE UNIQUE INDEX match_edge_current_idx ON match_edge (variant_a, variant_b, match_class)
      WHERE valid_to IS NULL
    """,
    # ------------------------------------------------------------ reference and governance
    f"""
    CREATE TABLE fx_rate (
      id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
      {_currency("base_currency")} NOT NULL,
      {_currency("quote_currency")} NOT NULL,
      rate numeric(20,10) NOT NULL CHECK (rate > 0),
      as_of date NOT NULL,
      source text NOT NULL,
      UNIQUE (base_currency, quote_currency, as_of, source)
    )
    """,
    """
    CREATE TABLE metric_def (
      id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
      key text NOT NULL,
      version integer NOT NULL CHECK (version > 0),
      name text NOT NULL,
      definition jsonb NOT NULL,
      owner text NOT NULL,
      created_at timestamptz NOT NULL DEFAULT now(),
      deprecated_at timestamptz,
      UNIQUE (key, version)
    )
    """,
    """
    CREATE TABLE audit_log (
      id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
      occurred_at timestamptz NOT NULL DEFAULT now(),
      actor text NOT NULL,
      action text NOT NULL,
      entity_type text,
      entity_id text,
      before jsonb,
      after jsonb,
      context jsonb NOT NULL DEFAULT '{}'
    )
    """,
    f"""
    CREATE TABLE decision_log (
      id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
      decided_at timestamptz NOT NULL DEFAULT now(),
      decided_by text NOT NULL,
      subject text NOT NULL,
      decision text NOT NULL,
      rationale text,
      reference text,
      cost_impact {MONEY},
      {_currency("cost_impact_currency")},
      CHECK ((cost_impact IS NULL) = (cost_impact_currency IS NULL))
    )
    """,
    """
    CREATE TRIGGER audit_log_append_only BEFORE UPDATE OR DELETE ON audit_log
      FOR EACH ROW EXECUTE FUNCTION pi_reject_mutation()
    """,
    """
    CREATE TRIGGER decision_log_append_only BEFORE UPDATE OR DELETE ON decision_log
      FOR EACH ROW EXECUTE FUNCTION pi_reject_mutation()
    """,
]


def _grants_sql() -> list[str]:
    return [
        f"""
        DO $$
        BEGIN
          IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
            CREATE ROLE {APP_ROLE} NOLOGIN;
          END IF;
        END
        $$
        """,
        f"GRANT USAGE ON SCHEMA public TO {APP_ROLE}",
        f"GRANT SELECT, INSERT, UPDATE ON {', '.join(MUTABLE_TABLES)} TO {APP_ROLE}",
        f"GRANT SELECT, INSERT ON {', '.join(APPEND_ONLY_TABLES)} TO {APP_ROLE}",
    ]


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    for name, values in (PI_CORE_ENUMS | SCHEMA_ENUMS).items():
        op.execute(_enum_sql(name, values))
    for sql in FUNCTIONS_SQL + TABLES_SQL + _grants_sql():
        op.execute(sql)


def downgrade() -> None:
    # The pi_app role and the vector extension are cluster/database-wide and may be shared,
    # so they are left in place; everything else this revision created is removed.
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {APP_ROLE}")
    op.execute(f"DROP TABLE {', '.join(reversed(TABLES))}")
    for signature in FUNCTIONS:
        op.execute(f"DROP FUNCTION {signature}")
    for name in reversed(PI_CORE_ENUMS | SCHEMA_ENUMS):
        op.execute(f"DROP TYPE {name}")
