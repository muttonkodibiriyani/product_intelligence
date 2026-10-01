import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { golden } from '@/lib/api/golden';
import type { Summary } from '@/lib/api/summary';
import type { Envelope } from '@/lib/api/types';
import { useSummaries } from './use-summaries';

const summary = golden('summary') as Envelope<Summary>;
// Asked for 'asked_id', the API answers for whichever retailer `answers` names.
const answers: Record<string, string> = {};
vi.mock('../auth-provider', () => ({ useAuth: () => ({ api: {} }) }));
vi.mock('../use-meta', () => ({
  useRetailerName: () => (id: string) => ({ sephora_ae: 'Sephora UAE', ulta_ae: 'Ulta UAE' })[id] ?? id,
}));
vi.mock('@/lib/api/summary', async (orig) => ({
  ...(await orig<typeof import('@/lib/api/summary')>()),
  getSummary: async (_api: unknown, q: { retailer: string }) => ({
    ...summary,
    status: 'ok',
    caveats: [],
    data: { ...summary.data!, retailer: answers[q.retailer] ?? q.retailer },
  }),
}));

function run(ids: string[]) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
  return renderHook(() => useSummaries(ids), { wrapper });
}

describe('useSummaries: a row is named for the retailer the API answered for', () => {
  it('asked for one id, answered for another: the answering retailer’s name, not the asked one', async () => {
    answers.sephora_me = 'sephora_ae';
    const { result } = run(['sephora_me']);
    await waitFor(() => expect(result.current.rows).toHaveLength(1));
    expect(result.current.rows[0]).toMatchObject({ retailer: 'sephora_ae', name: 'Sephora UAE' });
  });

  it('an answering retailer meta does not know keeps its raw id, never the asked retailer’s name', async () => {
    answers.ulta_ae = 'ulta_new';
    const { result } = run(['ulta_ae']);
    await waitFor(() => expect(result.current.rows).toHaveLength(1));
    expect(result.current.rows[0]).toMatchObject({ retailer: 'ulta_new', name: 'ulta_new' });
  });
});
