/**
 * What an answer shows beside its text, read from the tool results the server already
 * sanitised (`ToolEnvelope.data`): products as cards, per-shop shares as tiles, and one source
 * pill per citation that opens the page with the same filters. Every value here is the API's,
 * through the assistant's tools; nothing is computed from the model's prose. Untrusted text
 * (names, brands) is unwrapped with `plain()` and only ever rendered as text.
 */
import type { Money, Schemas } from '@/lib/api/types';
import { EMPTY_COMPARE, type GroupBy, toCompareSearch } from '@/lib/compare';
import { EMPTY, type ProductSort, SORTS, toSearch } from '@/lib/explore';
import { EMPTY_LAUNCHES, toLaunchesSearch } from '@/lib/launches';
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

/**
 * Where a citation's numbers can be seen. `href` is set only when every scoping argument the tool
 * ran with maps exactly onto a URL parameter the page reads, so the pill never opens a broader
 * view than it names; otherwise the pill is plain text. `page` is the page that would show it.
 */
export interface SourceLink {
  readonly page: NavKey | null;
  readonly href: string | null;
  /** The retailer ids the tool was scoped to, in order (base first for a pair). */
  readonly retailers: readonly string[];
  readonly brand: readonly string[];
  readonly category: readonly string[];
  readonly groupBy: GroupBy | null;
}

type Filters = Readonly<Record<string, unknown>>;

/** Arguments that size the result rather than scope it; the page has its own page size. */
const SIZING = new Set(['limit']);

const isSet = (v: unknown): boolean => v !== undefined && v !== null && !(Array.isArray(v) && v.length === 0);
const filterList = (v: unknown): string[] =>
  Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string') : typeof v === 'string' ? [v] : [];
const filterStr = (v: unknown): string => (typeof v === 'string' ? v : '');

/** True when the tool ran with a scoping argument outside `allowed`: the page cannot show the same. */
const beyond = (f: Filters, allowed: readonly string[]): boolean =>
  Object.keys(f).some((k) => isSet(f[k]) && !SIZING.has(k) && !allowed.includes(k));

function pair(f: Filters): { base: string; other: string } | null {
  const r = f.retailers;
  if (typeof r !== 'object' || r === null) return null;
  const { base, other } = r as { base?: unknown; other?: unknown };
  return typeof base === 'string' && typeof other === 'string' ? { base, other } : null;
}

const productHref = (locale: string, id: string) => `/${locale}/product/?id=${encodeURIComponent(id)}`;

/** The source pill's page and link for a citation; `href` null when no page shows exactly that scope. */
export function sourceLink(c: Citation, locale: string): SourceLink {
  const f = c.filters;
  const brand = filterList(f.brand);
  const category = filterList(f.category);
  const groupBy: GroupBy | null = f.groupBy === 'brand' || f.groupBy === 'category' ? f.groupBy : null;
  const p = pair(f);
  const retailers = p ? [p.base, p.other] : filterList(f.retailer);
  const base = { page: null, href: null, retailers, brand, category, groupBy };
  switch (c.tool) {
    case 'compare': {
      // Compare reads the pair, the grouping and brand/category; not product ids nor a date.
      const page = 'compare';
      if (!p || beyond(f, ['retailers', 'brand', 'category', 'groupBy'])) return { ...base, page };
      const href = `/${locale}/compare/${toCompareSearch({ ...EMPTY_COMPARE, ...p, groupBy, brand, category })}`;
      return { ...base, page, href };
    }
    case 'category_compare': {
      // Compare by category is the API's bucket level; the common level has no page.
      const page = 'compare';
      const level = f.level === undefined || f.level === 'bucket';
      if (!p || !level || beyond(f, ['retailers', 'level'])) return { ...base, page, groupBy: 'category' };
      const href = `/${locale}/compare/${toCompareSearch({ ...EMPTY_COMPARE, ...p, groupBy: 'category' })}`;
      return { ...base, page, groupBy: 'category', href };
    }
    case 'promotions': {
      // Promotions reads shops, brand/category and the preset depths only; not a date.
      const page = 'promotions';
      const min = typeof f.minPct === 'number' ? String(f.minPct) : '';
      const preset = (MIN_PCTS as readonly string[]).includes(min);
      if (!preset || beyond(f, ['retailer', 'brand', 'category', 'minPct'])) return { ...base, page };
      const minPct = min as MinPct;
      const href = `/${locale}/promotions/${toPromotionsSearch({ ...EMPTY_PROMOTIONS, retailer: retailers, brand, category, minPct })}`;
      return { ...base, page, href };
    }
    case 'launches': {
      // Launches reads brand/category and a preset window; not a shop nor a since date.
      const page = 'launches';
      if (beyond(f, ['brand', 'category'])) return { ...base, page };
      return {
        ...base,
        page,
        href: `/${locale}/launches/${toLaunchesSearch({ ...EMPTY_LAUNCHES, brand, category })}`,
      };
    }
    case 'search_products': {
      // Products reads every argument of the search tool.
      const page = 'explore';
      const sort = filterStr(f.sort);
      const sortOk = sort === '' || SORTS.includes(sort as ProductSort);
      const allowed = ['q', 'brand', 'category', 'retailer', 'matched', 'priceMin', 'priceMax', 'sort'];
      if (!sortOk || beyond(f, allowed)) return { ...base, page };
      const matched = f.matched === true ? 'yes' : f.matched === false ? 'no' : 'any';
      const href = `/${locale}/explore/${toSearch({
        ...EMPTY,
        q: filterStr(f.q),
        brand,
        category,
        retailer: retailers,
        matched,
        priceMin: filterStr(f.priceMin),
        priceMax: filterStr(f.priceMax),
        sort: sort === '' ? EMPTY.sort : (sort as ProductSort),
      })}`;
      return { ...base, page, href };
    }
    case 'reviews_summary': {
      // One product id opens that product; a list of ids has no page. Filters open Products.
      const page = 'explore';
      const ids = filterList(f.ids);
      if (ids.length > 0) {
        if (ids.length === 1 && !beyond(f, ['ids']))
          return { ...base, page, href: productHref(locale, ids[0]!) };
        return { ...base, page };
      }
      if (beyond(f, ['brand', 'category', 'retailer'])) return { ...base, page };
      return {
        ...base,
        page,
        href: `/${locale}/explore/${toSearch({ ...EMPTY, brand, category, retailer: retailers })}`,
      };
    }
    case 'get_product':
    case 'price_history': {
      // The product page; a history window (from/to) is not a view the page offers.
      const page = 'explore';
      const id = filterStr(f.id);
      if (!id || beyond(f, ['id'])) return { ...base, page };
      return { ...base, page, href: productHref(locale, id) };
    }
    case 'coverage_status': {
      // Dataset shows every shop; a shop subset has no page of its own.
      const page = 'dataset';
      if (beyond(f, [])) return { ...base, page };
      return { ...base, page, href: navHref(page, locale) };
    }
    case 'price_ladder':
    case 'price_distribution':
    case 'brand_positioning': {
      // Prices shows one named shop; without the argument the tool and the page pick their own defaults.
      const page = 'prices';
      const r = filterStr(f.retailer);
      if (!r || beyond(f, ['retailer'])) return { ...base, page };
      return { ...base, page, href: `${navHref(page, locale)}?${new URLSearchParams({ retailer: r })}` };
    }
    // No page shows these views at the tool's scope: the pill names the tool, unlinked.
    case 'index_trend':
    case 'assortment_gaps':
    case 'availability':
    case 'category_mix':
    case 'assortment_breadth':
    default:
      return base;
  }
}
