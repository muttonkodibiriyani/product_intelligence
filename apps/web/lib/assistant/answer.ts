import type { ChatProgress, Sanitised } from './types';
import { isUntrusted, plain } from './types';

/** Which user-facing note an unavailable answer gets (meter refusals and flow codes). */
export type UnavailableNote = 'off' | 'questionCap' | 'spendCap' | 'invalid' | 'tooLong' | 'generic';

export function unavailableNote(code: string | undefined): UnavailableNote {
  switch (code) {
    case 'disabled':
      return 'off';
    case 'question_cap':
      return 'questionCap';
    case 'month_cap':
    case 'label_month_cap':
    case 'label_day_cap':
      return 'spendCap';
    case 'invalid_question':
      return 'invalid';
    case 'prompt_too_large':
      return 'tooLong';
    default:
      return 'generic';
  }
}

export const TOOL_NAMES = [
  'search_products',
  'get_product',
  'compare',
  'category_compare',
  'index_trend',
  'promotions',
  'assortment_gaps',
  'launches',
  'reviews_summary',
  'coverage_status',
  'price_history',
  'availability',
  'price_ladder',
  'price_distribution',
  'brand_positioning',
  'category_mix',
  'assortment_breadth',
] as const;

export type ToolName = (typeof TOOL_NAMES)[number];

export const isToolName = (name: string): name is ToolName =>
  (TOOL_NAMES as readonly string[]).includes(name);

/** The label key for a tool name; `summary` is the page's own sample source (/api/v1/summary). */
export const toolKey = (name: string): ToolName | 'summary' | 'other' =>
  isToolName(name) || name === 'summary' ? name : 'other';

/** Progress chips: one per stage or tool call, in arrival order. */
export const progressKey = (p: ChatProgress, i: number): string =>
  p.type === 'status' ? `s-${p.stage}-${i}` : `t-${p.name}-${i}`;

export interface Table {
  readonly columns: readonly string[];
  readonly rows: readonly (readonly string[])[];
  readonly total: number;
}

export const MAX_TABLE_ROWS = 25;
const MAX_COLUMNS = 8;

const cell = (value: Sanitised | undefined): string | null => {
  if (value === null || value === undefined) return '—';
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean')
    return String(value);
  if (isUntrusted(value)) return plain(value);
  return null;
};

/**
 * A plain table from the first list of records in a tool result, for the unverified fallback
 * (the server's raw tool results). Only scalar and untrusted-text columns; nested values are left
 * out. Null when the result has no such list.
 */
export function firstTable(data: Sanitised | undefined): Table | null {
  const list = findList(data, 0);
  if (!list) return null;
  const records = list.filter(
    (row): row is { [key: string]: Sanitised } =>
      typeof row === 'object' && row !== null && !Array.isArray(row) && !isUntrusted(row),
  );
  const columns: string[] = [];
  for (const row of records)
    for (const [key, value] of Object.entries(row))
      if (!columns.includes(key) && cell(value) !== null && columns.length < MAX_COLUMNS) columns.push(key);
  if (columns.length === 0) return null;
  return {
    columns,
    rows: records.slice(0, MAX_TABLE_ROWS).map((row) => columns.map((c) => cell(row[c]) ?? '—')),
    total: records.length,
  };
}

function findList(data: Sanitised | undefined, depth: number): Sanitised[] | null {
  if (depth > 3 || data === null || data === undefined || typeof data !== 'object') return null;
  if (Array.isArray(data)) return data.length > 0 ? data : null;
  if (isUntrusted(data)) return null;
  for (const value of Object.values(data)) {
    const found = findList(value, depth + 1);
    if (found) return found;
  }
  return null;
}
