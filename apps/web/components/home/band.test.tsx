import { cleanup, render, within } from '@testing-library/react';
import { NextIntlClientProvider } from 'next-intl';
import { afterEach, describe, expect, it } from 'vitest';
import { summaryBody, summaryPricesWithheld } from '@/e2e/summary-fixture';
import type { Summary } from '@/lib/api/summary';
import type { CaveatView } from '@/lib/api/types';
import pagesAr from '@/messages/ar.json';
import pagesEn from '@/messages/en.json';
import widgetsAr from '@/messages/widgets.ar.json';
import widgetsEn from '@/messages/widgets.en.json';
import type { RetailerSummary } from '../widgets/kpis';
import { Band } from './band';
import { depthBands } from './model';
import type { ShopLaunches, ShopPromo } from './use-overview-data';

const en = { ...pagesEn, widgets: widgetsEn };
const ar = { ...pagesAr, widgets: widgetsAr };
const full = summaryBody.data as Summary;
const withheld = summaryPricesWithheld.data as Summary;

const row = (retailer: string, name: string, data: Summary, caveats: CaveatView[] = []): RetailerSummary => ({
  retailer,
  name,
  data: { ...data, retailer },
  caveats,
});
const snapshotCaveats: CaveatView[] = [
  { code: 'snapshot_import_date', params: { retailer: 'ulta_ae', date: '2026-09-30' }, en: 'x', ar: 'x' },
  { code: 'parent_listings_included', params: { retailer: 'ulta_ae' }, en: 'x', ar: 'x' },
  { code: 'was_price_unverified', params: { retailer: 'ulta_ae' }, en: 'x', ar: 'x' },
];
const snapshot = row(
  'ulta_ae',
  'Ulta',
  {
    ...full,
    freshness: { cutoff: '2026-09-30T11:20:00Z', ageDays: 1, status: 'snapshot' },
    withheld: [{ section: 'promotions', reason: 'was_price_unverified' }],
    promoSharePct: null,
    promoDepth: null,
    topDiscounts: null,
  },
  snapshotCaveats,
);
const shopA = row('shop_a', 'Shop A', full);
const shopB = row('shop_b', 'Shop B', { ...full, products: 4700, brands: 118, promoSharePct: '12.0' });

const shares = (list: Omit<ShopPromo, 'bands' | 'groups'>[]) =>
  new Map(list.map((s) => [s.retailer, { ...s, bands: [], groups: [] }]));
const ready = (id: string, name: string, total: number, perDay: ShopLaunches['perDay']): ShopLaunches => ({
  shop: { id, name, kind: 'collected', days: 3, date: '2026-10-01', ready: true },
  end: '2026-10-01',
  state: 'ready',
  total,
  perDay,
  env: null,
});
const notReady = (id: string, name: string, kind: 'collected' | 'imported', days: number): ShopLaunches => ({
  shop: { id, name, kind, days, date: kind === 'imported' ? '2026-09-30' : null, ready: false },
  end: '2026-10-01',
  state: 'notReady',
  total: null,
  perDay: null,
  env: null,
});
const days = (ns: number[]) => ns.map((n, i) => ({ date: `2026-09-${String(2 + i).padStart(2, '0')}`, n }));

function band(
  rows: RetailerSummary[],
  {
    locale = 'en',
    promo = new Map<string, ShopPromo>(),
    launches = [] as ShopLaunches[],
  }: { locale?: 'en' | 'ar'; promo?: Map<string, ShopPromo>; launches?: ShopLaunches[] } = {},
) {
  render(
    <NextIntlClientProvider locale={locale} messages={locale === 'ar' ? ar : en} onError={() => {}}>
      <Band rows={rows} promo={{ shares: promo, loading: false }} launches={launches} />
    </NextIntlClientProvider>,
  );
  const tile = (id: string) => document.querySelector<HTMLElement>(`[data-tile="${id}"]`)!;
  const tips = (el: HTMLElement) =>
    within(el)
      .getAllByRole('tooltip')
      .map((t) => t.textContent);
  return { tile, tips };
}

