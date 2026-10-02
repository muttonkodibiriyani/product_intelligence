import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { NextIntlClientProvider } from 'next-intl';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { golden } from '@/lib/api/golden';
import type { Summary } from '@/lib/api/summary';
import type { Envelope, Schemas } from '@/lib/api/types';
import pagesAr from '@/messages/ar.json';
import pagesEn from '@/messages/en.json';
import widgetsAr from '@/messages/widgets.ar.json';
import widgetsEn from '@/messages/widgets.en.json';
import { PricesView } from './prices-view';

const en = { ...pagesEn, widgets: widgetsEn };
const ar = { ...pagesAr, widgets: widgetsAr };
const meta = golden('meta') as Envelope<Schemas['MetaView']>;
const summary = golden('summary') as Envelope<Summary>;

/** Shop B's summary as the API withholds it: status not ok, a reason, and an empty shape, not zeros. */
const withheld: Envelope<Summary> = {
  ...summary,
  status: 'not_enough_data',
  reason: 'retailer_blocked',
  caveats: [],
  data: {
    ...summary.data!,
    retailer: 'shop_b',
    products: null,
    priced: null,
    medianPrice: null,
    meanPrice: null,
    ladder: null,
    brandPrice: null,
    priceHist: null,
    withheld: [{ section: 'prices', reason: 'retailer_blocked' }],
  },
};

const ctx = vi.hoisted(() => ({ search: '', compare: { kind: 'loading' } as unknown }));
vi.mock('../auth-provider', () => ({ useAuth: () => ({ api: {} }) }));
vi.mock('../use-meta', () => ({
  useMeta: () => ({ data: meta }),
  useRetailerName: () => (id: string) => meta.data!.retailers.find((r) => r.id === id)?.name ?? id,
}));
vi.mock('@/lib/api/summary', async (orig) => ({
  ...(await orig<typeof import('@/lib/api/summary')>()),
  getSummary: async (_api: unknown, q: { retailer: string }) =>
    q.retailer === 'shop_b' ? withheld : { ...summary, data: { ...summary.data!, retailer: q.retailer } },
}));
vi.mock('../widgets/use-compare', async (orig) => ({
  ...(await orig<typeof import('../widgets/use-compare')>()),
  useCompareData: () => ctx.compare,
}));
vi.mock('../widgets/use-category', () => ({ useCategoryCompare: () => ({ kind: 'loading' }) }));
vi.mock('next/navigation', () => ({
  useSearchParams: () => new URLSearchParams(ctx.search),
  usePathname: () => '/en/prices/',
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
}));
vi.mock('../widgets/charts', () => {
  const Chart = () => <div data-chart />;
  return { PriceHistWidget: Chart, LadderWidget: Chart, BrandPriceWidget: Chart, GapHistWidget: Chart };
});

afterEach(() => {
  cleanup();
  ctx.compare = { kind: 'loading' };
});

/** /compare withheld for the pair: no rows, a reason. */
const noPairs = {
  kind: 'empty',
  env: {
    status: 'not_enough_data',
    reason: 'cohort_too_small',
    data: null,
    caveats: [],
    meta: { cutoff: meta.data!.cutoff },
  },
};

function show(search: string, locale: 'en' | 'ar' = 'en') {
  ctx.search = search;
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <NextIntlClientProvider locale={locale} messages={locale === 'ar' ? ar : en} onError={() => {}}>
        <PricesView />
      </NextIntlClientProvider>
    </QueryClientProvider>,
  );
}

describe('PricesView: a retailer whose summary the API withheld', () => {
  it('says why in place of the charts, and never shows another retailer’s charts for it', async () => {
    show('retailer=shop_b');
    const status = (await screen.findByText(/No price summary for Shop B yet\./)).closest('[role=status]')!;
    expect(status).not.toBeNull();
    expect(status.textContent).toContain(en.reasons.retailer_blocked);
    // No chart, no takeaway, no fact that would read as 0 for a count that was never measured.
    expect(document.querySelector('[data-takeaway]')).toBeNull();
    expect(document.querySelector('[data-chart]')).toBeNull();
    expect(document.querySelector('#p-hist')).toBeNull();
    expect(document.querySelector('dl')).toBeNull();
    expect(document.body.textContent).not.toMatch(/\b0\b/);
    // The retailer control names shops by the helper: no raw id anywhere on the page.
    expect(document.body.textContent).not.toMatch(/shop_[a-d]/);
  });

  it('keeps the measured retailer’s charts, each led by its line', async () => {
    show('');
    await waitFor(() => expect(document.querySelectorAll('[data-takeaway]')).toHaveLength(3));
    // The golden summary has one category and one brand: the line says so rather than ranking two.
    expect(document.body.textContent).toMatch(
      /Only one category has a median so far: skincare at AED\s50\.00\./,
    );
    expect(screen.queryByText(/No price summary/)).toBeNull();
    expect(document.body.textContent).not.toMatch(/shop_[a-d]/);
  });

  it('head to head without comparable pairs says so with the API’s reason, in both languages', async () => {
    ctx.compare = noPairs;
    show('');
    const line = (await screen.findByText(/No comparable pairs yet\./)).closest('p')!;
    expect(line.textContent).toBe(`${en.prices.noPairs} ${en.reasons.cohort_too_small}`);
    expect(document.querySelector('#p-gap-hist')).toBeNull();
    cleanup();
    show('', 'ar');
    const ar_ = (await screen.findByText(new RegExp(ar.prices.noPairs))).closest('p')!;
    expect(ar_.textContent).toBe(`${ar.prices.noPairs} ${ar.reasons.cohort_too_small}`);
  });

  it('says it in Arabic too', async () => {
    show('retailer=shop_b', 'ar');
    const status = (await screen.findByText(/لا يوجد ملخص أسعار لـShop B بعد\./)).closest('[role=status]')!;
    expect(status).not.toBeNull();
    expect(status.textContent).toContain(ar.reasons.retailer_blocked);
  });
});
