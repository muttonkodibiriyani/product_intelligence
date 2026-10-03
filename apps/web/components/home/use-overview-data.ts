'use client';

import { useQueries, useQuery } from '@tanstack/react-query';
import { EMPTY_LAUNCHES, toLaunchesQuery, windowEnd } from '@/lib/launches';
import { EMPTY_PROMOTIONS, toPromotionsQuery } from '@/lib/promotions';
import type { Envelope, Schemas } from '@/lib/api/types';
import { useAuth } from '../auth-provider';
import { launchReadiness, type ShopReadiness } from '../launches/readiness';
import { useMeta } from '../use-meta';

/*
 * The Overview's promotion and launch figures, from the same two endpoints the Promotions and
 * Launches pages read, with the same default filters, so a tile's number is the page's number.
 */

export type ShopPromo = Schemas['RetailerPromo'];

/** /promotions with the Promotions page's defaults: one share (and its counts) per shop. */
export function usePromoShares(): {
  /** By retailer id, once served; an empty map while loading or after an error. */
  shares: ReadonlyMap<string, ShopPromo>;
  items: readonly Schemas['PromoItem'][];
  loading: boolean;
} {
  const { api } = useAuth();
  const q = useQuery({
    queryKey: ['promotions', 'overview'],
    queryFn: ({ signal }) =>
      api!.get('/api/v1/promotions', { query: toPromotionsQuery(EMPTY_PROMOTIONS), signal }),
    enabled: !!api,
  });
  const shares = new Map<string, ShopPromo>();
  for (const r of q.data?.data?.retailers ?? []) if (!shares.has(r.retailer)) shares.set(r.retailer, r);
  return { shares, items: q.data?.data?.items ?? [], loading: !q.data && !q.isError };
}

export interface ShopLaunches {
  shop: ShopReadiness;
  /** The Launches page's 30-day window, the day it ends on. */
  end: string;
  state: 'notReady' | 'loading' | 'error' | 'ready';
  /** The API's own count of launches in the window, once served. */
  total: number | null;
  /** Launches per day over the window, oldest first; null when the API cut the list (dates incomplete). */
  perDay: { date: string; n: number }[] | null;
  env: Envelope<Schemas['Launches']> | null;
}

/**
 * New products in the last 30 days, one /launches per shop that has two collection days, with
 * the largest limit so the window's dates are complete whenever the API does not say it cut.
 */
export function useLaunchCounts(ids: readonly string[]): { shops: ShopLaunches[]; end: string } {
  const { api } = useAuth();
  const meta = useMeta();
  const readiness = launchReadiness(meta.data);
  const end = meta.data?.data ? windowEnd(meta.data.data) : '';
  const shops = ids.map(
    (id): ShopReadiness =>
      readiness.shops.find((s) => s.id === id) ?? {
        id,
        name: id,
        kind: 'none',
        days: 0,
        date: null,
        ready: false,
      },
  );
  const query = toLaunchesQuery({ ...EMPTY_LAUNCHES, limit: 500 }, end);
  const qs = useQueries({
    queries: shops.map((s) => ({
      queryKey: ['launches', 'overview', s.id, end],
      queryFn: ({ signal }: { signal: AbortSignal }) =>
        api!.get('/api/v1/launches', { query: { ...query, retailer: [s.id] }, signal }),
      enabled: !!api && s.ready && !!end,
    })),
  });
  return {
    end,
    shops: shops.map((shop, i): ShopLaunches => {
      const q = qs[i]!;
      if (!shop.ready || !end) return { shop, end, state: 'notReady', total: null, perDay: null, env: null };
      if (q.isError) return { shop, end, state: 'error', total: null, perDay: null, env: null };
      if (!q.data) return { shop, end, state: 'loading', total: null, perDay: null, env: null };
      const d = q.data.data;
      const total = d && Number.isInteger(d.total) && d.total >= 0 ? d.total : null;
      return {
        shop,
        end,
        state: 'ready',
        total,
        // A body without its items list is not counted per day, rather than taking the page down.
        perDay:
          d && !d.truncated && Array.isArray(d.items) && query.since
            ? perDay(d.items, query.since, end)
            : null,
        env: q.data,
      };
    }),
  };
}

const DAY_MS = 86_400_000;

/** How many of the launches were first seen on each day of the window, every day listed. */
export function perDay(
  items: readonly { firstSeen: string }[],
  since: string,
  end: string,
): { date: string; n: number }[] {
  const from = Date.parse(`${since}T00:00:00Z`);
  const to = Date.parse(`${end}T00:00:00Z`);
  if (!Number.isFinite(from) || !Number.isFinite(to) || to < from) return [];
  const days = Math.round((to - from) / DAY_MS) + 1;
  const out = Array.from({ length: days }, (_, i) => ({
    date: new Date(from + i * DAY_MS).toISOString().slice(0, 10),
    n: 0,
  }));
  for (const it of items) {
    const i = Math.round((Date.parse(`${it.firstSeen.slice(0, 10)}T00:00:00Z`) - from) / DAY_MS);
    if (i >= 0 && i < days) out[i]!.n++;
  }
  return out;
}
