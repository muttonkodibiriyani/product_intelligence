/**
 * The read-only tools (design §4): one per service-layer endpoint, plus five thin views over
 * sections of /summary. Paths, parameters and
 * limits follow `docs/contracts/pi-api.openapi.json` (`/api/v1/*`); `test/contract.test.ts`
 * checks every tool's request against it and runs the golden responses through the registry.
 * Inputs are strict: unknown keys, free-form SQL, URLs and write-shaped arguments are rejected
 * before any request. Money inputs are decimal text in the dataset currency, never floats.
 */
import { z } from "zod";

import type { ApiRequest } from "../api/client.js";
import { defineTool, type ToolView } from "./types.js";
import { unitPriceView } from "./unit-price.js";

/**
 * Page size for search_products (the API allows up to 100). A worst-case card without its
 * match list (four retailers priced, 120-character name) is about 950 characters sanitised, so
 * 15 stay under MAX_RESULT_CHARS; with the match list, 12 were already refused.
 */
export const MAX_LIMIT = 15;
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

function withoutMatches(data: unknown): unknown {
  if (typeof data !== "object" || data === null || Array.isArray(data)) return data;
  const record = data as Record<string, unknown>;
  if (!Array.isArray(record.items)) return data;
  const items = record.items.map((item: unknown) => {
    if (typeof item !== "object" || item === null || Array.isArray(item)) return item;
    return Object.fromEntries(Object.entries(item).filter(([key]) => key !== "matches"));
  });
  return { ...record, items };
}

export const searchProducts = defineTool({
  name: "search_products",
  version: "3",
  description:
    "Find products by text (English or Arabic), brand, category, retailer ids, match state and " +
    "price range (decimal text in the dataset currency). Returns product cards with the latest " +
    "price at each retailer and, with exactly two retailers, the gap (the first is the base). " +
    "Use it to find product ids for get_product (match details), compare or reviews_summary.",
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
  // Each card's match list is dropped (get_product has it) so a full page fits the size cap.
  view: (data) => ({ data: withoutMatches(data) }),
});

/** Products scanned per price_per_unit call (the API's page maximum). */
export const UNIT_PRICE_SCAN = 100;

export const pricePerUnit = defineTool({
  name: "price_per_unit",
  version: "1",
  description:
    "Price per 1 ml or 1 g ('cheapest per ml', 'best value'): listed price divided by the " +
    "published size (L, cl, kg, mg converted exactly). Filters as search_products. Rows are " +
    "ranked within one measure and one currency; always state the currency. If partial is " +
    "true, say 'checked the first <scanned> of <matching> products'. `excluded` counts " +
    "products left out by reason (no size, other unit, no price, sizeUnproven: sold at " +
    "several retailers without a proven same size).",
  minRole: "viewer",
  input: z
    .object({
      q: text.optional(),
      ...filters,
      retailer: retailerList.optional(),
      per: z.enum(["ml", "g"]).optional(),
      order: z.enum(["asc", "desc"]).default("asc"),
      rows: z.number().int().min(1).max(MAX_ROWS).default(10),
    })
    .strict(),
  listKey: "rows",
  request: ({ q, brand, category, retailer }) =>
    get("/products", { q, brand, category, retailer, sort: "name", limit: UNIT_PRICE_SCAN }),
  view: (data, input) => unitPriceView(data, input),
});

export const getProduct = defineTool({
  name: "get_product",
  version: "3",
  description:
    "Full detail for one product id. Returns:\n" +
    "- the offer at each retailer: price, regular price, promo %, rating, size, availability;\n" +
    "- per retailer pair, the price gap and the cheaper side (base, other or equal), when the " +
    "product is a reviewed exact same-size match, otherwise the excluded reason;\n" +
    "- match details and evidence links.\n" +
    "An offer with price null and priceFlag invalid_low had a shown price at or below 0.01, " +
    "withheld as invalid (see the invalid_price_excluded caveat); say so, never call it 0 or free.",
  minRole: "viewer",
  input: z.object({ id: productId }).strict(),
  byId: true,
  request: ({ id }) => get(`/products/${encodeURIComponent(id)}`),
});

