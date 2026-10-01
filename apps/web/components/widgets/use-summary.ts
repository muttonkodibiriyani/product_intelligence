'use client';

import { useQuery } from '@tanstack/react-query';
import { getSummary, type Summary, type SummaryQuery } from '@/lib/api/summary';
import type { Envelope } from '@/lib/api/types';
import { useAuth } from '../auth-provider';

/** What a widget can be in; `ready` carries the data and the envelope it came in. */
export type SummaryState =
  | { kind: 'loading' }
  | { kind: 'error'; error: unknown; retry: () => void }
  | { kind: 'empty'; env: Envelope<Summary> }
  | { kind: 'ready'; data: Summary; currency: string; env: Envelope<Summary> };

/** The landing's one request: the server-side aggregate of the current snapshot. */
export function useSummaryData(params: SummaryQuery = {}): SummaryState {
  const { api } = useAuth();
  const q = useQuery({
    queryKey: ['summary', params],
    queryFn: ({ signal }) => getSummary(api!, params, signal),
    enabled: !!api,
  });
  if (q.isError && !q.data) return { kind: 'error', error: q.error, retry: () => void q.refetch() };
  if (!q.data) return { kind: 'loading' };
  const env = q.data;
  if (!env.data || env.status !== 'ok') return { kind: 'empty', env };
  return {
    kind: 'ready',
    data: env.data,
    currency: env.data.medianPrice?.currency ?? env.meta.currency,
    env,
  };
}
