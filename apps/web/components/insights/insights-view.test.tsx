import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen, within } from '@testing-library/react';
import { NextIntlClientProvider } from 'next-intl';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { golden } from '@/lib/api/golden';
import type { Envelope, Schemas } from '@/lib/api/types';
import type { Insights } from '@/lib/insights';
import ar from '@/messages/ar.json';
import en from '@/messages/en.json';
import { InsightsView } from './insights-view';

type Env = Envelope<Insights>;
const base = golden('insights') as Env;
const compare = golden('compare') as Envelope<Schemas['Comparison']>;
const gaps = golden('assortment-gaps') as Envelope<Schemas['AssortmentGaps']>;

const money = (amount: string) => ({ amount, currency: 'AED', minor: Math.round(Number(amount) * 100) });

/** The golden, with every card fed: two placed brands, a size trap, and stock-out counts. */
const rich: Env = {
  ...base,
  data: {
    ...base.data!,
    pricing: {
      ...base.data!.pricing,
      sizes: [
        { value: '100', unit: 'ml', n: 9, otherCheaper: 7, equal: 1, baseCheaper: 1, medianGapPct: '-11.5' },
        ...base.data!.pricing.sizes,
      ],
      brands: [
        {
          brand: 'Undercut',
          policy: 'other_cheaper',
          n: 5,
          otherCheaper: 5,
          equal: 0,
          baseCheaper: 0,
          medianGapPct: '-9.0',
        },
        {
          brand: 'Level',
          policy: 'parity',
          n: 5,
          otherCheaper: 0,
          equal: 5,
          baseCheaper: 0,
          medianGapPct: '0.0',
        },
        {
          brand: 'Mixed',
          policy: 'mixed',
          n: 6,
          otherCheaper: 3,
          equal: 0,
          baseCheaper: 3,
          medianGapPct: '0.0',
        },
      ],
    },
    ladders: base.data!.ladders.map((l) =>
      l.retailer === 'shop_a'
        ? {
            ...l,
            reason: null,
            steps: 9,
            notCheaper: 1,
            heldOut: 1,
            medianSavingPct: '10.0',
            exceptions: [
              {
                basis: 'name',
                brand: 'Fixture Beauty',
                family: '',
                name: 'Gel',
                smallerId: 'p30',
                largerId: 'p50',
                smallerValue: '30',
                largerValue: '50',
                unit: 'ml',
                smallerPrice: money('60.00'),
                largerPrice: money('110.00'),
                unitChangePct: '10.0',
              },
            ],
          }
        : l,
    ),
    stockouts: base.data!.stockouts.map((s) =>
      s.retailer === 'shop_b'
        ? {
            ...s,
            qualifying: 2,
            suppressed: 1,
            brands: [
              { brand: 'Balmain', observed: 113, outOfStock: 113 },
              { brand: 'Half', observed: 12, outOfStock: 6 },
            ],
          }
        : s,
    ),
  },
};

let answers: Record<string, unknown> = {};
let search = '';
let status: Record<string, string> = { shop_a: 'supported', shop_b: 'partial' };
let apiVersion = '1.17.0';
const asked: string[] = [];
vi.mock('../auth-provider', () => ({
  useAuth: () => ({
    api: {
      get: async (path: string) => {
        asked.push(path);
        return answers[path];
      },
    },
  }),
}));
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn() }),
  usePathname: () => '/en/insights/',
  useSearchParams: () => new URLSearchParams(search),
}));
vi.mock('../use-meta', () => ({
  useRetailerName: () => (id: string) => ({ shop_a: 'Shop A', shop_b: 'Shop B' })[id] ?? id,
  useMeta: () => ({
    data: {
      meta: { apiVersion },
      data: {
        retailers: Object.entries(status).map(([id, s]) => ({ id, name: id, status: s })),
      },
    },
  }),
}));

afterEach(cleanup);

function view(env: Env, locale: 'en' | 'ar' = 'en', more: Record<string, unknown> = {}) {
  answers = { '/api/v1/insights': env, '/api/v1/compare': compare, '/api/v1/assortment-gaps': gaps, ...more };
  search = 'retailers=shop_a,shop_b';
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <NextIntlClientProvider
        locale={locale}
        messages={locale === 'ar' ? ar : en}
        onError={(e) => {
          throw e;
        }}
      >
        <InsightsView />
      </NextIntlClientProvider>
    </QueryClientProvider>,
  );
}

const card = (name: string) => screen.getByRole('heading', { level: 2, name }).closest('section')!;

