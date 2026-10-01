import type { QueryOf, Schemas } from './api/types';

export type CompareQuery = QueryOf<'/api/v1/compare'>;
export type GroupBy = Schemas['GroupBy'];

const GROUP_BYS: readonly GroupBy[] = ['brand', 'category'];
/** Rows asked for: the API sends the largest gaps first and says when the list was cut. */
export const LIMITS = [100, 500] as const;
export type Limit = (typeof LIMITS)[number];
const MAX_VALUES = 25;
const MAX_LEN = 120;
/** A retailer id as the API accepts it. */
const RETAILER = /^[a-z][a-z0-9_]{1,62}$/;

/**
 * A comparison is described by the URL: the pair (base first), the grouping, the filters and how
 * many rows to show. `base` and `other` are empty until both are picked.
 */
export interface CompareState {
  base: string;
  other: string;
  groupBy: GroupBy | null;
  brand: string[];
  category: string[];
  limit: Limit;
}

export const EMPTY_COMPARE: CompareState = {
  base: '',
  other: '',
  groupBy: null,
  brand: [],
  category: [],
  limit: LIMITS[0],
};

const list = (vs: string[]) =>
  [...new Set(vs.map((v) => v.trim()).filter((v) => v && v.length <= MAX_LEN))].slice(0, MAX_VALUES);

export const hasComparePair = (s: Pick<CompareState, 'base' | 'other'>) => !!s.base && !!s.other;

/** Reads the URL leniently: a pair that isn't two different retailer ids is dropped. */
export function parseCompare(sp: URLSearchParams): CompareState {
  const [base = '', other = '', ...rest] = (sp.get('retailers') ?? '').split(',');
  const pair = rest.length === 0 && RETAILER.test(base) && RETAILER.test(other) && base !== other;
  const groupBy = sp.get('groupBy') as GroupBy | null;
  const limit = Number(sp.get('limit'));
  return {
    base: pair ? base : '',
    other: pair ? other : '',
    groupBy: groupBy && GROUP_BYS.includes(groupBy) ? groupBy : null,
    brand: list(sp.getAll('brand')),
    category: list(sp.getAll('category')),
    limit: (LIMITS as readonly number[]).includes(limit) ? (limit as Limit) : LIMITS[0],
  };
}

/** The URL query for a state; defaults are left out. */
export function toCompareSearch(s: CompareState): string {
  const p = new URLSearchParams();
  if (hasComparePair(s)) p.set('retailers', `${s.base},${s.other}`);
  if (s.groupBy) p.set('groupBy', s.groupBy);
  for (const k of ['brand', 'category'] as const) for (const v of s[k]) p.append(k, v);
  if (s.limit !== LIMITS[0]) p.set('limit', String(s.limit));
  const out = p.toString();
  return out ? `?${out}` : '';
}

export function toCompareQuery(s: CompareState): CompareQuery {
  return {
    retailers: `${s.base},${s.other}`,
    ...(s.groupBy ? { groupBy: s.groupBy } : {}),
    ...(s.brand.length ? { brand: s.brand } : {}),
    ...(s.category.length ? { category: s.category } : {}),
    limit: s.limit,
  };
}

/** Picking a retailer that is already the other side swaps the pair instead of emptying it. */
export function pick(s: CompareState, side: 'base' | 'other', id: string): CompareState {
  const flip = side === 'base' ? 'other' : 'base';
  if (id && id === s[flip]) return { ...s, [side]: id, [flip]: s[side] };
  return { ...s, [side]: id };
}