afterEach(cleanup);

describe('Band: shop tiles', () => {
  it('each shop: the hero count, four rows with bars, the freshness chip; the tile links to its list', () => {
    const { tile, tips } = band([shopA, shopB]);
    expect(document.querySelectorAll('[data-tile]')).toHaveLength(4);
    const a = tile('shop:shop_a');
    expect(a.textContent).toContain('4,812');
    expect(within(a).getByText('Brands').nextElementSibling!.nextElementSibling!.textContent).toBe('236');
    expect(a.textContent).toContain('61');
    expect(a.textContent).toContain('139.00');
    expect(a.textContent).toContain('18.4%');
    expect(within(a).getByText('Fresh')).toBeTruthy();
    expect(tips(a)).toEqual([expect.stringMatching(/^as of 30 Sept 2026/)]);
    expect(within(a).getByRole('link', { name: 'Shop A' }).getAttribute('href')).toMatch(
      /\/explore\/?\?.*retailer=shop_a/,
    );
    // Bars: the larger value fills, the smaller is scaled against it, in the shop's colour.
    const bars = (el: HTMLElement) => [...el.querySelectorAll<HTMLElement>('dd i')].map((i) => i.style.width);
    expect(bars(a)[0]).toBe('100%');
    expect(bars(tile('shop:shop_b'))[0]).toBe('50%');
    // No prose anywhere in the band: labels of one to three words only.
    for (const dt of document.querySelectorAll('dt'))
      expect(dt.textContent!.trim().split(/\s+/).length).toBeLessThanOrEqual(3);
  });

  it('a withheld section is one chip with the reason in its tooltip, never 0 or a percentage', () => {
    const { tile, tips } = band([row('shop_a', 'Shop A', withheld)]);
    const a = tile('shop:shop_a');
    expect(within(a).getAllByText('Not measured')).toHaveLength(2);
    expect(a.textContent).not.toContain('%');
    expect(a.textContent).not.toMatch(/\b0\b/);
    expect(tips(a)).toContain("This field isn't collected yet.");
    expect(a.querySelectorAll('p').length).toBeLessThanOrEqual(2);
  });

  it('an imported snapshot: a Snapshot chip with the import date, the count flagged, promotions not measured', () => {
    const { tile, tips } = band([snapshot]);
    const u = tile('shop:ulta_ae');
    expect(within(u).getByText('Snapshot')).toBeTruthy();
    expect(tips(u)).toContain('Imported 30 Sept 2026, capture date unknown');
    expect(tips(u)).toContain('Products (snapshot, may include parent listings)');
    expect(tips(u)).toContain(
      "This retailer's was-prices are unverified, so its promotions are not measured.",
    );
    expect(u.textContent).not.toMatch(/as of|day old|%/);
    // The chip sits inside its tile: nothing runs past the card's edge in the DOM order either.
    expect(within(u).getByText('Snapshot').closest('[data-tile]')).toBe(u);
  });
});

