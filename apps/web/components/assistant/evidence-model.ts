/**
 * What an answer shows beside its text, read from the tool results the server already
 * sanitised (`ToolEnvelope.data`): products as cards, per-shop shares as tiles, and one source
 * pill per citation that opens the page with the same filters. Every value here is the API's,
 * through the assistant's tools; nothing is computed from the model's prose. Untrusted text
 * (names, brands) is unwrapped with `plain()` and only ever rendered as text.
 */
import type { Money, Schemas } from '@/lib/api/types';
import { EMPTY_COMPARE, type GroupBy, toCompareSearch } from '@/lib/compare';
import { EMPTY, toSearch } from '@/lib/explore';
import { currencyExponent } from '@/lib/money';
import type { NavKey } from '@/lib/nav';
import { navHref } from '@/lib/nav';
import { EMPTY_PROMOTIONS, MIN_PCTS, type MinPct, toPromotionsSearch } from '@/lib/promotions';
import { type Verdict, verdictOf } from '@/lib/verdict';
import type { Citation, Sanitised, ToolEnvelope } from '@/lib/assistant/types';
import { isUntrusted, plain } from '@/lib/assistant/types';

/** Cards shown per tool result; the source pill carries the full count. */
export const MAX_CARDS = 6;
export const MAX_TILES = 4;

type Rec = { readonly [key: string]: Sanitised };

const isRec = (v: Sanitised | undefined): v is Rec =>
  typeof v === 'object' && v !== null && !Array.isArray(v) && !isUntrusted(v);

/** Text the API wrote (wrapped `{untrusted}`), or a plain string key; anything else is nothing. */
export function text(v: Sanitised | undefined): string | null {
  if (typeof v === 'string') return v;
  if (isUntrusted(v)) return plain(v);
  return null;
}

const str = (v: Sanitised | undefined): string | null => (typeof v === 'string' ? v : null);
const num = (v: Sanitised | undefined): number | null => (typeof v === 'number' ? v : null);
const list = (v: Sanitised | undefined): readonly Sanitised[] => (Array.isArray(v) ? v : []);
const strings = (v: Sanitised | undefined): string[] =>
  list(v).flatMap((x) => {
    const s = text(x);
    return s === null ? [] : [s];
  });

/**
 * A money value from a tool result. The sanitiser drops `minor` (the model must not quote it),
 * so it is rebuilt from the exact decimal text for the app's own money check.
 */
export function toMoney(v: Sanitised | undefined): Money | null {
  if (!isRec(v)) return null;
  const amount = str(v.amount);
  const currency = str(v.currency);
  if (amount === null || currency === null || !/^-?\d+(\.\d+)?$/.test(amount)) return null;
  const minor = Math.round(Number(amount) * 10 ** currencyExponent(currency));
  return Number.isFinite(minor) ? { amount, currency, minor } : null;
}

const toSize = (v: Sanitised | undefined): Schemas['Size'] | null => {
  if (!isRec(v)) return null;
  const value = str(v.value);
  const unit = text(v.unit);
  return value !== null && unit !== null ? { value, unit } : null;
};

const PRICE_FLAGS = new Set<string>(['invalid_low']);
const priceFlag = (v: Sanitised | undefined): Schemas['PriceFlag'] | undefined => {
  const s = str(v);
  return s !== null && PRICE_FLAGS.has(s) ? (s as Schemas['PriceFlag']) : undefined;
};

/** One shop's line on an evidence card, before the shop's display name is added. */
export interface EvidenceLine {
  readonly retailer: string;
  readonly price: Money | null;
  readonly priceFlag?: Schemas['PriceFlag'];
  readonly was?: Money | null;
  readonly off?: string | null;
  readonly notSold?: boolean;
  readonly size?: string | null;
}

/** A product from a tool result, ready for the PR 4 product card. */
export interface EvidenceCard {
  readonly id: string;
  readonly name: string;
  readonly brand: string | null;
  readonly category: string | null;
  readonly size: Schemas['Size'] | null;
  readonly lines: readonly EvidenceLine[];
  readonly verdict: Verdict | null;
}

const EXCLUDED = new Set<string>([
  'not_offered',
  'early',
  'no_match',
  'match_rejected',
  'match_unreviewed',
  'match_not_exact',
  'unpriced',
  'currency_mismatch',
  'size_mismatch',
  'size_unknown',
]);

const toGap = (v: Sanitised | undefined): Schemas['Gap'] | null => {
  if (!isRec(v)) return null;
  const amount = toMoney(v.amount);
  const cheaper = str(v.cheaper);
  const pct = str(v.pct);
  if (!amount || pct === null || !['base', 'other', 'equal'].includes(cheaper ?? '')) return null;
  return { amount, cheaper: cheaper as Schemas['Cheaper'], pct };
};

