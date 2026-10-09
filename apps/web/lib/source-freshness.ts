import type { CaveatView, Schemas } from './api/types';

type Meta = Pick<Schemas['MetaView'], 'dates' | 'retailers' | 'sources'>;
type Card = Pick<
  Schemas['ProductCard'],
  'brand' | 'category' | 'image' | 'name' | 'prices' | 'priceFlags' | 'size' | 'sizeLabel'
>;

/**
 * How current one retailer's own source is, read only from the API's own dates (ADR-0010): a
 * source is stale when its last observation date is before the view's last date, exactly as the
 * API composes it. The browser clock is never consulted.
 *
 * - `fresh`: the source's own last date is the view's last date ("latest in this dataset", not
 *   "today").
 * - `stale`: an older last date, or the API's `stale_source` caveat names it.
 * - `unavailable`: the retailer's status is blocked, pending or retired.
 * - `not_observed`: the retailer is listed but no source of that exact id was sent.
 * - `conflict`: two sources (or a source and its caveat) disagree about its last date.
 * - `invalid`: a malformed date, or a last date after the view's own.
 * - `mixed`: the last date is the view's, but the API says part of the source is an imported
 *   snapshot (`snapshot_import_date`). A list row carries no per-offer date, so a retained older
 *   offer cannot be told apart from a current one and the source is never shown as `fresh`.
 */
export const EVIDENCE_STATES = [
  'fresh',
  'stale',
  'unavailable',
  'not_observed',
  'conflict',
  'invalid',
  'mixed',
] as const;
export type EvidenceState = (typeof EVIDENCE_STATES)[number];

export interface SourceFreshness {
  retailer: string;
  state: EvidenceState;
  /** The source's own last observation date when exactly one valid value was sent. */
  lastDate: string | null;
  /** The view's last date the source is compared with. */
  viewDate: string | null;
  /** Products the source has an offer for, as /meta counts them; null when not sent. */
  products: number | null;
  /** The retailer's own status in /meta (partial is kept beside the state, never hidden). */
  status: Schemas['RetailerStatus'] | null;
  /** The API's snapshot import date for an imported retailer: its capture time is unknown. */
  importedOn: string | null;
  /** Field statuses the source declares, counted by status (for later attribute coverage). */
  fields: Partial<Record<Schemas['FieldStatus'], number>>;
}

const UNAVAILABLE: readonly Schemas['RetailerStatus'][] = ['blocked', 'pending', 'retired'];

/** A real calendar day in the API's date form; rollover dates fail closed. */
export function calendarDay(value: unknown): string | null {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
  const parsed = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value ? value : null;
}

const caveatsFor = (caveats: readonly CaveatView[], code: CaveatView['code'], retailer: string) =>
  caveats.filter((c) => c.code === code && c.params.retailer === retailer);

function countFields(fields: Record<string, Schemas['FieldStatus']> | undefined) {
  const out: Partial<Record<Schemas['FieldStatus'], number>> = {};
  for (const v of Object.values(fields ?? {})) out[v] = (out[v] ?? 0) + 1;
  return out;
}

/**
 * Every retailer the dataset names (in /meta's order, then any source or caveat that names one
 * /meta does not list) with its own source state. Each retailer is matched to sources and caveats
 * by its exact id only: no alias, no other retailer's date, no fallback.
 */
