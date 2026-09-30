/**
 * The nine read-only tools, one per service-layer endpoint (design §4). Inputs are strict:
 * unknown keys, free-form SQL, URLs and write-shaped arguments are rejected before any request.
 * Money inputs are decimal text in the dataset currency, never floats.
 */
import { z } from "zod";

import type { ApiRequest } from "../api/client.js";
import { defineTool } from "./types.js";

export const MAX_LIMIT = 25;

const limit = z.number().int().min(1).max(MAX_LIMIT).default(10);
const text = z.string().trim().min(1).max(120);
const textList = z.array(z.string().trim().min(1).max(80)).min(1).max(10);
const retailerId = z.string().regex(/^[a-z][a-z0-9_]{1,62}$/, "retailer id from coverage_status");
const productId = z.string().regex(/^[A-Za-z0-9_.:-]{1,200}$/);
const money = z.string().regex(/^\d{1,9}(?:\.\d{1,3})?$/, "decimal amount, e.g. 120.50");
const isoDate = z.string().regex(/^\d{4}-\d{2}-\d{2}$/);
const retailerPair = z
  .object({ base: retailerId, other: retailerId })
  .strict()
  .refine(({ base, other }) => base !== other, { message: "two different retailers" });
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
      // A retailer pair travels as "base,other" (service-layer §6 common filters).
      const pair = value as { readonly base: string; readonly other: string };
      query[key] = [`${pair.base},${pair.other}`];
    } else {
      query[key] = Array.isArray(value) ? value.map(String) : [String(value)];
    }
  }
  return query;
}

function get(path: string, input: Readonly<Record<string, QueryValue>>): ApiRequest {
  return { method: "GET", path, query: toQuery(input) };
}

export const searchProducts = defineTool({
  name: "search_products",
  version: "1",
  description:
    "Find products by text (English or Arabic), brand, category, retailer ids, match state and " +
    "price range (decimal text in the dataset currency). Returns product cards with the latest " +
    "price at each retailer. Use it to find product ids for get_product or compare.",
  minRole: "viewer",
  input: z
    .object({
      q: text.optional(),
      ...filters,
      retailer: z.array(retailerId).min(1).max(4).optional(),
      matched: z.boolean().optional(),
      priceMin: money.optional(),
      priceMax: money.optional(),
      sort: z.enum(["name", "price_asc", "price_desc", "gap"]).default("name"),
      limit,
    })
    .strict(),
  request: (input) => get("/v1/products", input),
});

export const getProduct = defineTool({
  name: "get_product",
  version: "1",
  description:
    "Full detail for one product id. Returns:\n" +
    "- the offer at each retailer: price, regular price, promo %, rating, size and shades;\n" +
    "- the price gap and the cheaper retailer, when the product is a reviewed exact same-size match;\n" +
    "- match details and evidence links.",
  minRole: "viewer",
  input: z.object({ id: productId }).strict(),
  request: ({ id }) => ({ method: "GET", path: `/v1/products/${encodeURIComponent(id)}` }),
});

export const compare = defineTool({
  name: "compare",
  version: "1",
  description:
    "Compare prices between two retailers (default: the first two in the dataset). Pass 2-6 " +
    "product ids, or brand/category filters. Only exact, approved or locked, same-size pairs count. Returns " +
    "per-product rows with the cheaper retailer. For 5 or more counted pairs it adds the median " +
    "and mean gap %, cheaper-at counts and basket totals.",
  minRole: "viewer",
  input: z
    .object({
      ids: z.array(productId).min(2).max(6).optional(),
      ...filters,
      retailers: retailerPair.optional(),
      limit,
    })
    .strict()
    .refine((value) => !(value.ids && (value.brand || value.category)), {
      message: "use either ids or brand/category filters, not both",
    }),
  request: (input) => ({ method: "POST", path: "/v1/compare", body: input }),
});

export const indexTrend = defineTool({
  name: "index_trend",
  version: "1",
  description:
    "Price index between two retailers over a fixed basket of exact, approved or locked, same-size pairs. " +
    "Index = sum of other prices / sum of base prices x 100, over the basket counted on the first " +
    "date; above 100 means other is dearer than base. One point per collection date. A trend needs " +
    "two or more dates of history.",
  minRole: "viewer",
  input: z
    .object({
      ...filters,
      retailers: retailerPair.optional(),
      from: isoDate.optional(),
      to: isoDate.optional(),
    })
    .strict()
    .refine((value) => !value.from || !value.to || value.from <= value.to, {
      message: "from must not be after to",
    }),
  request: (input) => get("/v1/index", input),
});

export const promotions = defineTool({
  name: "promotions",
  version: "1",
  description:
    "Current promotions: the share of offers on promotion at each retailer and the promoted " +
    "products, deepest first. Early recon offers are excluded.",
  minRole: "viewer",
  input: z
    .object({
      ...filters,
      retailer: z.array(retailerId).min(1).max(4).optional(),
      minPct: z.number().int().min(1).max(100).optional(),
      limit,
    })
    .strict(),
  request: (input) => get("/v1/promotions", input),
});

export const assortmentGaps = defineTool({
  name: "assortment_gaps",
  version: "1",
  description:
    "Products offered at presentAt with no match at missingAt. If missingAt's coverage is partial " +
    "or blocked, this returns not_enough_data instead of claiming absence. Rows are labelled " +
    "'unmatched' unless matching was reviewed; unmatched does not prove the product is not sold.",
  minRole: "viewer",
  input: z
    .object({
      missingAt: retailerId.optional(),
      presentAt: retailerId.optional(),
      ...filters,
      limit,
    })
    .strict()
    .refine((value) => !value.missingAt || value.missingAt !== value.presentAt, {
      message: "missingAt and presentAt must differ",
    }),
  request: (input) => get("/v1/assortment-gaps", input),
});

export const launches = defineTool({
  name: "launches",
  version: "1",
  description:
    "Products first seen at a retailer since a date. Needs collection history; without it this " +
    "returns not_enough_data (capability_off).",
  minRole: "viewer",
  input: z
    .object({
      since: isoDate.optional(),
      retailer: retailerId.optional(),
      category: textList.optional(),
      limit,
    })
    .strict(),
  request: (input) => get("/v1/launches", input),
});

export const reviewsSummary = defineTool({
  name: "reviews_summary",
  version: "1",
  description:
    "Star ratings per retailer for up to 25 product ids or brand/category filters: rating count, " +
    "count-weighted average and simple average (2 dp). Review text, themes and rating " +
    "distributions are not collected.",
  minRole: "viewer",
  input: z
    .object({
      ids: z.array(productId).min(1).max(MAX_LIMIT).optional(),
      ...filters,
      retailer: z.array(retailerId).min(1).max(4).optional(),
    })
    .strict()
    .refine((value) => !(value.ids && (value.brand || value.category)), {
      message: "use either ids or brand/category filters, not both",
    }),
  // The endpoint takes a repeated `id` (service-layer §6).
  request: ({ ids, ...rest }) => get("/v1/reviews-summary", { id: ids, ...rest }),
});

export const coverageStatus = defineTool({
  name: "coverage_status",
  version: "1",
  description:
    "What the data covers: each retailer's status (ok, partial, blocked or pending) and product " +
    "counts, which capabilities and fields exist, periods that were not observed, the cutoff and " +
    "the match stage. Call it before answering questions about what is or is not available.",
  minRole: "viewer",
  input: z.object({}).strict(),
  request: () => ({ method: "GET", path: "/v1/coverage" }),
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
