'use client';

import { useQuery } from '@tanstack/react-query';
import { useMemo } from 'react';
import type { GroupBy } from '@/lib/compare';
import type { Envelope, Schemas } from '@/lib/api/types';
import { useAuth } from '../auth-provider';
import { useMeta, useRetailerName } from '../use-meta';
import { activeRetailers } from './model';

/*
 * The head-to-head data for one pair, on the matched set only. Every consumer shows the
 * comparable-pair count (`summary.n`) next to what it draws, so no number reads as a
 * full-catalogue comparison.
 */

/** What the head-to-head hooks can be in; `ready` carries the body and its envelope. */
export type PairState<T> =
  | { kind: 'loading' }
  | { kind: 'error'; error: unknown; retry: () => void }
  | { kind: 'empty'; env: Envelope<T> }
  | { kind: 'ready'; data: T; env: Envelope<T> };

function state<T>(
  q: {
    data?: Envelope<T>;
    isError: boolean;
    error: unknown;
    refetch: () => unknown;
  },
  shaped: (d: T) => boolean,
): PairState<T> {
  if (q.isError && !q.data) return { kind: 'error', error: q.error, retry: () => void q.refetch() };
  if (!q.data) return { kind: 'loading' };
  // A body without the arrays we draw from is treated as no data, never handed to a chart.
  if (!q.data.data || q.data.status !== 'ok' || !shaped(q.data.data)) return { kind: 'empty', env: q.data };
  return { kind: 'ready', data: q.data.data, env: q.data };
}

/** The retailers the dashboard reports on (collected or partly collected), and the first two as the pair. */
export function useRetailers() {
  const meta = useMeta();
  const name = useRetailerName();
  const ids = useMemo(() => activeRetailers(meta.data?.data), [meta.data]);
  const pair = ids.length >= 2 ? { base: ids[0]!, other: ids[1]!, name } : null;
  return { ids, pair, name, loading: !meta.data && !meta.isError, error: meta.isError ? meta.error : null };
}

/** /compare for a pair, optionally grouped by brand or category; `limit` rows, widest gap first. */
export function useCompareData(
  pair: { base: string; other: string } | null,
  groupBy: GroupBy | null = null,
  limit = 100,
): PairState<Schemas['Comparison']> {
  const { api } = useAuth();
  const q = useQuery({
    queryKey: ['compare', pair?.base, pair?.other, groupBy, limit],
    queryFn: ({ signal }) =>
      api!.get('/api/v1/compare', {
        query: { retailers: `${pair!.base},${pair!.other}`, ...(groupBy ? { groupBy } : {}), limit },
        signal,
      }),
    enabled: !!api && !!pair,
  });
  return state(q, (d) => Array.isArray(d.rows) && Array.isArray(d.groups));
}

/** /index for a pair: the basket index per collection day, drawn only when a real trend exists. */
export function useIndexData(pair: { base: string; other: string } | null): PairState<Schemas['PriceIndex']> {
  const { api } = useAuth();
  const q = useQuery({
    queryKey: ['index', pair?.base, pair?.other],
    queryFn: ({ signal }) =>
      api!.get('/api/v1/index', { query: { retailers: `${pair!.base},${pair!.other}` }, signal }),
    enabled: !!api && !!pair,
  });
  return state(q, (d) => Array.isArray(d.points));
}
