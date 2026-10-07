import type { Page, Route } from '@playwright/test';
import { categoryCompareBody, THIN } from './category-compare-fixture';
import { expect, golden, mockBackend, noHorizontalScroll, signIn, test } from './fixtures';
import { summaryBlocked, summaryBody } from './summary-fixture';

type Json = Record<string, unknown>;
type Meta = { data: { retailers: { id: string; status: string }[] } };
const goldenMeta = golden('meta') as Meta;
/** The golden /meta with shop_c blocked: the dashboard reports on the pair shop_a/shop_b. */
const twoShops: Meta = {
  ...goldenMeta,
  data: {
    ...goldenMeta.data,
    retailers: goldenMeta.data.retailers.map((r) => (r.id === 'shop_c' ? { ...r, status: 'blocked' } : r)),
  },
};
/** Only shop_a collected: no pair, so nothing head-to-head can be said. */
const oneShop: Meta = {
  ...goldenMeta,
  data: {
    ...goldenMeta.data,
    retailers: goldenMeta.data.retailers.map((r) => (r.id === 'shop_a' ? r : { ...r, status: 'blocked' })),
  },
};

type Summary = typeof summaryBody;
const asShop = (retailer: string, data: Partial<Summary['data']> = {}): Summary => ({
  ...summaryBody,
  data: { ...summaryBody.data, retailer, ...data },
  meta: { ...summaryBody.meta, filters: { retailer } },
});
const shops: Record<string, Summary> = {
  shop_a: asShop('shop_a'),
  shop_b: asShop('shop_b', { products: 4700, priced: 4680, promoSharePct: '12.0' }),
};

const promotionsGolden = golden('promotions') as Json & { data: Json };
const promotions = {
  ...promotionsGolden,
  status: 'ok',
  reason: null,
  caveats: [],
  data: {
    ...promotionsGolden.data,
    retailers: [
      { retailer: 'shop_a', n: 4790, onPromo: 881, share: '18.4', reason: null },
      { retailer: 'shop_b', n: 4680, onPromo: 562, share: '12.0', reason: null },
    ],
  },
};
const launchesGolden = golden('launches') as Json;
const launches = (retailer: string | null) => {
  const items = [{ firstSeen: '2026-09-27', id: `${retailer}-1`, name: 'Product p12', retailer }];
  return { ...launchesGolden, caveats: [], data: { items, total: items.length, truncated: false } };
};

/** Every read a dashboard view can make; `summary` answers per retailer asked for. */
const api =
  (summary: (retailer: string | null) => unknown, meta: Meta = twoShops) =>
  async (r: Route) => {
    const url = new URL(r.request().url());
    const p = url.pathname;
    if (p === '/api/v1/meta') return r.fulfill({ json: meta });
    if (p === '/api/v1/summary') return r.fulfill({ json: summary(url.searchParams.get('retailer')) });
    if (p === '/api/v1/compare') return r.fulfill({ json: golden('compare') });
    if (p === '/api/v1/category-compare')
      return r.fulfill({ json: categoryCompareBody('shop_a', 'shop_b', THIN) });
    if (p === '/api/v1/index') return r.fulfill({ json: golden('index') });
    if (p === '/api/v1/promotions') return r.fulfill({ json: promotions });
    if (p === '/api/v1/launches') return r.fulfill({ json: launches(url.searchParams.get('retailer')) });
    return r.fulfill({ status: 404, json: { error: { code: 'not_found', message: 'no route' } } });
  };
const byShop = (retailer: string | null) => shops[retailer ?? ''] ?? shops.shop_a;

/** What each view draws, by the ids the shared sections carry; anything not listed must be absent. */
const SECTIONS = {
  band: '[data-tile]',
  headline: '#headline-title',
  headToHead: '#head-to-head',
  byCategory: '#by-category',
  gaps: '#i-gaps',
  index: '#i-index',
  launches: '#i-launches',
  hist: '#i-hist-0',
  ladder: '#i-ladder-0',
  brands: '#i-brands-0',
  share: '#i-share-0',
  depth: '#i-depth-0',
  top: '#w-top',
} as const;
type Section = keyof typeof SECTIONS;
const VIEWS: Record<string, Section[]> = {
  lead: ['band', 'headline', 'gaps', 'index', 'launches'],
  price: ['headToHead', 'byCategory', 'index', 'hist', 'ladder', 'brands'],
  promo: ['band', 'depth', 'top'],
  range: ['band', 'share', 'brands', 'launches'],
};

async function open(page: Page, locale: 'en' | 'ar', view?: string) {
  await signIn(page, locale);
  await expect(page.getByRole('navigation')).toBeVisible();
  await page.goto(`/app/${locale}/dashboard/${view ? `?view=${view}` : ''}`);
}

