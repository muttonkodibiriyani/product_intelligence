'use client';

import { useQueries } from '@tanstack/react-query';
import { getSummary, type Summary } from '@/lib/api/summary';
import type { Envelope } from '@/lib/api/types';
import { useAuth } from '../auth-provider';
import { useRetailerName } from '../use-meta';
import type { RetailerSummary } from './kpis';
import { displayName, scopedCaveats } from './model';

/**
 * One /summary per retailer, each with an explicit `?retailer=` (the live API has no multi-retailer
 * summary), sharing the query key `useSummaryData` uses. The rows are keyed by the retailer the
 * API answered for, deduplicated, with the envelope's caveats scoped to that retailer: on API
 * < 1.5.2 an imported retailer's caveats arrive on every request.
 */
export function useSummaries(ids: readonly string[]): {
  rows: RetailerSummary[];
  /** Envelopes without data (withheld or thin), one per distinct reason, after loading. */
  empty: Envelope<Summary>[];
  loading: boolean;
  error: { error: unknown; retry: () => void } | null;
} {
  const { api } = useAuth();
  const name = useRetailerName();
  const qs = useQueries({
    queries: ids.map((retailer) => ({
      queryKey: ['summary', { retailer }],
      queryFn: ({ signal }: { signal: AbortSignal }) => getSummary(api!, { retailer }, signal),
      enabled: !!api,
    })),
  });
  {
    const rows: RetailerSummary[] = [];
    const empty: Envelope<Summary>[] = [];
    let error: { error: unknown; retry: () => void } | null = null;
    qs.forEach((q, i) => {
      const env = q.data;
      if (!env) {
        if (q.isError && !error) error = { error: q.error, retry: () => void q.refetch() };
        return;
      }
      if (!env.data || env.status !== 'ok') {
        if (!empty.some((e) => e.reason === env.reason)) empty.push(env);
        return;
      }
      const retailer = env.data.retailer;
      if (rows.some((r) => r.retailer === retailer)) return;
      rows.push({
        retailer,
        name: displayName(name, retailer, ids[i]!),
        data: env.data,
        caveats: scopedCaveats(env.caveats, [retailer, ids[i]!]),
      });
    });
    const loading = ids.length > 0 && qs.some((q) => !q.data && !q.isError);
    return { rows, empty, loading, error };
  }
}
