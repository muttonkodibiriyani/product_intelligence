import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen, within } from '@testing-library/react';
import { NextIntlClientProvider } from 'next-intl';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/lib/api/client';
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
const promotions = golden('promotions') as Envelope<Schemas['Promotions']>;

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
let apiVersion = '1.18.0';
const asked: Array<{ path: string; query: unknown }> = [];
vi.mock('../auth-provider', () => ({
  useAuth: () => ({
    api: {
      get: async (path: string, options?: { query?: unknown }) => {
        asked.push({ path, query: options?.query });
        const a = answers[path];
        if (a instanceof Error) throw a;
        return a;
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
  answers = {
    '/api/v1/insights': env,
    '/api/v1/compare': compare,
    '/api/v1/assortment-gaps': gaps,
    '/api/v1/promotions': promotions,
    ...more,
  };
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
  it('leads with ready evidence and keeps supporting cards after the stable primary cards', async () => {
    asked.length = 0;
    view(rich);
    await screen.findByText('Shop B undercuts most at 100 ml: median ⁦-11.5%⁩ on 9 matched products.');
    await screen.findByText('6 decision signals are ready');
    expect(screen.getByRole('navigation', { name: en.insights.report.toc })).toBeTruthy();
    expect(screen.getByText(en.insights.report.cohortValue)).toBeTruthy();
    expect(screen.getByText('1 proposed match excluded')).toBeTruthy();
    expect(screen.getByRole('link', { name: /Size traps/ }).getAttribute('href')).toBe('#finding-traps');
    const decisions = [
      en.insights.stock.title,
      en.insights.traps.title,
      en.insights.size.title,
      en.insights.policy.title,
      en.insights.promo.title,
      en.insights.space.title,
    ];
    const titles = screen
      .getAllByRole('heading', { level: 2 })
      .map((h) => h.textContent)
      .filter((title): title is string => !!title && decisions.includes(title));
    expect(titles).toEqual(decisions);
    expect(screen.getByText(/1 unreviewed match: not counted/)).toBeTruthy();
    expect(asked.map((a) => a.path).sort()).toEqual([
      '/api/v1/assortment-gaps',
      '/api/v1/compare',
      '/api/v1/insights',
      '/api/v1/promotions',
    ]);
    expect(asked.find((a) => a.path === '/api/v1/compare')?.query).toEqual({
      retailers: 'shop_a,shop_b',
      limit: 1,
    });
    expect(asked.find((a) => a.path === '/api/v1/assortment-gaps')?.query).toEqual({
      presentAt: 'shop_b',
      missingAt: 'shop_a',
    });
    expect(asked.find((a) => a.path === '/api/v1/promotions')?.query).toEqual({
      retailer: ['shop_a', 'shop_b'],
      limit: 4,
    });
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

  it('promotion evidence is measured, ranked and linked instead of a dead hand-off card', async () => {
    view(base);
    await screen.findByText('3 decision signals are ready');
    const c = card(en.insights.promo.title);
    expect(within(c).getByText('Product p05 at Shop A has the deepest listed cut: −33.3%.')).toBeTruthy();
    expect(within(c).getAllByRole('listitem')).toHaveLength(3);
    expect(within(c).getByRole('link', { name: 'Product p05' }).getAttribute('href')).toMatch(
      /^\/en\/product\/?\?id=p05#evidence$/,
    );
    expect(c.textContent).toMatch(/Save.*AED.*40\.00/);
    expect(within(c).getByRole('link', { name: en.insights.promo.open }).getAttribute('href')).toMatch(
      /^\/en\/promotions\/?$/,
    );
  });

  it('a measured zero stays a measured zero, never field-not-collected', async () => {
    const none = {
      ...promotions,
      status: 'ok',
      reason: null,
      data: {
        ...promotions.data!,
        items: [],
        total: 0,
        truncated: false,
        retailers: promotions.data!.retailers.map((row) =>
          row.retailer === 'shop_a' || row.retailer === 'shop_b'
            ? { ...row, share: '0.0', n: 6, onPromo: 0, reason: null }
            : row,
        ),
      },
    } as Envelope<Schemas['Promotions']>;
    view(base, 'en', { '/api/v1/promotions': none });
    await screen.findByText('2 decision signals are ready');
    expect(screen.getByText(en.insights.readiness.nonePromotions)).toBeTruthy();
    expect(screen.queryByText(en.reasons.field_not_collected)).toBeNull();
  });

  it('an unavailable Insights cohort makes only the one primary request', async () => {
    const withheld: Env = { ...base, status: 'not_enough_data', reason: 'field_not_collected', data: null };
    asked.length = 0;
    view(withheld);
    await screen.findByText(en.reasons.field_not_collected);
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(asked.map((a) => a.path)).toEqual(['/api/v1/insights']);
    expect(screen.queryByText(/decision signals are ready/)).toBeNull();
  });

  it('the golden leads with its three supported decisions and folds the dead cards away', async () => {
    view(base);
    await screen.findByText('3 decision signals are ready');
    expect(screen.getByRole('heading', { level: 2, name: en.insights.size.title })).toBeTruthy();
    expect(screen.getByRole('heading', { level: 2, name: en.insights.promo.title })).toBeTruthy();
    expect(screen.getByRole('heading', { level: 2, name: en.insights.space.title })).toBeTruthy();
    expect(screen.queryByRole('heading', { level: 2, name: en.insights.policy.title })).toBeNull();
    expect(screen.queryByRole('heading', { level: 2, name: en.insights.stock.title })).toBeNull();
    expect(screen.queryByRole('heading', { level: 2, name: en.insights.traps.title })).toBeNull();
    expect(screen.getByText('3 analyses are not ready')).toBeTruthy();
    expect(screen.getAllByText(en.reasons.cohort_too_small)).toHaveLength(3);
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
    asked.length = 0;
    view(pending);
    await screen.findByText('2 decision signals are ready');
    expect(screen.queryByRole('heading', { level: 2, name: en.insights.size.title })).toBeNull();
    expect(screen.getAllByText(en.reasons.matches_unreviewed)).toHaveLength(2);
    expect(screen.getByText('6 unreviewed matches excluded')).toBeTruthy();
    expect(asked.map((a) => a.path)).not.toContain('/api/v1/compare');
  });

  it('the follow-ups are named, not filled', async () => {
    view(rich);
    await screen.findByText(en.insights.more.later);
    expect(screen.getByText(/Shop A: the typical step up in size saves ⁦10.0%⁩ per unit/)).toBeTruthy();
  });

  it('Arabic: the same cards, the stock-out wording in Arabic', async () => {
    view(rich, 'ar');
    await screen.findByRole('heading', { level: 2, name: ar.insights.stock.title });
    await screen.findByText('6 إشارات قرار جاهزة');
    expect(
      screen.getByText(
        /Balmain في Shop B: 113 قائمة مرصودة نافدة من المخزون من بين 113 قائمة مرصودة في رصد جزئي/,
      ),
    ).toBeTruthy();
    const cards = [
      ar.insights.stock.title,
      ar.insights.traps.title,
      ar.insights.size.title,
      ar.insights.policy.title,
      ar.insights.promo.title,
      ar.insights.space.title,
    ];
    expect(
      screen.getAllByRole('heading', { level: 2 }).filter((h) => cards.includes(h.textContent ?? '')),
    ).toHaveLength(6);
  });

  it('API 1.16.0 (no /insights): says so and asks the API nothing, no card, no number', async () => {
    apiVersion = '1.16.0';
    asked.length = 0;
    view(rich);
    await screen.findByText(
      'Insights is not available yet: it needs data service version 1.18.0 or later, and this site runs 1.16.0. Nothing is shown until the service is updated.',
    );
    expect(screen.queryAllByRole('heading', { level: 2 })).toHaveLength(0);
    expect(screen.queryByRole('combobox')).toBeNull();
    await new Promise((r) => setTimeout(r, 50));
    expect(asked).toEqual([]);
    apiVersion = '1.18.0';
  });

  it('/insights answers 404 (route not deployed): the honest "not available yet", never an error card', async () => {
    view(rich, 'en', { '/api/v1/insights': new ApiError('not_found', 404) });
    await screen.findByText(
      'Insights is not available yet: the data service does not serve it. Nothing is shown until the service is updated.',
    );
    expect(screen.queryByRole('alert')).toBeNull();
    expect(screen.queryAllByRole('heading', { level: 2 })).toHaveLength(0);
    expect(screen.queryByRole('combobox')).toBeNull();
  });

  it('any other /insights failure still shows the error card', async () => {
    view(rich, 'en', { '/api/v1/insights': new ApiError('internal_error', 500) });
    expect(await screen.findByRole('alert')).toBeTruthy();
  });
});
