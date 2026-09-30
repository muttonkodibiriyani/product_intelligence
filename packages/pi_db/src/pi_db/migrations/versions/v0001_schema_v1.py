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
# Rungs kept in the numbering for audit and history but never usable (owner guardrail:
# rung 3 = stealth browsers, fingerprint rotation, cookie reuse is disabled program-wide).
# Applies to rungs used or current, not to ladder_rung_max_allowed: the cap may sit above a
# forbidden rung, and escalation skips it.
FORBIDDEN_RUNGS: tuple[int, ...] = (3,)
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
        "observed",
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

# Vocabularies pi_core models in PR3 (#6); the parity tests check them as soon as pi_core
# exports the matching class (SourceKind, ImageRole, FetchMethod).
SCHEMA_ENUMS: dict[str, tuple[str, ...]] = {
    "source_kind": ("web", "app", "feed", "aggregator", "offline"),
    "image_role": ("main", "alt", "swatch", "model", "texture"),
    "fetch_method": (
        "site_api",
        "embedded_json",
        "sitemap",
        "plain_http",
        "playwright",
        "egress_variation",
        "residential_proxy",
    ),
}

# Each fetch method belongs to exactly one ladder rung (pi_core FetchMethod.rung, ADR-0003).
# No method maps to a forbidden rung; values are locked with pi_core (#6). Adding an enum
# value later is cheap (ALTER TYPE ... ADD VALUE), removing one is not.
FETCH_METHOD_RUNG: dict[str, int] = {
    "site_api": 0,
    "embedded_json": 0,
    "sitemap": 0,
    "plain_http": 1,
    "playwright": 2,
    "egress_variation": 4,
    "residential_proxy": 5,
}

# Pre-created monthly partitions of offer_observation (UTC months, inclusive). There is no
# default partition: rows outside existing months fail loudly until the loader has called
# pi_ensure_offer_observation_partition() for them (e.g. SRC-15 backfill before 2026).
PARTITIONS_FROM = "2026-01-01"
PARTITIONS_TO = "2027-12-01"
# pi_ensure_offer_observation_partition() refuses months outside [floor, now + horizon), so a
# garbled timestamp (bad clock, parse error) cannot mint a partition for 1970 or 2099.
PARTITION_FLOOR = "2000-01-01"
PARTITION_HORIZON_MONTHS = 24

# Tables the app may only INSERT into and SELECT from (history is never rewritten, DAT-01).
# Each also carries owner-level UPDATE/DELETE/TRUNCATE triggers; evidence alone may be
# deleted once past retention_until (DAT-10).
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
    "pi_reject_evidence_mutation()",
    "pi_ensure_offer_observation_partition(date)",
)

# field_state keys whose column is never null; field_state only qualifies how they were
# determined, so only these may carry 'observed' (pi_core QUALIFIED_FIELDS).
QUALIFIED_FIELDS: tuple[str, ...] = ("availability_state",)

MONEY = "numeric(18,4)"
# Ratings are stored as published together with the source's scale (5, 10, 100, ...), so a
# 4.5/5 and a 90/100 stay distinguishable; comparisons normalise downstream.
RATING = "numeric(7,2)"
CURRENCY = "char(3) CHECK ({col} ~ '^[A-Z]{{3}}$')"
RUNG = f"smallint CHECK ({{col}} BETWEEN 0 AND {LADDER_RUNG_MAX})"


def _currency(col: str) -> str:
    return f"{col} {CURRENCY.format(col=col)}"


def _rung(col: str) -> str:
    return f"{col} {RUNG.format(col=col)}"


def _used_rung(col: str) -> str:
    """A rung actually used: in range and not forbidden."""
    forbidden = ", ".join(str(r) for r in FORBIDDEN_RUNGS)
    return f"{_rung(col)} CHECK ({col} NOT IN ({forbidden}))"


def _positive_money(col: str) -> str:
    """Prices are NULL (with a field_state reason) or strictly positive; missing is never 0."""
    return f"{col} {MONEY} CHECK ({col} IS NULL OR {col} > 0)"


def _method_rung_check() -> str:
    cases = " ".join(f"WHEN '{m}' THEN {r}" for m, r in FETCH_METHOD_RUNG.items())
    return f"CHECK (ladder_rung_used = CASE fetch_method::text {cases} END)"