export function sourceFreshness(meta: Meta, caveats: readonly CaveatView[] = []): SourceFreshness[] {
  const dates = meta.dates ?? [];
  const viewDate = dates.length ? calendarDay(dates[dates.length - 1]) : null;
  const ids: string[] = [];
  const add = (id: string | undefined) => {
    if (id && !ids.includes(id)) ids.push(id);
  };
  meta.retailers.forEach((r) => add(r.id));
  meta.sources.forEach((s) => add(s.source));
  caveats.filter((c) => c.code === 'stale_source').forEach((c) => add(c.params.retailer));

  return ids.map((id) => {
    const retailer = meta.retailers.find((r) => r.id === id) ?? null;
    const sources = meta.sources.filter((s) => s.source === id);
    const stale = caveatsFor(caveats, 'stale_source', id);
    const imported = caveatsFor(caveats, 'snapshot_import_date', id)
      .map((c) => calendarDay(c.params.date))
      .find(Boolean);
    const days = sources.map((s) => calendarDay(s.lastDate));
    const distinct = [...new Set(days)];
    const only = sources.length === 1 ? sources[0] : undefined;
    const lastDate = distinct.length === 1 ? (distinct[0] ?? null) : null;
    const base = {
      retailer: id,
      lastDate,
      viewDate,
      products: only ? only.products : null,
      status: retailer?.status ?? null,
      importedOn: imported ?? null,
      fields: only ? countFields(only.fields) : {},
    };
    const state = ((): EvidenceState => {
      if (retailer && UNAVAILABLE.includes(retailer.status)) return 'unavailable';
      if (!sources.length) return stale.length ? 'stale' : 'not_observed';
      if (distinct.length > 1) return 'conflict';
      if (!lastDate || !viewDate || lastDate > viewDate) return 'invalid';
      const asOf = stale.map((c) => calendarDay(c.params.asOf));
      if (asOf.some((d) => d !== lastDate)) return 'conflict';
      if (stale.length || lastDate < viewDate) return 'stale';
      return imported ? 'mixed' : 'fresh';
    })();
    return { ...base, state };
  });
}

/** One retailer's state, or `not_observed` when the dataset does not name it at all. */
export function freshnessOf(all: readonly SourceFreshness[], retailer: string): SourceFreshness {
  return (
    all.find((s) => s.retailer === retailer) ?? {
      retailer,
      state: 'not_observed',
      lastDate: null,
      viewDate: null,
      products: null,
      status: null,
      importedOn: null,
      fields: {},
    }
  );
}

/**
 * The state of one product's cell for one retailer in a list. The list carries no offer of that
 * retailer, no price on the read date, or a price the API flags as implausible (`invalid_price`,
 * distinct from an invalid date): each says exactly that, never "out of stock", "not sold" or
 * "removed". Otherwise the cell takes the retailer's own source state.
 */
export type CellState = EvidenceState | 'no_offer' | 'no_price' | 'invalid_price';
export function cellState(card: Pick<Card, 'prices' | 'priceFlags'>, source: SourceFreshness): CellState {
  if (!Object.hasOwn(card.prices, source.retailer)) return 'no_offer';
  if (card.priceFlags?.[source.retailer] === 'invalid_low') return 'invalid_price';
  if (card.prices[source.retailer] == null) return 'no_price';
  return source.state;
}

/** The product fields a list row can lack; each missing one is labelled, the row is kept. */
export const CARD_FIELDS = ['brand', 'name', 'category', 'image', 'size', 'price'] as const;
export type CardField = (typeof CARD_FIELDS)[number];

export function missingFields(card: Card): CardField[] {
  const blank = (v: string | null | undefined) => !v || !v.trim();
  const out: CardField[] = [];
  if (blank(card.brand)) out.push('brand');
  if (blank(card.name)) out.push('name');
  if (!card.category?.length) out.push('category');
  if (blank(card.image)) out.push('image');
  if (!card.size && blank(card.sizeLabel)) out.push('size');
  if (!Object.values(card.prices ?? {}).some((p) => p != null)) out.push('price');
  return out;
}

/**
 * The missing-data states a server-side filter cannot match, so the page can say they are not in
 * the list instead of letting them vanish: a brand filter cannot match a product without a brand,
 * a price bound one without a price, an availability filter one whose stock was not observed.
 */
export type FilterGap =
  'brand' | 'category' | 'price' | 'availability' | 'discount' | 'size' | 'shade' | 'color';
export function filterGaps(s: {
  brand: readonly string[];
  category: readonly string[];
  priceMin: string;
  priceMax: string;
  availability: readonly string[];
}): FilterGap[] {
  const out: FilterGap[] = [];
  if (s.brand.length) out.push('brand');
  if (s.category.length) out.push('category');
  if (s.priceMin || s.priceMax) out.push('price');
  if (s.availability.length) out.push('availability');
  return out;
}