export const compare = defineTool({
  name: "compare",
  version: "4",
  description:
    "Compare prices between two retailers (base and other, ids from coverage_status). Pass up " +
    "to 25 product ids, or brand/category filters. Only exact, approved or locked, same-size " +
    "pairs count. Each row has gap {amount, pct, cheaper}; cheaper is base, other or equal. For " +
    "5 or more counted pairs it adds the median and mean gap %, cheaper-at counts and basket " +
    "totals; groupBy brand or category adds the same summary per group. The summary always " +
    "covers every row; a cut list keeps the largest |gap pct| first. summary.gapHist bins the " +
    "counted pairs' gap % at its 10 edges (-50 to 50) into 11 counts, below the first edge to " +
    "at or above the last; each bin is [lo, hi) and the counts sum to n." +
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
    "(the date of the retailer's latest collected data; use it for 'how fresh / how old is the " +
    "data') and notes. Call it first to learn the retailer ids the other tools need, and before " +
    "answering questions about what is or is not available.",
  minRole: "viewer",
  input: z.object({ retailer: retailerList.optional() }).strict(),
  request: (input) => get("/coverage", input),
});
export const priceHistory = defineTool({
  name: "price_history",
  version: "1",
  description:
    "Price history of one product id: per retailer, one point per collection date with price, " +
    "regular price and availability. Needs collection history; without it this returns " +
    "not_enough_data (capability_off). Use dates as written; say 'no price' for a null price.",
  minRole: "viewer",
  input: z
    .object({ id: productId, from: isoDate.optional(), to: isoDate.optional() })
    .strict()
    .refine((value) => !value.from || !value.to || value.from <= value.to, {
      message: "from must not be after to",
    }),
  byId: true,
  request: ({ id, ...rest }) => get(`/products/${encodeURIComponent(id)}/history`, rest),
});

export const availability = defineTool({
  name: "availability",
  version: "1",
  description:
    "Stock availability per retailer on a date (default: the latest): counts per stock state " +
    "and the out-of-stock and low-stock shares (%) of offers in an observed stock state " +
    "(`denominator`). Retailers that do not show stock return a reason instead of shares. " +
    "Without stock data this returns not_enough_data.",
  minRole: "viewer",
  input: z
    .object({ ...filters, retailer: retailerList.optional(), date: isoDate.optional() })
    .strict(),
  request: (input) => get("/availability", input),
});

/** Which withholdable part of /summary (API `Section`) each summary field belongs to. */
type SummarySection = "prices" | "promotions" | "ratings";

/** The context every /summary view keeps, so answers can cite the retailer and freshness. */
const SUMMARY_CONTEXT = ["retailer", "asOf", "currency", "freshness"] as const;

/**
 * A view of /summary: the context plus `fields`, unchanged. When any field is null and the
 * service listed its section as withheld, the view is not_enough_data with that reason.
 */
export function summaryView(
  fields: readonly string[],
  section: SummarySection | undefined,
): (data: unknown) => ToolView {
  return (data) => {
    if (typeof data !== "object" || data === null || Array.isArray(data)) return { data };
    const record = data as Record<string, unknown>;
    const picked: Record<string, unknown> = {};
    for (const key of [...SUMMARY_CONTEXT, ...fields]) {
      if (key in record) picked[key] = record[key];
    }
    const withheldList = Array.isArray(record.withheld) ? record.withheld : [];
    const mine = withheldList.find(
      (w): w is { section: string; reason: string } =>
        typeof w === "object" &&
        w !== null &&
        (w as { section?: unknown }).section === section &&
        typeof (w as { reason?: unknown }).reason === "string",
    );
    const missing = fields.some((key) => record[key] === null || record[key] === undefined);
    return mine && missing ? { data: picked, withheld: mine.reason } : { data: picked };
  };
}

const summaryInput = z
  .object({
    retailer: retailerId
      .optional()
      .describe(
        "retailer id from coverage_status; default: the retailer with the most collected offers",
      ),
  })
  .strict();
