/**
 * Whether launches can exist yet, per shop, from /meta alone. A launch needs two collections of
 * the same shop to compare, so a shop counts as ready once it has two collection days.
 *
 * The API has no per-retailer day count yet (asked for in coverage_status); until it does, a
 * collected retailer is credited with the dataset's collection days on or after its own start
 * (`since`), an imported one with its single snapshot, and one never collected with none. When
 * the count arrives, this is the one place to read it from instead.
 */
import type { Envelope, Schemas } from '@/lib/api/types';
import { importedOn } from '../widgets/model';

/** Collection days a shop needs before its launches are measurable. */
export const MIN_DAYS = 2;

export interface ShopReadiness {
  id: string;
  name: string;
  kind: 'collected' | 'imported' | 'none';
  days: number;
  /** The latest collection day, or the import date of a one-off snapshot. */
  date: string | null;
  ready: boolean;
}

export interface LaunchReadiness {
  shops: ShopReadiness[];
  /** Some shop can have launches: the list is worth showing. */
  anyReady: boolean;
  /** Every shop can: the page needs no "soon" badge. */
  allReady: boolean;
}

const DAY = /^\d{4}-\d{2}-\d{2}$/;
const ACTIVE: ReadonlySet<Schemas['RetailerStatus']> = new Set(['supported', 'partial']);

export function launchReadiness(env: Envelope<Schemas['MetaView']> | undefined): LaunchReadiness {
  const m = env?.data;
  if (!m) return { shops: [], anyReady: false, allReady: false };
  const days = m.dates.filter((d) => DAY.test(d)).sort();
  const shops = m.retailers
    .filter((r) => ACTIVE.has(r.status))
    .map((r): ShopReadiness => {
      const imported = importedOn(env.caveats, r.id);
      if (imported)
        return { id: r.id, name: r.name, kind: 'imported', days: 1, date: imported, ready: false };
      if (!r.since) return { id: r.id, name: r.name, kind: 'none', days: 0, date: null, ready: false };
      const own = days.filter((d) => d >= r.since!);
      return {
        id: r.id,
        name: r.name,
        kind: 'collected',
        days: own.length,
        date: own.at(-1) ?? null,
        ready: own.length >= MIN_DAYS,
      };
    });
  return {
    shops,
    anyReady: shops.some((s) => s.ready),
    allReady: shops.length > 0 && shops.every((s) => s.ready),
  };
}