for (const locale of ['en', 'ar'] as const) {
  const ar = locale === 'ar';
  const T = ar
    ? {
        title: 'لوحة المتابعة',
        nav: 'لوحة المتابعة',
        views: {
          lead: 'ملخص القيادة',
          price: 'مكتب التسعير',
          promo: 'مكتب العروض',
          range: 'التشكيلة والجديد',
        },
        noRetailers: 'لا يوجد متجر مُجمَّع لعرض بياناته.',
        onePair: 'تحتاج المقارنات إلى متجرين مُجمَّعين.',
      }
    : {
        title: 'Dashboard',
        nav: 'Dashboard',
        views: {
          lead: 'Leadership summary',
          price: 'Pricing desk',
          promo: 'Promotions desk',
          range: 'Range & launches',
        },
        noRetailers: 'No collected retailer to report on.',
        onePair: 'Comparisons need two collected retailers.',
      };

  test.describe(`dashboard (${locale})`, () => {
    for (const [view, drawn] of Object.entries(VIEWS)) {
      test(`${view}: draws its sections from the API and nothing else`, async ({ page }, info) => {
        const mock = await mockBackend(page, { onApi: api(byShop) });
        await open(page, locale, view);
        await expect(page.getByRole('heading', { level: 1, name: T.title })).toBeVisible();
        await expect(page.locator('html')).toHaveAttribute('dir', ar ? 'rtl' : 'ltr');
        const name = T.views[view as keyof typeof T.views];
        await expect(page.getByRole('button', { name, exact: true })).toHaveAttribute('aria-pressed', 'true');
        for (const s of drawn) await expect(page.locator(SECTIONS[s]).first(), s).toBeVisible();
        for (const s of Object.keys(SECTIONS) as Section[])
          if (!drawn.includes(s)) await expect(page.locator(SECTIONS[s]), s).toHaveCount(0);
        await noHorizontalScroll(page);
        await info.attach(`dashboard-${view}-${locale}`, {
          body: await page.screenshot({ fullPage: true }),
          contentType: 'image/png',
        });
        expect(mock.errors).toEqual([]);
      });
    }

    test('the nav lists it; the switch moves the view and the URL, by mouse and by keyboard', async ({
      page,
    }) => {
      const mock = await mockBackend(page, { onApi: api(byShop) });
      await open(page, locale);
      const nav = page.getByRole('navigation').getByRole('link', { name: T.nav });
      if (await nav.isVisible()) await expect(nav).toHaveAttribute('aria-current', 'page');
      await expect(page.getByRole('button', { name: T.views.lead, exact: true })).toHaveAttribute(
        'aria-pressed',
        'true',
      );
      await page.getByRole('button', { name: T.views.price, exact: true }).click();
      await expect(page).toHaveURL(/\?view=price$/);
      await expect(page.locator('#head-to-head')).toBeVisible();
      await expect(page.locator('[data-tile]')).toHaveCount(0);

      const promo = page.getByRole('button', { name: T.views.promo, exact: true });
      await promo.focus();
      await page.keyboard.press('Enter');
      await expect(page).toHaveURL(/\?view=promo$/);
      await expect(page.locator('#w-top').first()).toBeVisible();

      // The default view drops the query, so the plain URL is the leadership summary.
      await page.getByRole('button', { name: T.views.lead, exact: true }).click();
      await expect(page).toHaveURL(new RegExp(`/${locale}/dashboard/$`));
      expect(mock.errors).toEqual([]);
    });

    test('an unknown view is the leadership summary', async ({ page }) => {
      await mockBackend(page, { onApi: api(byShop) });
      await open(page, locale, 'stockouts');
      await expect(page.getByRole('button', { name: T.views.lead, exact: true })).toHaveAttribute(
        'aria-pressed',
        'true',
      );
    });

    test('one collected shop: the pricing desk says comparisons need two, and draws no pair section', async ({
      page,
    }) => {
      const mock = await mockBackend(page, { onApi: api(byShop, oneShop) });
      await open(page, locale, 'price');
      await expect(page.getByText(T.onePair)).toBeVisible();
      await expect(page.locator('#head-to-head')).toHaveCount(0);
      await expect(page.locator('#i-index')).toHaveCount(0);
      await expect(page.locator('#i-hist-0')).toBeVisible();
      expect(mock.errors.filter((e) => !/404/.test(e))).toEqual([]);
    });

    test('every shop withheld: one line saying so, never a zero', async ({ page }) => {
      const mock = await mockBackend(page, { onApi: api(() => summaryBlocked) });
      await open(page, locale, 'promo');
      await expect(page.getByText(T.noRetailers)).toBeVisible();
      await expect(page.locator('[data-tile]')).toHaveCount(0);
      expect(mock.errors.filter((e) => !/404/.test(e))).toEqual([]);
    });
  });
}