const toPairGap = (v: Sanitised | undefined): Schemas['PairGap'] | null => {
  if (!isRec(v)) return null;
  const base = str(v.base);
  const other = str(v.other);
  if (base === null || other === null) return null;
  const reason = str(v.excludedReason);
  const labels = strings(v.sizeLabels);
  return {
    base,
    other,
    gap: toGap(v.gap),
    excludedReason: reason !== null && EXCLUDED.has(reason) ? (reason as Schemas['Excluded']) : null,
    sizeLabels: labels.length === 2 ? [labels[0]!, labels[1]!] : null,
  };
};

/** A compare row (base and other price, the gap) as a two-line card with the pair's verdict. */
function compareCard(row: Rec, base: string, other: string): EvidenceCard | null {
  const id = str(row.id);
  const name = text(row.name);
  if (id === null || name === null) return null;
  const basePrice = toMoney(row.basePrice);
  const otherPrice = toMoney(row.otherPrice);
  const reason = str(row.excludedReason);
  const gap: Schemas['PairGap'] = {
    base,
    other,
    gap: toGap(row.gap),
    excludedReason: reason !== null && EXCLUDED.has(reason) ? (reason as Schemas['Excluded']) : null,
  };
  const prices: Record<string, Money | null> = {};
  if (basePrice) prices[base] = basePrice;
  if (otherPrice) prices[other] = otherPrice;
  return {
    id,
    name,
    brand: text(row.brand),
    category: strings(row.category)[0] ?? null,
    size: toSize(row.size),
    lines: [
      { retailer: base, price: basePrice, notSold: reason === 'not_offered' && !basePrice },
      { retailer: other, price: otherPrice, notSold: reason === 'not_offered' && !otherPrice },
    ],
    verdict: verdictOf({ gap, prices, priceFlags: {} }),
  };
}

/** A promotion item: the shop's price now, the regular price struck through, the depth. */
function promoCard(item: Rec): EvidenceCard | null {
  const id = str(item.id);
  const name = text(item.name);
  const retailer = str(item.retailer);
  const price = toMoney(item.price);
  if (id === null || name === null || retailer === null || !price) return null;
  return {
    id,
    name,
    brand: text(item.brand),
    category: null,
    size: null,
    lines: [{ retailer, price, was: toMoney(item.regular), off: str(item.depthPct) }],
    verdict: null,
  };
}

/** A product card from search (`prices` per shop, the pair's gap when one was asked). */
function searchCard(item: Rec): EvidenceCard | null {
  const id = str(item.id);
  const name = text(item.name);
  if (id === null || name === null || !isRec(item.prices)) return null;
  const prices: Record<string, Money | null> = {};
  for (const [r, m] of Object.entries(item.prices)) prices[r] = toMoney(m);
  const flags: Record<string, Schemas['PriceFlag']> = {};
  if (isRec(item.priceFlags))
    for (const [r, f] of Object.entries(item.priceFlags)) {
      const flag = priceFlag(f);
      if (flag) flags[r] = flag;
    }
  const gap = toPairGap(item.gap);
  const retailers = gap
    ? [gap.base, gap.other, ...Object.keys(prices).filter((r) => r !== gap.base && r !== gap.other)]
    : Object.keys(prices);
  if (retailers.length === 0) return null;
  return {
    id,
    name,
    brand: text(item.brand),
    category: strings(item.category)[0] ?? null,
    size: toSize(item.size),
    lines: retailers.map((r) => ({
      retailer: r,
      price: prices[r] ?? null,
      priceFlag: flags[r],
      notSold: !(r in prices),
      size: gap?.sizeLabels
        ? r === gap.base
          ? gap.sizeLabels[0]
          : r === gap.other
            ? gap.sizeLabels[1]
            : null
        : null,
    })),
    verdict: verdictOf({ gap, prices, priceFlags: flags }),
  };
}

/** The products in a tool result, by the tool's own shape; empty for tools without products. */
export function evidenceCards(env: ToolEnvelope): EvidenceCard[] {
  const data = env.data;
  if (!isRec(data)) return [];
  const cards: (EvidenceCard | null)[] = [];
  switch (env.citation.tool) {
    case 'compare': {
      const base = str(data.base);
      const other = str(data.other);
      if (base === null || other === null) return [];
      for (const row of list(data.rows)) if (isRec(row)) cards.push(compareCard(row, base, other));
      break;
    }
    case 'promotions':
      for (const item of list(data.items)) if (isRec(item)) cards.push(promoCard(item));
      break;
    case 'search_products':
      for (const item of list(data.items)) if (isRec(item)) cards.push(searchCard(item));
      break;
    case 'get_product':
      if (isRec(data.card)) cards.push(searchCard(data.card));
      break;
  }
  return cards.filter((c): c is EvidenceCard => c !== null).slice(0, MAX_CARDS);
}

/** A shop's share of priced products on promotion (the `promotions` tool's `retailers`). */
export interface EvidenceShare {
  readonly retailer: string;
  readonly n: number;
  readonly onPromo: number;
  /** The API's percentage text ("18.4"), or null when the shop's discounts are not measured. */
  readonly share: string | null;
  readonly reason: string | null;
}

