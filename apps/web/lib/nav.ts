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
  dataset: 'dataset/',
  assistant: 'assistant/',
};

export const navHref = (key: NavKey, locale: string): string => `/${locale}/${PATH[key]}`;

/** The Dataset page. */
export const datasetHref = (locale: string): string => navHref('dataset', locale);

/** Where every "About the data" link points: the plain-words section on the Dataset page. */
export const aboutDataHref = (locale: string): string => `${datasetHref(locale)}#about-data`;

const MATCH: Record<NavKey, RegExp | null> = {
  overview: /^\/(en|ar)\/?$/,
  explore: /^\/(en|ar)\/(explore|product)\//,
  compare: /^\/(en|ar)\/compare\//,
  promotions: /^\/(en|ar)\/promotions\//,
  launches: /^\/(en|ar)\/launches\//,
  prices: /^\/(en|ar)\/prices\//,
  dataset: /^\/(en|ar)\/dataset\//,
  assistant: /^\/(en|ar)\/assistant\//,
};

export const navMatches = (key: NavKey, pathname: string): boolean => MATCH[key]?.test(pathname) ?? false;

/** What the data says about each page; a field is undefined until its request has answered. */
export interface NavSignals {
  /** `priced` from each retailer's /summary. */
  priced?: readonly (number | null)[];
  /** Any retailer whose discounts /summary measures (a share without a withheld reason). */
  promoMeasured?: boolean;
  /**
   * Every shop has the collection days launches need (`components/launches/readiness.ts`,
   * from /meta); false while any shop is short of them.
   */
  launchesReady?: boolean;
}

export type NavState = 'shown' | 'hidden' | 'soon';

/**
 * Overview, Compare, Dataset and the assistant always show (Compare carries its own empty state).
 * Products and Prices need a retailer with priced products; Promotions a retailer whose discounts
 * are measured. Launches stays reachable but reads "soon" until every retailer has the collection
 * days a launch needs. While a signal is unknown (still loading, or the request failed) the page
 * stays reachable with nothing said.
 */
export function navState(key: NavKey, s: NavSignals): NavState {
  switch (key) {
    case 'explore':
    case 'prices':
      return s.priced === undefined || s.priced.some((n) => (n ?? 0) > 0) ? 'shown' : 'hidden';
    case 'promotions':
      return s.promoMeasured === false ? 'hidden' : 'shown';
    case 'launches':
      return s.launchesReady === false ? 'soon' : 'shown';
    default:
      return 'shown';
  }
}
