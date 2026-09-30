-- Export one source's snapshot from pi_db as pi_match JSONL (one ProductRecord per line).
-- Usage (local stack):
--   psql "$PI_DATABASE_URL" -v source=sephora_ae -At -f packages/pi_match/sql/export_snapshot.sql > sephora.jsonl
-- Brand, size, shade and GTIN come from the linked variant when the loader set one, else from
-- listing_content.labels (brand/size/shade/gtin keys) of the latest content row. Price is the
-- latest observation's price_current. Nothing is inferred: missing values are omitted (null).
-- Rows without any brand are skipped: they cannot be blocked by brand.
WITH latest_offer AS (
  SELECT DISTINCT ON (o.source_listing_id)
    o.source_listing_id, o.price_current, o.currency
  FROM offer_observation o
  ORDER BY o.source_listing_id, o.observed_at DESC, o.observation_id DESC
),
latest_content AS (
  SELECT DISTINCT ON (c.listing_id) c.listing_id, c.labels
  FROM listing_content c
  ORDER BY c.listing_id, c.observed_at DESC
)
SELECT json_strip_nulls(json_build_object(
  'source', s.name,
  'source_key', l.source_listing_key,
  'brand', COALESCE(b.name, lc.labels ->> 'brand'),
  'name', l.name_original,
  'url', l.url,
  'size', COALESCE(v.size_value::text || ' ' || v.size_unit, lc.labels ->> 'size'),
  'shade', COALESCE(NULLIF(concat_ws(' ', v.shade_code, v.shade), ''), lc.labels ->> 'shade'),
  'gtin', COALESCE(v.gtin, lc.labels ->> 'gtin'),
  'category', l.category_path_source,
  'price', lo.price_current::text,
  'currency', lo.currency
))
FROM source_listing l
JOIN source s ON s.id = l.source_id
LEFT JOIN variant v ON v.id = l.variant_id
LEFT JOIN product_family f ON f.id = v.family_id
LEFT JOIN brand b ON b.id = f.brand_id
LEFT JOIN latest_offer lo ON lo.source_listing_id = l.id
LEFT JOIN latest_content lc ON lc.listing_id = l.id
WHERE s.name = :'source'
  AND COALESCE(b.name, lc.labels ->> 'brand') IS NOT NULL
ORDER BY l.source_listing_key;
