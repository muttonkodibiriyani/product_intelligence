import type { Schemas } from './api/types';
import { formatCount } from './format';
import { apiAtLeast } from './insights';

export type Findings = Schemas['Findings'];
export type Finding = Schemas['Finding'];
export type FindingKey = Schemas['FindingKey'];
export type Param = Schemas['Param'];
export type Chart = Schemas['Chart'];
export type ChartRow = Schemas['ChartRow'];
export type Example = Schemas['Example'];

/** The first API version that serves GET /api/v1/findings. */
export const FINDINGS_API = '1.23.0';

export const findingsServed = (apiVersion: string | undefined): boolean | undefined =>
  apiVersion === undefined ? undefined : apiAtLeast(apiVersion, FINDINGS_API);

/** The page's themes, top to bottom; every finding sits in exactly one (design, 6 Oct). */
export const THEMES = ['assortment', 'price', 'promo', 'stock', 'reviews', 'dq'] as const;
export type Theme = (typeof THEMES)[number];

export const THEME_OF: Readonly<Record<FindingKey, Theme>> = {
  brand_white_space: 'assortment',
  brand_depth_gaps: 'assortment',
  brand_price_policy: 'price',
  size_level_gaps: 'price',
  fragrance_ladder: 'price',
  size_traps: 'price',
  positioning: 'price',
  promo_strategy: 'promo',
  real_discounts: 'promo',
  stock: 'stock',
  price_vs_rating: 'reviews',
  pricing_anomalies: 'dq',
};

/** The findings by theme, in theme order; within a theme, by the API's rank. Empty themes drop. */
export function byTheme(findings: readonly Finding[]): [Theme, Finding[]][] {
  return THEMES.map((t): [Theme, Finding[]] => [
    t,
    findings.filter((f) => THEME_OF[f.key] === t).sort((a, b) => a.rank - b.rank),
  ]).filter(([, fs]) => fs.length > 0);
}

/** The DOM id a summary tile jumps to. */
export const findingId = (key: FindingKey): string => `finding-${key.replaceAll('_', '-')}`;

/** Examples shown per card (the API sends at most four). */
export const EXAMPLES_SHOWN = 4;

/** A decimal string's sign written with a true minus, so −8.7 does not read as a hyphen. */
export const signed = (v: string, plus = false): string =>
  v.startsWith('-') ? `−${v.slice(1)}` : plus && Number(v) > 0 ? `+${v}` : v;

/** The largest absolute chart value, at least `floor` so an all-zero chart still draws. */
export const scale = (rows: readonly ChartRow[], floor = 1): number =>
  Math.max(floor, ...rows.map((r) => Math.abs(Number(r.value))));

/** A bar's length (0–100) at `max`; a non-zero value never shrinks to nothing. */
export function barWidth(value: string, max: number): number {
  const v = Math.abs(Number(value));
  if (!(max > 0) || v === 0) return 0;
  return Math.max(1, Math.min(100, (v / max) * 100));
}

/** A strip's axis: every dot across rows, padded to include zero. */
export function stripAxis(rows: readonly ChartRow[]): { min: number; max: number } {
  const xs = rows.flatMap((r) => r.parts.map(Number));
  const min = Math.min(0, ...xs);
  const max = Math.max(0, ...xs);
  return max > min ? { min, max } : { min: min - 1, max: max + 1 };
}

/** Where a value sits on a strip's axis, 0–100. */
export const stripPos = (v: number, axis: { min: number; max: number }): number =>
  ((v - axis.min) / (axis.max - axis.min)) * 100;

/** A matrix cell's tint (0.06–1) against the largest cell. */
export function cellShade(v: string, rows: readonly ChartRow[]): number {
  const max = Math.max(1, ...rows.flatMap((r) => r.parts.map(Number)));
  return 0.06 + (0.94 * Number(v)) / max;
}

/** How the page names what a param holds: a shop by its display name, a category in the locale. */
export type Namers = {
  shop: (id: string) => string;
  category: (code: string) => string;
};

/** Items joined the way the locale lists them ("A, B and C" / "A وB وC"). */
export const list = (items: readonly string[], locale: string): string =>
  new Intl.ListFormat(locale === 'ar' ? 'ar' : 'en', { style: 'long', type: 'conjunction' }).format(items);

/**
 * An amount in a sentence or on an axis: whole amounts without decimals ("AED 50", as a shopper
 * reads a price band), any other amount to the fils, in Latin digits.
 */
export function moneyText(amount: string, currency: string, locale: string): string {
  const whole = /^-?\d+(\.0+)?$/.test(amount);
  return new Intl.NumberFormat(locale === 'ar' ? 'ar-AE' : 'en-AE', {
    style: 'currency',
    currency,
    numberingSystem: 'latn',
    minimumFractionDigits: whole ? 0 : 2,
    maximumFractionDigits: whole ? 0 : 2,
  }).format(amount as Intl.StringNumericLiteral);
}

/** One param as message text: counts and money in Latin digits, a true minus, names not ids. */
export function paramText(p: Param, locale: string, names: Namers): string {
  switch (p.kind) {
    case 'count':
      return formatCount(Number(p.value), locale);
    case 'pct':
      return `${signed(p.value)}%`;
    case 'ratio':
      return signed(p.value);
    case 'money':
      return p.currency ? moneyText(p.value, p.currency, locale) : p.value;
    case 'retailer':
      return names.shop(p.value);
    case 'category':
      return names.category(p.value);
    case 'list':
      return list(p.items, locale);
    case 'text':
      return p.value;
    case 'missing':
      return '';
  }
}

/**
 * Every param as a message argument, plus `has_<name>` ('yes'/'no': present, and for a list not
 * empty) and `zero_<name>` for numbers, so a message words a missing or zero value explicitly
 * instead of printing a blank.
 */
export function messageArgs(f: Finding, locale: string, names: Namers): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [k, p] of Object.entries(f.params)) {
    out[k] = paramText(p, locale, names);
    const present = p.kind === 'list' ? p.items.length > 0 : p.kind !== 'missing';
    out[`has_${k}`] = present ? 'yes' : 'no';
    if (p.kind === 'count' || p.kind === 'pct' || p.kind === 'ratio')
      out[`zero_${k}`] = Number(p.value) === 0 ? 'yes' : 'no';
  }
  return out;
}

/**
 * The arguments a message names that the finding did not send, filled so an optional part reads
 * its "other" branch instead of failing: `has_x`/`zero_x` → 'no', anything else → ''. A finding
 * leaves a param out when there is nothing to say (no third shop, no lead brand).
 */
export function fillArgs(message: string, args: Record<string, string>): Record<string, string> {
  const out = { ...args };
  for (const [, name] of message.matchAll(/\{(\w+)[},]/g)) {
    if (name !== undefined && !(name in out)) out[name] = /^(has|zero)_/.test(name) ? 'no' : '';
  }
  return out;
}

/** A headline's words (KPI included), the design's limit being twelve. */
export const words = (text: string): number => text.trim().split(/\s+/).filter(Boolean).length;
export const HEADLINE_WORDS = 12;
