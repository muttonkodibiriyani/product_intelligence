import type { QueryOf } from './api/types';
import { EVIDENCE_STATES, type LaunchEvidenceFilters, type LaunchEvidenceState } from './launch-evidence';
import { cleanList, type Limit, LIMITS, parseLimit } from './url-state';

export type LaunchesQuery = QueryOf<'/api/v1/launches'>;

/** The windows the page offers: new in the last 30 days (the default) or the last 7. */
export const WINDOWS = [30, 7] as const;
export type Window = (typeof WINDOWS)[number];

/** The launches view, all in the URL. */
export interface LaunchesState extends LaunchEvidenceFilters {
  /** How many days back from the dataset's cutoff the list reaches. */
  days: Window;
  limit: Limit;
}

export const EMPTY_LAUNCHES: LaunchesState = {
  days: WINDOWS[0],
  retailer: [],
  brand: [],
  category: [],
  dateFrom: '',
  dateTo: '',
  priceMin: '',
  priceMax: '',
  discountMin: '',
  availability: [],
  size: '',
  color: '',
  shade: '',
  evidence: [],
  limit: LIMITS[0],
};

export function parseWindow(v: string | null): Window {
  const n = Number(v);
  return (WINDOWS as readonly number[]).includes(n) ? (n as Window) : WINDOWS[0];
}

export function parseLaunches(sp: URLSearchParams): LaunchesState {
  return {
    days: parseWindow(sp.get('days')),
    retailer: cleanList(sp.getAll('retailer')),
    brand: cleanList(sp.getAll('brand')),
    category: cleanList(sp.getAll('category')),
    dateFrom: cleanDate(sp.get('dateFrom')),
    dateTo: cleanDate(sp.get('dateTo')),
    priceMin: cleanNumber(sp.get('priceMin')),
    priceMax: cleanNumber(sp.get('priceMax')),
    discountMin: cleanNumber(sp.get('discountMin')),
    availability: cleanList(sp.getAll('availability')),
    size: cleanTerm(sp.get('size')),
    color: cleanTerm(sp.get('color')),
    shade: cleanTerm(sp.get('shade')),
    evidence: cleanList(sp.getAll('evidence')).filter((value): value is LaunchEvidenceState =>
      (EVIDENCE_STATES as readonly string[]).includes(value),
    ),
    limit: parseLimit(sp.get('limit')),
  };
}

export function toLaunchesSearch(s: LaunchesState): string {
  const p = new URLSearchParams();
  for (const k of ['retailer', 'brand', 'category', 'availability', 'evidence'] as const)
    for (const v of s[k]) p.append(k, v);
  for (const k of [
    'dateFrom',
    'dateTo',
    'priceMin',
    'priceMax',
    'discountMin',
    'size',
    'color',
    'shade',
  ] as const)
    if (s[k]) p.set(k, s[k]);
  if (s.days !== WINDOWS[0]) p.set('days', String(s.days));
  if (s.limit !== LIMITS[0]) p.set('limit', String(s.limit));
  const out = p.toString();
  return out ? `?${out}` : '';
}

const DAY = /^\d{4}-\d{2}-\d{2}$/;
const NUMBER = /^\d{1,9}(?:\.\d{1,3})?$/;

const cleanDate = (value: string | null) => (value && DAY.test(value) ? value : '');
const cleanNumber = (value: string | null) => (value && NUMBER.test(value) ? value : '');
const cleanTerm = (value: string | null) => {
  const term = value?.trim() ?? '';
  return term.length <= 120 ? term : '';
};

/**
 * The day the window ends on: the dataset's last collection day, a market date. The cutoff is an
 * instant in UTC, and after 20:00Z its UTC date is the day before the market's (UTC+4), which
 * would stretch "the last 30 days" to 31; it is only the fallback when /meta lists no days.
 */
export function windowEnd(meta: { cutoff: string; dates: readonly string[] }): string {
  const last = meta.dates.at(-1) ?? '';
  return DAY.test(last) ? last : meta.cutoff.slice(0, 10);
}

/**
 * The first day of a window ending on `end` (YYYY-MM-DD): the last 30 days are that day and the
 * 29 before it. '' when `end` is not a date the API would accept.
 */
export function windowSince(end: string, days: Window): string {
  const day = end.slice(0, 10);
  if (!DAY.test(day)) return '';
  const d = new Date(`${day}T00:00:00Z`);
  if (Number.isNaN(d.getTime())) return '';
  d.setUTCDate(d.getUTCDate() - (days - 1));
  return d.toISOString().slice(0, 10);
}

/** Always with a limit: only then does the API send the newest first and say when it cut. */
export function toLaunchesQuery(s: LaunchesState, end: string): LaunchesQuery {
  const since = windowSince(end, s.days);
  return {
    ...(since ? { since } : {}),
    ...(s.retailer.length ? { retailer: s.retailer } : {}),
    ...(s.brand.length ? { brand: s.brand } : {}),
    ...(s.category.length ? { category: s.category } : {}),
    limit: s.limit,
  };
}
