/**
 * The nine read-only tools, one per service-layer endpoint (design §4). Paths, parameters and
 * limits follow `docs/contracts/pi-api.openapi.json` (`/api/v1/*`); `test/contract.test.ts`
 * checks every tool's request against it and runs the golden responses through the registry.
 * Inputs are strict: unknown keys, free-form SQL, URLs and write-shaped arguments are rejected
 * before any request. Money inputs are decimal text in the dataset currency, never floats.
 */
import { z } from "zod";

import type { ApiRequest } from "../api/client.js";
import { defineTool } from "./types.js";

/** Page size for search_products (the API allows up to 100; tool results are capped by size). */
export const MAX_LIMIT = 25;
/** The API's cap on repeated list parameters (brand, category, retailer, id). */
export const MAX_LIST = 25;

const limit = z.number().int().min(1).max(MAX_LIMIT).default(10);
/**
 * Row cap for compare, promotions and launches (API 1.1.0 allows 1..500). Always sent, so a
 * result stays small; summaries are computed over every row by the API.
 */
export const MAX_ROWS = 25;
const rowLimit = z.number().int().min(1).max(MAX_ROWS).default(MAX_ROWS);
const TRUNCATED_NOTE =
  " At most `limit` rows (default 25) are returned; `total` counts them all. If `truncated` is " +
  "true, say the list was cut, as 'top {shown} of {total}'.";
const text = z.string().trim().min(1).max(120);
const textList = z.array(text).min(1).max(10);
const retailerId = z.string().regex(/^[a-z][a-z0-9_]{1,62}$/, "retailer id from coverage_status");
const retailerList = z.array(retailerId).min(1).max(4);
const productId = z.string().regex(/^[A-Za-z0-9_.:-]{1,120}$/);
const money = z.string().regex(/^\d{1,9}(?:\.\d{1,3})?$/, "decimal amount, e.g. 120.50");
const isoDate = z.string().regex(/^\d{4}-\d{2}-\d{2}$/);
const retailerPair = z
  .object({ base: retailerId, other: retailerId })
  .strict()
  .refine(({ base, other }) => base !== other, { message: "two different retailers" })
  .describe("ordered pair of retailer ids from coverage_status; base is the reference");
const filters = { brand: textList.optional(), category: textList.optional() };

type QueryValue =
  | string
  | number
  | boolean
  | readonly (string | number)[]
  | { readonly base: string; readonly other: string }
  | undefined;

/** Flatten a parsed input into query parameters; arrays repeat the key. */
export function toQuery(input: Readonly<Record<string, QueryValue>>): Record<string, string[]> {
  const query: Record<string, string[]> = {};
  for (const [key, value] of Object.entries(input)) {
    if (value === undefined) continue;
    if (typeof value === "object" && !Array.isArray(value)) {
      // A retailer pair travels as one parameter "base,other"; the order is meaningful.
      const pair = value as { readonly base: string; readonly other: string };
      query[key] = [`${pair.base},${pair.other}`];
    } else {
      query[key] = Array.isArray(value) ? value.map(String) : [String(value)];
    }
  }
  return query;
}

export const API_PREFIX = "/api/v1";

function get(path: string, input: Readonly<Record<string, QueryValue>> = {}): ApiRequest {
  return { method: "GET", path: `${API_PREFIX}${path}`, query: toQuery(input) };
}

const noIdsWithFilters = (value: {
  ids?: readonly string[] | undefined;
  brand?: readonly string[] | undefined;
  category?: readonly string[] | undefined;
}) => !(value.ids && (value.brand || value.category));
const NO_IDS_WITH_FILTERS = { message: "use either ids or brand/category filters, not both" };

export const searchProducts = defineTool({
  name: "search_products",
  version: "2",
  description:
    "Find products by text (English or Arabic), brand, category, retailer ids, match state and " +
    "price range (decimal text in the dataset currency). Returns product cards with the latest " +
    "price at each retailer and, with exactly two retailers, the gap (the first is the base). " +
    "Use it to find product ids for get_product, compare or reviews_summary.",
  minRole: "viewer",
  input: z
    .object({
      q: text.optional(),
      ...filters,
      retailer: retailerList.optional(),
      matched: z.boolean().optional(),
      priceMin: money.optional(),
      priceMax: money.optional(),
      sort: z.enum(["name", "price_asc", "price_desc", "gap", "gap_asc"]).default("name"),
      limit,
    })
    .strict(),
  request: (input) => get("/products", input),
});

export const getProduct = defineTool({
  name: "get_product",
  version: "2",
  description:
    "Full detail for one product id. Returns:\n" +
    "- the offer at each retailer: price, regular price, promo %, rating, size, availability;\n" +
    "- per retailer pair, the price gap and the cheaper side (base, other or equal), when the " +
    "product is a reviewed exact same-size match, otherwise the excluded reason;\n" +
    "- match details and evidence links.",
  minRole: "viewer",
  input: z.object({ id: productId }).strict(),
  request: ({ id }) => get(`/products/${encodeURIComponent(id)}`),
});

