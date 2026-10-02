import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen } from '@testing-library/react';
import { NextIntlClientProvider } from 'next-intl';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Envelope, Schemas } from '@/lib/api/types';
import en from '@/messages/en.json';
import { Explorer } from './explorer';

const api = vi.hoisted(() => ({ page: vi.fn(), get: vi.fn() }));
vi.mock('../auth-provider', () => ({ useAuth: () => ({ api }) }));
vi.mock('../use-meta', () => ({ useRetailerName: () => (id: string) => id }));
vi.mock('next/navigation', () => ({
  useSearchParams: () => new URLSearchParams(''),
  useRouter: () => ({ push: vi.fn() }),
  usePathname: () => '/en/explore/',
}));

afterEach(cleanup);

const meta = { apiVersion: '1', currency: 'AED' } as Schemas['ApiMeta'];
const empty: Schemas['ProductPage'] = {
  facets: { retailer: [], brand: [], category: [] } as unknown as Schemas['Facets'],
  items: [],
  nextCursor: null,
  total: 0,
};

function serve(body: Envelope<Schemas['ProductPage']>) {
  api.page.mockResolvedValue({ body, restarted: false });
  return render(
    <NextIntlClientProvider locale="en" messages={en} timeZone="UTC" onError={() => {}}>
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <Explorer />
      </QueryClientProvider>
    </NextIntlClientProvider>,
  );
}

describe('Explorer with nothing to list', () => {
  it('an answer that is not "ok": says the data is not available, with the API reason, never "no products"', async () => {
    serve({ status: 'not_enough_data', reason: 'capability_off', data: null, meta, caveats: [] });
    expect(await screen.findByText(en.reasons.capability_off)).toBeTruthy();
    expect(screen.getAllByRole('status').some((el) => el.textContent?.includes(en.state.notAvailable))).toBe(
      true,
    );
    expect(screen.queryByText(en.explore.empty)).toBeNull();
  });

  it('an "ok" answer with no items: no products match these filters', async () => {
    serve({ status: 'ok', data: empty, meta, caveats: [] });
    expect(await screen.findByText(en.explore.empty)).toBeTruthy();
    expect(screen.queryByText(en.state.notAvailable)).toBeNull();
  });
});
