import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { NextIntlClientProvider } from 'next-intl';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { golden } from '@/lib/api/golden';
import type { Envelope, Schemas } from '@/lib/api/types';
import ar from '@/messages/ar.json';
import en from '@/messages/en.json';
import { PromotionsView } from './promotions-view';

type Env = Envelope<Schemas['Promotions']>;
const measured = golden('promotions') as Env;
/** What pi_metrics answers when promotions cannot be measured at all: no shops, no items, a reason. */
const withheld = (reason: Schemas['Reason']): Env => ({
  ...measured,
  status: 'not_enough_data',
  reason,
  detail: { en: 'api detail', ar: 'api detail' },
  caveats: [],
  data: { retailers: [], items: [], total: 0, truncated: false },
});

let answer: Env = measured;
let search = '';
vi.mock('../auth-provider', () => ({ useAuth: () => ({ api: { get: async () => answer } }) }));
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn() }),
  usePathname: () => '/en/promotions/',
  useSearchParams: () => new URLSearchParams(search),
}));
vi.mock('../use-meta', () => ({
  useRetailerName: () => (id: string) =>
    ({ shop_a: 'Shop A', shop_b: 'Shop B', shop_c: 'Shop C', shop_d: 'Shop D' })[id] ?? id,
}));

afterEach(cleanup);

function view(env: Env, query = '', locale: 'en' | 'ar' = 'en') {
  answer = env;
  search = query;
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <NextIntlClientProvider locale={locale} messages={locale === 'ar' ? ar : en} onError={() => {}}>
        <PromotionsView />
      </NextIntlClientProvider>
    </QueryClientProvider>,
  );
}

const EMPTY = { en: en.promotions.empty, ar: ar.promotions.empty };

describe('PromotionsView', () => {
  it('a measured answer: tiles, the heading from the user’s pick, the as-of date, the deepest first', async () => {
    view(measured, 'retailer=shop_a');
    await screen.findByRole('heading', { level: 2, name: 'Deepest discounts at Shop A' });
    expect(screen.getByRole('list', { name: en.promotions.shares })).toBeTruthy();
    expect(screen.getByRole('link', { name: en.app.aboutData }).parentElement!.textContent).toMatch(
      /^Data as of .*2026 · /,
    );
    expect(screen.getByText('3 products', { selector: '[role="status"]' })).toBeTruthy();
    expect(screen.queryByRole('note')).toBeNull();
  });

  it('the heading names no shop when the user picked none, even if every row is one shop’s', async () => {
    view(measured);
    await screen.findByRole('heading', { level: 2, name: 'Deepest discounts' });
    expect(screen.queryByRole('heading', { level: 2, name: /at Shop A/ })).toBeNull();
  });

  it('a measured answer with no discounted product is "no product is discounted"', async () => {
    view({ ...measured, data: { ...measured.data!, items: [], total: 0 } });
    expect(await screen.findByText(EMPTY.en)).toBeTruthy();
  });

  it.each(['capability_off', 'field_not_collected', 'not_applicable'] as const)(
    '%s: the card says discounts are not measured and gives the API’s reason, never "no product"',
    async (reason) => {
      view(withheld(reason));
      expect(await screen.findByText(en.promotions.notMeasuredFilters)).toBeTruthy();
      expect(screen.getByText(en.reasons[reason])).toBeTruthy();
      expect(screen.queryByText(EMPTY.en)).toBeNull();
      expect(screen.queryByText(/products/, { selector: '[role="status"]' })).toBeNull();
      expect(screen.queryByText(/\b0 products\b/)).toBeNull();
      expect(screen.queryByRole('note')).toBeNull();
      // Nothing to export or cut when nothing was measured.
      expect(screen.queryByRole('button', { name: /Export/ })).toBeNull();
      expect(screen.queryByLabelText(en.promotions.minPct)).toBeNull();
    },
  );

  it('names the picked shop in the not-measured line, and keeps the shop chip so the pick can be undone', async () => {
    view(withheld('capability_off'), 'retailer=shop_b');
    expect(await screen.findByText('Discounts at Shop B aren’t measured.')).toBeTruthy();
    expect(screen.getByRole('heading', { level: 2, name: 'Deepest discounts at Shop B' })).toBeTruthy();
    expect(screen.queryByText(EMPTY.en)).toBeNull();
    expect(screen.getByRole('button', { name: /Shop: Shop B/ })).toBeTruthy();
  });

  it('one unmeasured shop among measured ones is its own tile’s business: the list is still the list', async () => {
    view(measured, 'retailer=shop_c');
    await screen.findByRole('heading', { level: 2, name: 'Deepest discounts at Shop C' });
    expect(screen.getByText('Discounts at Shop C aren’t measured.')).toBeTruthy();
    // Once in Shop C's tile, once in the card.
    expect(screen.getByRole('list', { name: en.promotions.shares }).textContent).toContain(
      en.reasons.retailer_partial,
    );
    expect(screen.getByText(en.reasons.retailer_partial)).toBeTruthy();
    expect(screen.queryByText(EMPTY.en)).toBeNull();
  });

  it('Arabic: the not-measured state in Arabic, no "no product" line', async () => {
    view(withheld('field_not_collected'), '', 'ar');
    expect(await screen.findByText(ar.promotions.notMeasuredFilters)).toBeTruthy();
    expect(screen.getByText(ar.reasons.field_not_collected)).toBeTruthy();
    expect(screen.queryByText(EMPTY.ar)).toBeNull();
    await waitFor(() => expect(screen.queryByText(en.promotions.loading)).toBeNull());
  });
});
