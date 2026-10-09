import type { Schemas } from './api/types';
import { PILOT_PAIR } from './insights';

/**
 * A line for a shop whose prices stop before the rest of the data, or a pilot shop the data does
 * not hold. Pages that read a shop at the set's date (Insights, Compare) show it above the answer,
 * so an old price is never read as today's (coordinator, 01a11f5e-b303).
 */
export type ShopNotice =
  | { kind: 'asOf'; id: string; date: string; note: Schemas['RetailerCoverage']['note'] }
  | { kind: 'absent'; id: string };

/**
 * The market's time zone. /meta does not serve it; every dataset is the AE market, whose days
 * (meta.dates, and so /coverage freshness) are Asia/Dubai days (pi_dataset models.py, `dates`).
 */
export const MARKET_TIME_ZONE = 'Asia/Dubai';

/** The calendar day (YYYY-MM-DD) of an instant in the market's time zone. */
export function marketDay(iso: string): string | null {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  // en-CA writes dates as YYYY-MM-DD.
  return new Intl.DateTimeFormat('en-CA', { timeZone: MARKET_TIME_ZONE }).format(d);
}

/**
 * The notices for the shops a page shows.
 * - asOf: the shop's last collected day (/coverage `freshness`, already a Dubai day) is before
 *   the cutoff's Dubai day. Only the cutoff, an instant, is converted: 22:07Z on 8 Oct is 9 Oct
 *   in Dubai (coordinator, 01a11f62-a32d). `since` is not read; it may be a first sighting.
 * - absent: a pilot-pair shop not collected in this data (missing, blocked or pending).
 */
export function shopNotices(
  meta: Pick<Schemas['MetaView'], 'cutoff'> | null | undefined,
  coverage: readonly Pick<Schemas['RetailerCoverage'], 'id' | 'freshness' | 'note'>[] | null | undefined,
  shown: readonly string[],
  active: readonly string[],
): ShopNotice[] {
  if (!meta) return [];
  const cutoff = marketDay(meta.cutoff);
  const out: ShopNotice[] = [];
  if (cutoff && coverage) {
    for (const id of shown) {
      const c = coverage.find((r) => r.id === id);
      if (c?.freshness && c.freshness.slice(0, 10) < cutoff)
        out.push({ kind: 'asOf', id, date: c.freshness.slice(0, 10), note: c.note ?? null });
    }
  }
  for (const id of PILOT_PAIR) if (!active.includes(id)) out.push({ kind: 'absent', id });
  return out;
}