export const compare = defineTool({
  name: "compare",
  version: "3",
  description:
    "Compare prices between two retailers (base and other, ids from coverage_status). Pass up " +
    "to 25 product ids, or brand/category filters. Only exact, approved or locked, same-size " +
    "pairs count. Each row has gap {amount, pct, cheaper}; cheaper is base, other or equal. For " +
    "5 or more counted pairs it adds the median and mean gap %, cheaper-at counts and basket " +
    "totals; groupBy brand or category adds the same summary per group. The summary always " +
    "covers every row; a cut list keeps the largest |gap pct| first." +
    TRUNCATED_NOTE,
  minRole: "viewer",
  listKey: "rows",
  input: z
    .object({
      retailers: retailerPair,
      ids: z.array(productId).min(1).max(MAX_LIST).optional(),
      ...filters,
      date: isoDate.optional(),
      groupBy: z.enum(["brand", "category"]).optional(),
      limit: rowLimit,
    })
    .strict()
    .refine(noIdsWithFilters, NO_IDS_WITH_FILTERS),
  // The endpoint takes a repeated `id`.
  request: ({ ids, ...rest }) => get("/compare", { ...rest, id: ids }),
});

export const indexTrend = defineTool({
  name: "index_trend",
  version: "2",
  description:
    "Price index between two retailers (base and other) over a fixed basket of exact, approved " +
    "or locked, same-size pairs. Index = sum of other prices / sum of base prices x 100, over " +
    "the basket counted on the first date; above 100 means other is dearer than base. One " +
    "point per collection date. A trend needs two or more dates of history.",
  minRole: "viewer",
  input: z
    .object({
      retailers: retailerPair,
      ...filters,
      from: isoDate.optional(),
      to: isoDate.optional(),
    })
    .strict()
    .refine((value) => !value.from || !value.to || value.from <= value.to, {
      message: "from must not be after to",
    }),
  request: (input) => get("/index", input),
});

export const promotions = defineTool({
  name: "promotions",
  version: "3",
  description:
    "Promotions on a date (default: the latest): the share of offers on promotion at each " +
    "retailer and the promoted products. depthPct = (regular - price) / regular x 100, " +
    "computed from shown prices, not the retailer's stated discount; minPct filters on it. " +
    "Early recon offers are excluded. Shares cover every offer; a cut list keeps the deepest " +
    "discounts first." +
    TRUNCATED_NOTE,
  minRole: "viewer",
  listKey: "items",
  input: z
    .object({
      ...filters,
      retailer: retailerList.optional(),
      minPct: z.number().int().min(1).max(100).optional(),
      date: isoDate.optional(),
      limit: rowLimit,
    })
    .strict(),
  // The API takes minPct as decimal text.
  request: ({ minPct, ...rest }) =>
    get("/promotions", { ...rest, minPct: minPct === undefined ? undefined : String(minPct) }),
});

export const assortmentGaps = defineTool({
  name: "assortment_gaps",
  version: "2",
  description:
    "Products offered at presentAt with no match at missingAt (both required, ids from " +
    "coverage_status). If missingAt's coverage is partial or blocked, this returns " +
    "not_enough_data instead of claiming absence. Rows are labelled 'unmatched' unless " +
    "matching was reviewed; unmatched does not prove the product is not sold.",
  minRole: "viewer",
  input: z
    .object({
      missingAt: retailerId,
      presentAt: retailerId,
      ...filters,
      date: isoDate.optional(),
    })
    .strict()
    .refine((value) => value.missingAt !== value.presentAt, {
      message: "missingAt and presentAt must differ",
    }),
  request: (input) => get("/assortment-gaps", input),
});

export const launches = defineTool({
  name: "launches",
  version: "3",
  description:
    "Products first seen at a retailer since a date. Needs collection history; without it this " +
    "returns not_enough_data (capability_off). A cut list keeps the newest first." +
    TRUNCATED_NOTE,
  minRole: "viewer",
  listKey: "items",
  input: z
    .object({
      since: isoDate.optional(),
      retailer: retailerList.optional(),
      ...filters,
      limit: rowLimit,
    })
    .strict(),
  request: (input) => get("/launches", input),
});

export const reviewsSummary = defineTool({
  name: "reviews_summary",
  version: "2",
  description:
    "Star ratings per retailer for up to 25 product ids or brand/category filters: rating " +
    "count, count-weighted average and rating scale. Review text, themes and rating " +
    "distributions are not collected.",
  minRole: "viewer",
  input: z
    .object({
      ids: z.array(productId).min(1).max(MAX_LIST).optional(),
      ...filters,
      retailer: retailerList.optional(),
    })
    .strict()
    .refine(noIdsWithFilters, NO_IDS_WITH_FILTERS),
  // The endpoint takes a repeated `id`.
  request: ({ ids, ...rest }) => get("/reviews-summary", { ...rest, id: ids }),
});

export const coverageStatus = defineTool({
  name: "coverage_status",
  version: "2",
  description:
    "What the data covers: each retailer's id, status (supported, partial, blocked, pending or " +
    "retired; only supported backs an absence claim), product and matched counts, freshness " +
    "and notes. Call it first to learn the retailer ids the other tools need, and before " +
    "answering questions about what is or is not available.",
  minRole: "viewer",
  input: z.object({ retailer: retailerList.optional() }).strict(),
  request: (input) => get("/coverage", input),
});
export const TOOLS = [
  searchProducts,
  getProduct,
  compare,
  indexTrend,
  promotions,
  assortmentGaps,
  launches,
  reviewsSummary,
  coverageStatus,
] as const;