const SUMMARY_NOTE =
  " From the retailer's current snapshot (/summary): `asOf` and `freshness` say how recent it " +
  "is. Money is decimal text in `currency`. A null value is withheld (not measured), never zero.";

export const priceLadder = defineTool({
  name: "price_ladder",
  version: "1",
  description:
    "Price ladder per category at one retailer: number of priced products (n) and the min, " +
    "25th percentile, median, 75th percentile and max price." +
    SUMMARY_NOTE,
  minRole: "viewer",
  input: summaryInput,
  request: (input) => get("/summary", input),
  view: summaryView(["ladder"], "prices"),
});

export const priceDistribution = defineTool({
  name: "price_distribution",
  version: "1",
  description:
    "How prices are spread at one retailer: a histogram (bucket `edges` and product `counts` " +
    "per bucket), the median price and the number of priced products." +
    SUMMARY_NOTE,
  minRole: "viewer",
  input: summaryInput,
  request: (input) => get("/summary", input),
  view: summaryView(["priceHist", "medianPrice", "priced"], "prices"),
});

export const brandPositioning = defineTool({
  name: "brand_positioning",
  version: "1",
  description:
    "Where brands sit on price at one retailer: per brand, the number of priced products (n) " +
    "and the median price." +
    SUMMARY_NOTE,
  minRole: "viewer",
  input: summaryInput,
  request: (input) => get("/summary", input),
  view: summaryView(["brandPrice"], "prices"),
});

export const categoryMix = defineTool({
  name: "category_mix",
  version: "1",
  description:
    "The category mix of one retailer's catalogue: per category path, the number of products " +
    "(n). Do not compute shares; quote the counts and the total `products`." +
    SUMMARY_NOTE,
  minRole: "viewer",
  input: summaryInput,
  request: (input) => get("/summary", input),
  view: summaryView(["categoryMix", "products"], undefined),
});

export const assortmentBreadth = defineTool({
  name: "assortment_breadth",
  version: "1",
  description:
    "How broad one retailer's assortment is: product, priced-product, brand and category " +
    "counts." +
    SUMMARY_NOTE,
  minRole: "viewer",
  input: summaryInput,
  request: (input) => get("/summary", input),
  view: summaryView(["products", "priced", "brands", "categories"], undefined),
});

export const categoryCompare = defineTool({
  name: "category_compare",
  version: "1",
  description:
    "Category-to-category prices between two retailers (base and other, ids from " +
    "coverage_status) across both full catalogues on the latest date. No product matching: " +
    "for like-for-like pairs use compare. level bucket (default) is the nine top-level " +
    "categories; common is the finer taxonomy read from retailer breadcrumbs. Each row has " +
    "each side's n and price stats (median, mean, p25, p75, min, max) and gap {amount, pct, " +
    "cheaper} between the two medians. A side with fewer than minCohort products has its " +
    "prices null and the row has no gap (gapReason says why); say there is not enough data, " +
    "never 0. A category gap reflects each retailer's range in that category, not the same " +
    "items being cheaper; say so. coverage gives each side's priced, mapped and unmapped counts.",
  minRole: "viewer",
  input: z
    .object({ retailers: retailerPair, level: z.enum(["bucket", "common"]).optional() })
    .strict(),
  request: (input) => get("/category-compare", input),
  // The unmapped breadcrumb list is for writing taxonomy rules (retailer text, unbounded); the
  // answer keeps only its count, unmappedPaths.
  view: (data) => {
    if (typeof data !== "object" || data === null || Array.isArray(data)) return { data };
    return { data: Object.fromEntries(Object.entries(data).filter(([key]) => key !== "unmapped")) };
  },
});

export const TOOLS = [
  searchProducts,
  pricePerUnit,
  getProduct,
  compare,
  indexTrend,
  promotions,
  assortmentGaps,
  launches,
  reviewsSummary,
  coverageStatus,
  priceHistory,
  availability,
  priceLadder,
  priceDistribution,
  brandPositioning,
  categoryMix,
  assortmentBreadth,
  categoryCompare,
] as const;
