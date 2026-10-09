import type { InsightKey } from '../home/insights';

/** The dashboard's preset views, in the order the switch lists them; the first is the default. */
export const VIEW_KEYS = ['lead', 'price', 'promo', 'range'] as const;
export type ViewKey = (typeof VIEW_KEYS)[number];

/**
 * What each view draws, top to bottom, from sections that already read the metric API. A view
 * names no chart the API does not publish: stock-outs, the promotion calendar and pack sizes are
 * left out until there is a metric behind them.
 */
export interface View {
  /** Each shop's tiles: catalogue, promotions, launches. */
  band: boolean;
  /** The one line on the matched products. */
  headline: boolean;
  /** The pair on the matched set: the head-to-head numbers and the spread of gaps. */
  headToHead: boolean;
  /** The pair by shared category over both full catalogues. */
  byCategory: boolean;
  /** The charts, from the Overview's set. */
  insights: readonly InsightKey[];
  /** Each shop's deepest verified discounts. */
  topDiscounts: boolean;
}

export const VIEWS: Record<ViewKey, View> = {
  lead: {
    band: true,
    headline: true,
    headToHead: false,
    byCategory: false,
    insights: ['gaps', 'index', 'launches'],
    topDiscounts: false,
  },
  price: {
    band: false,
    headline: false,
    headToHead: true,
    byCategory: true,
    insights: ['index', 'hist', 'ladder', 'brands'],
    topDiscounts: false,
  },
  promo: {
    band: true,
    headline: false,
    headToHead: false,
    byCategory: false,
    insights: ['depth'],
    topDiscounts: true,
  },
  range: {
    band: true,
    headline: false,
    headToHead: false,
    byCategory: false,
    insights: ['share', 'brands', 'launches'],
    topDiscounts: false,
  },
};

/** The view a `?view=` value names; anything else is the default. */
export const viewFrom = (v: string | null): ViewKey =>
  (VIEW_KEYS as readonly string[]).includes(v ?? '') ? (v as ViewKey) : VIEW_KEYS[0];