describe('Band: promotions tile', () => {
  it('the Promotions page’s share per shop with its counts in the tooltip, /summary’s share until then', () => {
    const { tile, tips } = band([shopA, shopB], {
      promo: shares([{ retailer: 'shop_a', n: 4790, onPromo: 958, share: '20.0', reason: null }]),
    });
    const p = tile('promotions');
    expect(within(p).getByRole('link', { name: 'On promotion' }).getAttribute('href')).toMatch(
      /\/promotions\/?$/,
    );
    expect(p.textContent).toContain('20%');
    expect(p.textContent).toContain('12%');
    expect(p.textContent).not.toContain('18.4%');
    expect(tips(p)).toContain('958 of 4,790 products on promotion');
  });

  it('the depth strip: one segment per band the API counted, the counts in the tooltip', () => {
    const { tile, tips } = band([shopA]);
    const p = tile('promotions');
    const { bands, total } = depthBands(full.promoDepth!);
    const strip = within(p).getByRole('img', {
      name: `Shop A: ${total} discounted products by discount depth`,
    });
    expect(strip.querySelectorAll('i[data-band]')).toHaveLength(bands.filter((b) => b.n > 0).length);
    expect(tips(p).join('\n')).toContain(`${bands[0]!.band} off: ${bands[0]!.n} products`);
    expect(within(p).getByText('Discount depth')).toBeTruthy();
  });

  it('a shop the API reports as not measured is one chip, with no strip for it', () => {
    const { tile, tips } = band([snapshot], {
      promo: shares([{ retailer: 'ulta_ae', n: 0, onPromo: 0, share: null, reason: 'was_price_unverified' }]),
    });
    const p = tile('promotions');
    expect(within(p).getAllByText('Not measured')).toHaveLength(1);
    expect(p.textContent).not.toContain('%');
    expect(within(p).queryByRole('img')).toBeNull();
    expect(tips(p)).toContain(
      "This retailer's was-prices are unverified, so its promotions are not measured.",
    );
  });
});

describe('Band: launches tile', () => {
  it('a ready shop: the API’s total and a sparkline per day; a not-ready one a chip with the reason', () => {
    const { tile, tips } = band([shopA, shopB], {
      launches: [
        ready('shop_a', 'Shop A', 7, days([0, 3, 0, 4])),
        notReady('shop_b', 'Shop B', 'collected', 1),
      ],
    });
    const l = tile('launches');
    expect(within(l).getByRole('link', { name: 'Launches' }).getAttribute('href')).toMatch(/\/launches\/?$/);
    expect(l.textContent).toContain('4 days');
    expect(l.textContent).toContain('7');
    const spark = within(l).getByRole('img', { name: 'Shop A: 7 launches, per day' });
    expect(spark.querySelectorAll('i')).toHaveLength(4);
    expect(within(l).getByText('Not yet')).toBeTruthy();
    expect(tips(l)).toContain(
      '1 of 2 · A launch is a product seen today that was not there on an earlier day, so it needs two collections to compare.',
    );
  });

  it('an imported shop reads as a snapshot; a cut list keeps the count and drops the sparkline', () => {
    const { tile, tips } = band([snapshot, shopA], {
      launches: [notReady('ulta_ae', 'Ulta', 'imported', 1), ready('shop_a', 'Shop A', 120, null)],
    });
    const l = tile('launches');
    expect(within(l).getByText('Snapshot')).toBeTruthy();
    expect(tips(l)).toContain('One-off snapshot, loaded 30 Sept 2026');
    expect(l.textContent).toContain('120');
    expect(within(l).queryByRole('img')).toBeNull();
    expect(l.querySelector('dd i')).toBeTruthy();
  });
});

describe('Band: Arabic', () => {
  it('labels in Arabic, every digit Latin, the same chips', () => {
    const { tile } = band([shopA, snapshot], {
      locale: 'ar',
      promo: shares([{ retailer: 'shop_a', n: 4790, onPromo: 958, share: '20.0', reason: null }]),
      launches: [
        ready('shop_a', 'Shop A', 7, days([0, 3, 0, 4])),
        notReady('ulta_ae', 'Ulta', 'imported', 1),
      ],
    });
    expect(document.body.textContent).not.toMatch(/[٠-٩]/);
    expect(within(tile('shop:shop_a')).getByText('العلامات')).toBeTruthy();
    expect(within(tile('shop:ulta_ae')).getByText('لقطة مستوردة')).toBeTruthy();
    expect(within(tile('promotions')).getAllByText('غير مُقاس')).toHaveLength(1);
    expect(
      within(tile('launches')).getByRole('img', { name: 'Shop A: 7 منتجات جديدة، لكل يوم' }),
    ).toBeTruthy();
    expect(within(tile('launches')).getByText('4 أيام')).toBeTruthy();
  });
});
