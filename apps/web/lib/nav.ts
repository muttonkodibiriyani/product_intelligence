/**
 * The app's pages: their routes, which one is current, and when each shows in the navigation.
 * Pure, so the rules are unit-tested; `components/use-nav.ts` feeds it the live signals.
 */
export const NAV_KEYS = [
  'overview',
  'explore',
  'compare',
  'promotions',
  'launches',
  'prices',
  'dataset',
  'assistant',
] as const;
export type NavKey = (typeof NAV_KEYS)[number];

/** The five on a phone's tab bar; the rest sit behind the phone menu. */
export const TABBAR_KEYS = ['overview', 'explore', 'compare', 'promotions', 'assistant'] as const;

/** The first item of the nav's second group (the data and the assistant), drawn under a rule. */
export const NAV_SECTION_BREAK: NavKey = 'dataset';

const PATH: Record<NavKey, string> = {
  overview: '',
  explore: 'explore/',
  compare: 'compare/',
  promotions: 'promotions/',
  launches: 'launches/',
  prices: 'prices/',
  // The Dataset section lives on the Overview until it has a page of its own.
  dataset: '#dataset',
  assistant: 'assistant/',
};

export const navHref = (key: NavKey, locale: string): string => `/${locale}/${PATH[key]}`;

/** Where "About the data" points: the Dataset section. */
export const datasetHref = (locale: string): string => navHref('dataset', locale);

const MATCH: Record<NavKey, RegExp | null> = {
  overview: /^\/(en|ar)\/?$/,
  explore: /^\/(en|ar)\/(explore|product)\//,
  compare: /^\/(en|ar)\/compare\//,
  promotions: /^\/(en|ar)\/promotions\//,
  launches: /^\/(en|ar)\/launches\//,
  prices: /^\/(en|ar)\/prices\//,
  // An anchor on the Overview, so never the current page itself.
  dataset: null,
  assistant: /^\/(en|ar)\/assistant\//,
};

export const navMatches = (key: NavKey, pathname: string): boolean => MATCH[key]?.test(pathname) ?? false;

/** What the data says about each page; a field is undefined until its request has answered. */
export interface NavSignals {
  /** `priced` from each retailer's /summary. */
  priced?: readonly (number | null)[];
  /** Any retailer whose discounts /summary measures (a share without a withheld reason). */
  promoMeasured?: boolean;
  /** Collection days in the dataset (/meta `dates`). */
  collectionDays?: number;
  /** Any retailer that is a one-off import rather than a daily collection. */
  oneOff?: boolean;
}

export type NavState = 'shown' | 'hidden' | 'soon';

/**
 * Overview, Compare, Dataset and the assistant always show (Compare carries its own empty state).
 * Products and Prices need a retailer with priced products; Promotions a retailer whose discounts
 * are measured. Launches needs two collection days from every retailer: until the API counts days
 * per retailer, the dataset's day count stands in, and a one-off import counts as one day. While a
 * signal is unknown (still loading, or the request failed) the page stays reachable.
 */
export function navState(key: NavKey, s: NavSignals): NavState {
  switch (key) {
    case 'explore':
    case 'prices':
      return s.priced === undefined || s.priced.some((n) => (n ?? 0) > 0) ? 'shown' : 'hidden';
    case 'promotions':
      return s.promoMeasured === false ? 'hidden' : 'shown';
    case 'launches':
      if (s.collectionDays === undefined && s.oneOff === undefined) return 'shown';
      return (s.collectionDays ?? 2) >= 2 && !s.oneOff ? 'shown' : 'soon';
    default:
      return 'shown';
  }
}
