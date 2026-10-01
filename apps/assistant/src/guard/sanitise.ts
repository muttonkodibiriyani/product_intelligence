/**
 * Fail-closed handling of API `data` before the model sees it (design §7). The service layer
 * returns retailer-sourced text raw, so every string is treated as untrusted and wrapped as
 * `{ untrusted }`, with these exceptions:
 *
 * - Decimal text (money, %, index, ratings) passes: it cannot carry instructions, and the
 *   numeric verifier needs it.
 * - ISO dates/datetimes and `#rrggbb` colours pass.
 * - Short identifier-shaped values under known structural keys pass (status, reason, retailer,
 *   id, enums).
 * - Keys ending in "url"/"Url" go through the https + host-allowlist filter.
 *
 * A new API field therefore defaults to untrusted. Object keys that are not identifier-shaped
 * (for example a map keyed by brand name) are dropped, because keys are not wrapped.
 *
 * Also dropped: `minor` (the integer minor-unit copy of every money amount; the model quotes
 * `amount`, and an integer like 9000 must not count as a supported number), `image` (the card
 * thumbnail URL; thumbnails are attached server-side from productIds, §7) and, for callers
 * below admin, the admin-only evidence keys `runId` and `source`.
 */
import { DECIMAL_TEXT } from "./decimal.js";
import { type Untrusted, evidenceUrl, untrusted } from "./untrusted.js";

export const STRUCTURAL_KEYS: ReadonlySet<string> = new Set([
  "status",
  "reason",
  "retailer",
  "base",
  "other",
  "cheaper",
  "currency",
  "market",
  "id",
  "productId",
  "runId",
  "matchClass",
  "reviewState",
  "excludedReason",
  "gapExcludedReason",
  "summaryUnavailable",
  "label",
  "unit",
  "fieldStatus",
  "class",
  "convention",
  "availability",
  "a",
  "b",
  "missingAt",
  "presentAt",
  "groupBy",
  "endpoint",
]);

/**
 * Keys known to hold retailer-sourced text: always wrapped, even when the value looks like a
 * number (a product named "50" must not become a verifiable number). Every property the OpenAPI
 * contract marks `x-pi-source-text` is listed here (or is a URL key), and none is structural:
 * `test/contract.test.ts` checks this against `docs/contracts/pi-api.openapi.json`.
 */
export const SOURCE_TEXT_KEYS: ReadonlySet<string> = new Set([
  "brand",
  "name",
  "title",
  "sku",
  "category",
  "shade",
  "shadeFamilies",
  "description",
  "key",
  "note",
  "method",
  "stage",
  "source",
  "sizeLabel",
  "sizeLabels",
  "sizeSystem",
  "caption",
  "catalogueId",
  "externalId",
  "structuredId",
  "structuredProductId",
  "productType",
  "roles",
  "selections",
  "selectionLabels",
]);

/** Always removed (see the module comment). */
export const DROPPED_KEYS: ReadonlySet<string> = new Set(["minor", "image", "optionValues"]);

/** Admin-only evidence fields, removed for viewers as defence in depth. */
export const ADMIN_ONLY_KEYS: ReadonlySet<string> = new Set(["runId", "source"]);

const IDENTIFIER = /^[A-Za-z0-9_.:-]{1,64}$/;
const KEY = /^[A-Za-z][A-Za-z0-9_]{0,63}$/;
const ISO = /^\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2}))?$/;
const HEX = /^#[0-9a-fA-F]{6}$/;
const MAX_DEPTH = 8;

export type Sanitised =
  string | number | boolean | null | Untrusted | Sanitised[] | { [key: string]: Sanitised };

function isUrlKey(key: string | undefined): boolean {
  return key !== undefined && /(?:^url|Url)$/.test(key);
}

export interface SanitiseOptions {
  readonly evidenceHosts: readonly string[];
  /** Keep `ADMIN_ONLY_KEYS`; only for admin callers. */
  readonly admin: boolean;
}

export function sanitiseData(value: unknown, options: SanitiseOptions): Sanitised {
  return sanitiseValue(value, options);
}

function sanitiseValue(
  value: unknown,
  options: SanitiseOptions,
  key?: string,
  depth = 0,
): Sanitised {
  if (depth > MAX_DEPTH) return null;
  if (value === null || typeof value === "boolean") return value;
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  if (typeof value === "string") {
    if (isUrlKey(key)) return evidenceUrl(value, options.evidenceHosts);
    if (key !== undefined && SOURCE_TEXT_KEYS.has(key)) return untrusted(value);
    if (DECIMAL_TEXT.test(value) || ISO.test(value) || HEX.test(value)) return value;
    if (key !== undefined && STRUCTURAL_KEYS.has(key) && IDENTIFIER.test(value)) return value;
    return untrusted(value);
  }
  if (Array.isArray(value)) {
    return value.map((item) => sanitiseValue(item, options, key, depth + 1));
  }
  if (typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>);
    // A pre-wrapped value from upstream is re-sanitised, never trusted as already clean.
    if (entries.length === 1 && entries[0]?.[0] === "untrusted") {
      return untrusted(String(entries[0][1]));
    }
    const out: { [key: string]: Sanitised } = {};
    for (const [childKey, child] of entries) {
      if (!KEY.test(childKey) || DROPPED_KEYS.has(childKey)) continue;
      if (!options.admin && ADMIN_ONLY_KEYS.has(childKey)) continue;
      out[childKey] = sanitiseValue(child, options, childKey, depth + 1);
    }
    return out;
  }
  return null;
}