export function evidenceShares(env: ToolEnvelope): EvidenceShare[] {
  const data = env.data;
  if (env.citation.tool !== 'promotions' || !isRec(data)) return [];
  const shares: EvidenceShare[] = [];
  for (const r of list(data.retailers)) {
    if (!isRec(r)) continue;
    const retailer = str(r.retailer);
    const n = num(r.n);
    const onPromo = num(r.onPromo);
    if (retailer === null || n === null || onPromo === null) continue;
    const share = str(r.share);
    shares.push({
      retailer,
      n,
      onPromo,
      share: share !== null && /^\d+(\.\d+)?$/.test(share) ? share : null,
      reason: str(r.reason),
    });
  }
  return shares.slice(0, MAX_TILES);
}

/** How many records the tool's list had in all (`total`), when it says. */
export function evidenceTotal(env: ToolEnvelope): number | null {
  return isRec(env.data) ? num(env.data.total) : null;
}

/** The page a citation opens, with the same filters the tool ran with. */
export interface SourceLink {
  readonly page: NavKey;
  readonly href: string;
  /** The retailer ids the tool was scoped to, in order (base first for a pair). */
  readonly retailers: readonly string[];
  readonly brand: readonly string[];
  readonly category: readonly string[];
  readonly groupBy: GroupBy | null;
}

const PAGE: Partial<Record<string, NavKey>> = {
  search_products: 'explore',
  get_product: 'explore',
  compare: 'compare',
  category_compare: 'compare',
  index_trend: 'prices',
  promotions: 'promotions',
  assortment_gaps: 'explore',
  launches: 'launches',
  reviews_summary: 'explore',
  coverage_status: 'dataset',
  price_history: 'explore',
  availability: 'explore',
  price_ladder: 'prices',
  price_distribution: 'prices',
  brand_positioning: 'prices',
  category_mix: 'overview',
  assortment_breadth: 'overview',
};

const filterList = (v: unknown): string[] =>
  Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string') : typeof v === 'string' ? [v] : [];
const filterStr = (v: unknown): string => (typeof v === 'string' ? v : '');

function pair(f: Readonly<Record<string, unknown>>): { base: string; other: string } | null {
  const r = f.retailers;
  if (typeof r !== 'object' || r === null) return null;
  const { base, other } = r as { base?: unknown; other?: unknown };
  return typeof base === 'string' && typeof other === 'string' ? { base, other } : null;
}

/** Where a citation's numbers can be seen on the pages; null for a tool the app has no page for. */
export function sourceLink(c: Citation, locale: string): SourceLink | null {
  const page = PAGE[c.tool];
  if (!page) return null;
  const f = c.filters;
  const brand = filterList(f.brand);
  const category = filterList(f.category);
  const groupBy: GroupBy | null = f.groupBy === 'brand' || f.groupBy === 'category' ? f.groupBy : null;
  const p = pair(f);
  const base = { page, brand, category, groupBy };
  switch (c.tool) {
    case 'compare':
    case 'index_trend':
    case 'category_compare': {
      const by = c.tool === 'category_compare' ? 'category' : groupBy;
      const href =
        page === 'compare'
          ? `/${locale}/compare/${toCompareSearch({ ...EMPTY_COMPARE, ...p, groupBy: by, brand, category })}`
          : navHref(page, locale);
      return { ...base, groupBy: by, retailers: p ? [p.base, p.other] : [], href };
    }
    case 'promotions': {
      const retailers = filterList(f.retailer);
      const min = typeof f.minPct === 'number' ? String(f.minPct) : '';
      const minPct = (MIN_PCTS as readonly string[]).includes(min) ? (min as MinPct) : '';
      return {
        ...base,
        retailers,
        href: `/${locale}/promotions/${toPromotionsSearch({ ...EMPTY_PROMOTIONS, retailer: [...retailers], brand, category, minPct })}`,
      };
    }
    case 'get_product': {
      const id = filterStr(f.id);
      return {
        ...base,
        retailers: [],
        href: id ? `/${locale}/product/?id=${encodeURIComponent(id)}` : navHref(page, locale),
      };
    }
    case 'search_products':
    case 'reviews_summary':
    case 'price_history':
    case 'availability': {
      const retailers = filterList(f.retailer);
      const matched = f.matched === true ? 'yes' : f.matched === false ? 'no' : 'any';
      return {
        ...base,
        retailers,
        href: `/${locale}/explore/${toSearch({
          ...EMPTY,
          q: filterStr(f.q),
          brand,
          category,
          retailer: retailers,
          matched,
          priceMin: filterStr(f.priceMin),
          priceMax: filterStr(f.priceMax),
        })}`,
      };
    }
    case 'assortment_gaps': {
      const present = filterStr(f.presentAt);
      const retailers = present ? [present] : [];
      return {
        ...base,
        retailers,
        href: `/${locale}/explore/${toSearch({ ...EMPTY, brand, category, retailer: retailers })}`,
      };
    }
    default:
      return { ...base, retailers: filterList(f.retailer), href: navHref(page, locale) };
  }
}
