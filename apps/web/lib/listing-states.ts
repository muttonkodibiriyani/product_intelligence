/**
 * What a retailer's own listing (new in, best sellers) lets the matrices say, and what it does not.
 *
 * The shapes mirror page_capture.listings' `read` output (#313): one summary per listing and one
 * position row per product. The wire contract for the matrices is not agreed yet, so the API maps
 * onto these types; nothing here fetches.
 */

/** Why the capture stopped reading a listing. Only `end` can mean the whole list was read. */
export const STOP_REASONS = [
  'end',
  'cap',
  'no_products',
  'empty_page',
  'repeat',
  'robots_page1',
  'page1_ssr',
  'block',
  'error',
  'pending',
] as const;
export type StopReason = (typeof STOP_REASONS)[number];

/** How much of one listing was read on one day. */
export interface ListingSummary {
  /** As served; anything outside STOP_REASONS reads as `error`. */
  stopReason: string;
  endReached: boolean;
  pagesRead: number;
  positionsCaptured: number;
  /** When the last page was read, an ISO instant in UTC. */
  capturedAt: string;
}

/**
 * What may be said about a product missing from a listing.
 * - notInList: the whole list was read and the product is not in it.
 * - notInFirst: only the first `n` positions were read; past them nothing is known.
 * - notObserved: nothing usable was read (or the list was never read), so absence says nothing.
 */
export type Absence =
  | { kind: 'notInList'; at: string }
  | { kind: 'notInFirst'; n: number; stop: StopReason }
  | { kind: 'notObserved'; stop: StopReason | 'not_read' };

function stopOf(s: string): StopReason {
  return (STOP_REASONS as readonly string[]).includes(s) ? (s as StopReason) : 'error';
}

export function absence(l: ListingSummary | null | undefined): Absence {
  if (!l) return { kind: 'notObserved', stop: 'not_read' };
  const stop = stopOf(l.stopReason);
  // A page 1 that was blocked, failed or matched no product is not an empty list.
  if (l.pagesRead < 1 || l.positionsCaptured < 1) return { kind: 'notObserved', stop };
  // Both must agree: a served end_reached with any other reason is not trusted to mean "the end".
  if (l.endReached && stop === 'end') return { kind: 'notInList', at: l.capturedAt };
  return { kind: 'notInFirst', n: l.positionsCaptured, stop };
}

/** A retailer's own product flag, as served in each language. `ar` is null when not captured. */
export interface ServedFlag {
  code: string;
  en: string;
  ar: string | null;
}

/** Reviewed Arabic for the flag codes we know, used only when the Arabic side was not captured. */
export const FLAG_AR: Readonly<Record<string, string>> = {
  new: 'جديد',
  exclusive: 'حصري',
  online_only: 'أونلاين فقط',
  limited_edition: 'إصدار محدود',
  best_seller: 'الأكثر مبيعاً',
};

/**
 * The flag text to show: the served side for the locale, untouched. In Arabic with no served
 * Arabic, the reviewed string for a known code, else the English as served; `arMissing` then tells
 * the evidence drawer to say the Arabic text was not captured.
 */
export function flagText(f: ServedFlag, locale: string): { text: string; arMissing: boolean } {
  if (locale !== 'ar') return { text: f.en, arMissing: false };
  if (f.ar) return { text: f.ar, arMissing: false };
  const reviewed = Object.hasOwn(FLAG_AR, f.code) ? FLAG_AR[f.code] : undefined;
  return { text: reviewed ?? f.en, arMissing: true };
}

/** Where a launch signal came from. Each is shown under its own source and never merged. */
export type LaunchSignal =
  | { source: 'flag'; flag: ServedFlag }
  | { source: 'newIn'; position: number; page: number; capturedAt: string }
  | { source: 'firstSeen'; date: string };

const SIGNAL_ORDER: Record<LaunchSignal['source'], number> = { flag: 0, newIn: 1, firstSeen: 2 };

/** The signals in a fixed order (flag, new-in, first seen), all of them kept. */
export function orderSignals(signals: readonly LaunchSignal[]): LaunchSignal[] {
  return [...signals].sort((a, b) => SIGNAL_ORDER[a.source] - SIGNAL_ORDER[b.source]);
}

/** One product's place in a listing, as read. */
export interface PositionRow {
  productId: string;
  position: number;
  page: number;
  /** The tile's title as served. */
  title: string;
}

/**
 * A listed product's cell: the held product page joined on product id, or, with none held, the
 * listing's own position and title only. Image, price and match come from a product page, never
 * from a guess.
 */
export type ListingCell<P> =
  { kind: 'detailed'; row: PositionRow; product: P } | { kind: 'listedOnly'; row: PositionRow };

export function listingCell<P>(row: PositionRow, held: ReadonlyMap<string, P>): ListingCell<P> {
  const product = held.get(row.productId);
  return product === undefined ? { kind: 'listedOnly', row } : { kind: 'detailed', row, product };
}

/** Best-seller positions compare only within the same listing category. */
export function ranksComparable(a: { category: string }, b: { category: string }): boolean {
  return a.category !== '' && a.category === b.category;
}