def _sql_list(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def _enum_sql(name: str, values: tuple[str, ...]) -> str:
    return f"CREATE TYPE {name} AS ENUM ({_sql_list(values)})"


FUNCTIONS_SQL = [
    # Every value of a field_state map must be a FieldState (DQ-02: missing is data).
    # 'observed' qualifies how a never-null field was determined; it is never a null reason,
    # so it is valid only on the qualified fields.
    f"""
    CREATE FUNCTION pi_field_state_valid(fs jsonb) RETURNS boolean
    LANGUAGE sql STABLE AS $$
      SELECT jsonb_typeof(fs) = 'object'
         AND NOT EXISTS (
           SELECT 1 FROM jsonb_each(fs) AS e(key, value)
           WHERE jsonb_typeof(e.value) <> 'string'
              OR NOT (e.value #>> '{{}}') = ANY (enum_range(NULL::field_state)::text[])
              OR (e.value #>> '{{}}' = 'observed'
                  AND e.key NOT IN ({_sql_list(QUALIFIED_FIELDS)}))
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
    # Evidence is append-only too, except that rows past retention_until may be deleted by
    # the retention job (DAT-04, DAT-10). Hashes and URIs are never rewritten.
    """
    CREATE FUNCTION pi_reject_evidence_mutation() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP = 'DELETE' AND OLD.retention_until < now() THEN
        RETURN OLD;
      END IF;
      RAISE EXCEPTION 'evidence is append-only; only rows past retention_until may be deleted'
        USING ERRCODE = 'insufficient_privilege';
    END
    $$
    """,
    # Creates the UTC monthly partition containing `month` if missing; returns its name.
    # SECURITY DEFINER so the pipeline (pi_app, no DDL rights) can extend the table; the fixed
    # search_path stops callers from substituting objects. The advisory lock serialises
    # concurrent loaders asking for the same month. Row triggers are cloned to new partitions
    # by PostgreSQL; the TRUNCATE guard is not, so it is added here.
    f"""
    CREATE FUNCTION pi_ensure_offer_observation_partition(month date) RETURNS text
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
    DECLARE
      lower_bound timestamptz := date_trunc('month', month)::timestamp AT TIME ZONE 'UTC';
      upper_bound timestamptz :=
        (date_trunc('month', month) + interval '1 month')::timestamp AT TIME ZONE 'UTC';
      part text := format('offer_observation_p%s', to_char(month, 'YYYYMM'));
    BEGIN
      IF month < date '{PARTITION_FLOOR}'
         OR month >= date_trunc('month', now()) + interval '{PARTITION_HORIZON_MONTHS} months' THEN
        RAISE EXCEPTION 'observation month % is outside [%, now + % months)',
          month, date '{PARTITION_FLOOR}', {PARTITION_HORIZON_MONTHS}
          USING ERRCODE = 'invalid_parameter_value';
      END IF;
      PERFORM pg_advisory_xact_lock(hashtext('pi_ensure_offer_observation_partition'),
                                    hashtext(part));
      IF to_regclass(format('public.%I', part)) IS NULL THEN
        EXECUTE format(
          'CREATE TABLE public.%I PARTITION OF public.offer_observation'
          ' FOR VALUES FROM (%L) TO (%L)',
          part, lower_bound, upper_bound
        );
        EXECUTE format(
          'CREATE TRIGGER no_truncate BEFORE TRUNCATE ON public.%I'
          ' FOR EACH STATEMENT EXECUTE FUNCTION public.pi_reject_mutation()',
          part
        );
      END IF;
      RETURN part;
    END
    $$
    """,
    "REVOKE EXECUTE ON FUNCTION pi_ensure_offer_observation_partition(date) FROM PUBLIC",
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
      {_used_rung("ladder_rung_current")} NOT NULL DEFAULT 0,
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
      {_used_rung("ladder_rung_used")} NOT NULL,
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
    # ladder_rung_used and fetch_method are per request, not per run: the ladder escalates
    # request by request, so the rung can vary within a crawl_run (ADR-0003 audit trail).
    f"""
    CREATE TABLE evidence (
      id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
      crawl_run_id bigint NOT NULL REFERENCES crawl_run,
      url text NOT NULL,
      content_hash text NOT NULL,
      storage_uri text NOT NULL,
      retrieved_at timestamptz NOT NULL,
      http_status smallint,
      {_used_rung("ladder_rung_used")} NOT NULL,
      fetch_method fetch_method NOT NULL,
      retention_until timestamptz NOT NULL,
      {_method_rung_check()}
    )
    """,
    "CREATE INDEX evidence_content_hash_idx ON evidence (content_hash)",
    """
    CREATE TRIGGER evidence_append_only BEFORE UPDATE OR DELETE ON evidence
      FOR EACH ROW EXECUTE FUNCTION pi_reject_evidence_mutation()
    """,
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
    # No reviewer names or other PII, by design (SEC-06).
    f"""
    CREATE TABLE review (
      id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
      listing_id bigint NOT NULL REFERENCES source_listing,
      source_review_id text NOT NULL,
      rating {RATING},
      rating_scale {RATING} CHECK (rating_scale > 0),
      title text,
      body text,
      lang text,
      posted_at timestamptz,
      verified_flag boolean,
      helpful_count integer CHECK (helpful_count >= 0),
      attributes jsonb NOT NULL DEFAULT '{{}}',
      UNIQUE (listing_id, source_review_id),
      CHECK ((rating IS NULL) = (rating_scale IS NULL)),
      CHECK (rating BETWEEN 0 AND rating_scale)
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
      {_positive_money("min_spend")},
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
    # Append-only (DAT-01), UTC-monthly range partitions (DAT-13). The partition key is part
    # of every unique key.
    # Idempotency contract (DAT-09, SRC-10): idempotency_key is the pipeline's hash of the
    # logical key (DAT-02 grain), and observed_at must come from the evidence
    # (evidence.retrieved_at or the source's own timestamp), never re-stamped with now() on
    # retry. Then a replay hits UNIQUE (idempotency_key, observed_at) and ON CONFLICT DO
    # NOTHING makes it a no-op; a re-stamped observed_at would create a duplicate.
    # Missing is data (DQ-02): prices are NULL or > 0, never 0, and a NULL price_current needs
    # a field_state reason. quality_status is NULL until the quality gate has run (no default).
    # No false stock-outs: out_of_stock is not allowed when availability itself was blocked or
    # unknown. A range price (PRC-13) keeps both bounds instead of inventing a single price.
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
      {_positive_money("price_current")},
      {_positive_money("price_regular_stated")},
      {_positive_money("price_promo")},
      {_positive_money("price_member")},
      {_positive_money("price_range_min")},
      {_positive_money("price_range_max")},
      price_type price_type,
      {_currency("currency")},
      installment jsonb,
      tax_status tax_status NOT NULL DEFAULT 'unknown',
      {_positive_money("unit_price_derived")},
      unit_basis text,
      availability_state availability_state NOT NULL,
      available_variants integer CHECK (available_variants >= 0),
      low_stock_flag boolean,
      delivery_promise text,
      rating_value {RATING},
      rating_scale {RATING} CHECK (rating_scale > 0),
      rating_count integer CHECK (rating_count >= 0),
      rank_in_category integer CHECK (rank_in_category > 0),
      rank_in_search jsonb,
      badges_at_time text[] NOT NULL DEFAULT '{{}}',
      field_state jsonb NOT NULL DEFAULT '{{}}' CHECK (pi_field_state_valid(field_state)),
      evidence_id bigint REFERENCES evidence,
      quality_status quality_status,
      correction_of bigint,
      PRIMARY KEY (observation_id, observed_at),
      UNIQUE (idempotency_key, observed_at),
      CHECK (
        currency IS NOT NULL OR num_nonnulls(
          price_current, price_regular_stated, price_promo, price_member, unit_price_derived,
          price_range_min, price_range_max
        ) = 0
      ),
      CHECK ((price_range_min IS NULL) = (price_range_max IS NULL)),
      CHECK (price_range_min <= price_range_max),
      CHECK ((price_type IS NOT DISTINCT FROM 'range') = (price_range_min IS NOT NULL)),
      CHECK (price_current IS NULL OR price_type NOT IN ('range', 'quote_only')),
      -- DAT-06, contract point 2 v2: a negative availability claim needs availability itself
      -- to have been observed on the page. Other fields' states do not gate availability.
      CHECK (
        availability_state NOT IN ('out_of_stock', 'removed', 'not_deliverable')
        OR field_state ->> 'availability_state' IS NOT DISTINCT FROM 'observed'
      ),
      CHECK ((availability_state = 'low_stock') = (low_stock_flag IS TRUE)),
      CHECK (price_current IS NOT NULL OR field_state ? 'price_current'),
      CHECK ((rating_value IS NULL) = (rating_scale IS NULL)),
      CHECK (rating_value BETWEEN 0 AND rating_scale),
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
    """
    CREATE INDEX offer_observation_correction_idx ON offer_observation (correction_of)
      WHERE correction_of IS NOT NULL
    """,
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
    CREATE TRIGGER listing_content_append_only BEFORE UPDATE OR DELETE ON listing_content
      FOR EACH ROW EXECUTE FUNCTION pi_reject_mutation()
    """,
    """
    CREATE TRIGGER review_summary_append_only BEFORE UPDATE OR DELETE ON review_summary
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
    """
    CREATE TRIGGER offer_promotion_append_only BEFORE UPDATE OR DELETE ON offer_promotion
      FOR EACH ROW EXECUTE FUNCTION pi_reject_mutation()
    """,
    # ------------------------------------------------------------ matching
    # Versioned match graph (MAT-08) with one current edge per pair: a rejected or locked
    # verdict (MAT-05, MAT-07) is the pair's current edge, so the matcher cannot add a
    # competing proposal next to it. Superseding closes valid_to and inserts a new edge.
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
    CREATE UNIQUE INDEX match_edge_current_idx ON match_edge (variant_a, variant_b)
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
    # Row triggers do not fire on TRUNCATE (including TRUNCATE ... CASCADE from a parent).
    *(
        f"CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON {table}"
        " FOR EACH STATEMENT EXECUTE FUNCTION pi_reject_mutation()"
        for table in APPEND_ONLY_TABLES
    ),
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
        f"GRANT EXECUTE ON FUNCTION pi_ensure_offer_observation_partition(date) TO {APP_ROLE}",
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
