import type { Schemas } from './api/types';
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