describe('InsightsView', () => {
  it('leads each card with its one-line headline, in the agreed order', async () => {
    view(rich);
    await screen.findByText('Shop B undercuts most at 100 ml: median ⁦-11.5%⁩ on 9 matched products.');
    const titles = screen.getAllByRole('heading', { level: 2 }).map((h) => h.textContent);
    expect(titles).toEqual([
      en.insights.size.title,
      en.insights.policy.title,
      en.insights.space.title,
      en.insights.promo.title,
      en.insights.stock.title,
      en.insights.traps.title,
    ]);
    expect(screen.getByText(/1 unreviewed match: not counted/)).toBeTruthy();
  });

  it('stock-outs are counts with the partial-crawl label, never a share or a ranking', async () => {
    view(rich);
    await screen.findByRole('heading', { level: 2, name: en.insights.stock.title });
    const c = card(en.insights.stock.title);
    expect(
      within(c).getByText(
        'Balmain at Shop B: 113 observed out-of-stock listings among 113 observed listings in a partial crawl.',
      ),
    ).toBeTruthy();
    expect(within(c).getByText('6 out of stock / 12 observed')).toBeTruthy();
    expect(within(c).getByText(en.insights.stock.partial)).toBeTruthy();
    expect(c.textContent).not.toMatch(/%/);
    expect(within(c).getByRole('link', { name: 'Balmain' }).getAttribute('href')).toMatch(
      /^\/en\/explore\/?\?brand=Balmain&retailer=shop_b$/,
    );
  });

  it('a fully crawled shop is not called partial', async () => {
    status = { shop_a: 'supported', shop_b: 'supported' };
    view(rich);
    await screen.findByRole('heading', { level: 2, name: en.insights.stock.title });
    expect(screen.getByText(/113 observed listings in the latest crawl\.$/)).toBeTruthy();
    expect(screen.queryByText(en.insights.stock.partial)).toBeNull();
    status = { shop_a: 'supported', shop_b: 'partial' };
  });

  it('brands sit in their policy column and link to their counted pairs', async () => {
    view(rich);
    await screen.findByRole('heading', { level: 2, name: en.insights.policy.title });
    const c = card(en.insights.policy.title);
    expect(
      within(c).getByText('1 brand is consistently cheaper at Shop B; 1 holds price parity.'),
    ).toBeTruthy();
    expect(within(c).getByRole('link', { name: 'Undercut' }).getAttribute('href')).toMatch(
      /^\/en\/compare\/?\?retailers=shop_a%2Cshop_b&brand=Undercut$/,
    );
    expect(within(c).queryByRole('link', { name: 'Mixed' })).toBeNull();
  });

  it('size traps link both sizes to their products', async () => {
    view(rich);
    await screen.findByRole('heading', { level: 2, name: en.insights.traps.title });
    const c = card(en.insights.traps.title);
    expect(within(c).getByText(/1 of 9 size steps/)).toBeTruthy();
    const links = within(c)
      .getAllByRole('link')
      .map((a) => a.getAttribute('href'));
    expect(links.some((h) => h?.includes('p30'))).toBe(true);
    expect(links.some((h) => h?.includes('p50'))).toBe(true);
  });

  it('the golden: no placed brand, no stock-out, no ladder: each card says why, with no number', async () => {
    view(base);
    await screen.findByRole('heading', { level: 2, name: en.insights.policy.title });
    expect(within(card(en.insights.policy.title)).getByText(en.reasons.cohort_too_small)).toBeTruthy();
    expect(within(card(en.insights.stock.title)).getByText(en.reasons.cohort_too_small)).toBeTruthy();
    expect(within(card(en.insights.traps.title)).getByText(en.reasons.cohort_too_small)).toBeTruthy();
    // White space: a confirmed absence, worded as missing.
    expect(screen.getByText('Shop A lists 1 product that Shop B does not carry.')).toBeTruthy();
  });

  it('only unreviewed matches: no price is compared and the reason says so', async () => {
    const pending: Env = {
      ...base,
      data: {
        ...base.data!,
        pricing: {
          ...base.data!.pricing,
          status: 'not_enough_data',
          reason: 'matches_unreviewed',
          n: 0,
          sizes: [],
          brands: [],
          unreviewed: 6,
        },
      },
    };
    const none = { ...compare, data: { ...compare.data!, summary: null } };
    view(pending, 'en', { '/api/v1/compare': none });
    await screen.findByRole('heading', { level: 2, name: en.insights.size.title });
    expect(within(card(en.insights.size.title)).getByText(en.reasons.matches_unreviewed)).toBeTruthy();
    expect(screen.getByText(/6 unreviewed matches: not counted/)).toBeTruthy();
  });

  it('the follow-ups are named, not filled', async () => {
    view(rich);
    await screen.findByText(en.insights.more.later);
    expect(screen.getByText(/Shop A: the typical step up in size saves ⁦10.0%⁩ per unit/)).toBeTruthy();
  });

  it('Arabic: the same cards, the stock-out wording in Arabic', async () => {
    view(rich, 'ar');
    await screen.findByRole('heading', { level: 2, name: ar.insights.stock.title });
    expect(
      screen.getByText(
        /Balmain في Shop B: 113 قائمة مرصودة نافدة من المخزون من بين 113 قائمة مرصودة في رصد جزئي/,
      ),
    ).toBeTruthy();
    expect(screen.getAllByRole('heading', { level: 2 })).toHaveLength(6);
  });

  it('API 1.16.0 (no /insights): says so and asks the API nothing, no card, no number', async () => {
    apiVersion = '1.16.0';
    asked.length = 0;
    view(rich);
    await screen.findByText(
      'Insights is not available yet: it needs data service version 1.17.0 or later, and this site runs 1.16.0. Nothing is shown until the service is updated.',
    );
    expect(screen.queryAllByRole('heading', { level: 2 })).toHaveLength(0);
    expect(screen.queryByRole('combobox')).toBeNull();
    await new Promise((r) => setTimeout(r, 50));
    expect(asked).toEqual([]);
    apiVersion = '1.17.0';
  });
});
