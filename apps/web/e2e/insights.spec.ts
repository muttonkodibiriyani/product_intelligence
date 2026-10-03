import type { Route } from '@playwright/test';
import { expect, golden, mockBackend, noHorizontalScroll, openNav, signIn, test } from './fixtures';

type Json = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any

const meta = golden('meta') as Json;
const compare = golden('compare') as Json;
const gaps = golden('assortment-gaps') as Json;
const base = golden('insights') as Json;
// The golden with stock-out counts at Shop B, so the stock card has something to show.
const insights = {
  ...base,
  data: {
    ...base.data,
    stockouts: base.data.stockouts.map((s: Json) =>
      s.retailer === 'shop_b'
        ? { ...s, qualifying: 1, brands: [{ brand: 'Balmain', observed: 113, outOfStock: 113 }] }
        : s,
    ),
  },
};

async function api(route: Route) {
  const p = new URL(route.request().url()).pathname;
  const json = {
    '/api/v1/meta': meta,
    '/api/v1/insights': insights,
    '/api/v1/compare': compare,
    '/api/v1/assortment-gaps': gaps,
  }[p];
  if (json) return route.fulfill({ json });
  return route.fulfill({ status: 404, json: { error: { code: 'not_found', message: 'no route' } } });
}

for (const locale of ['en', 'ar'] as const) {
  const T =
    locale === 'ar'
      ? {
          nav: 'الرؤى',
          title: 'الرؤى',
          cards: [
            'فرق السعر حسب الحجم',
            'سياسة أسعار العلامات',
            'فجوات التشكيلة',
            'استراتيجية العروض',
            'نفاد مخزون العلامات',
            'فخاخ الأحجام',
          ],
          stock: 'Balmain في Shop B: 113 قائمة مرصودة نافدة من المخزون من بين 113 قائمة مرصودة في آخر رصد.',
          promo: 'افتح العروض',
        }
      : {
          nav: 'Insights',
          title: 'Insights',
          cards: [
            'Price gap by size',
            'Brand price policy',
            'Assortment white space',
            'Promotion strategy',
            'Brand stock-outs',
            'Size traps',
          ],
          stock:
            'Balmain at Shop B: 113 observed out-of-stock listings among 113 observed listings in the latest crawl.',
          promo: 'Open Promotions',
        };

  test.describe(`${locale} insights`, () => {
    test('from the nav: the pair, six cards in order, counts not shares, evidence one click on', async ({
      page,
    }) => {
      const mock = await mockBackend(page, { onApi: api });
      await signIn(page, locale);
      await openNav(page, T.nav);
      await expect(page).toHaveURL(new RegExp(`/${locale}/insights/`));
      await expect(page.getByRole('heading', { name: T.title, level: 1 })).toBeVisible();
      await expect(page.getByRole('heading', { level: 2 })).toHaveText(T.cards);
      await expect(page.getByText(T.stock)).toBeVisible();
      // The page asks for the first two collected shops when the URL names none.
      const asked = mock.api.map((r) => new URL(r.url)).find((u) => u.pathname === '/api/v1/insights');
      expect(asked?.searchParams.get('retailers')).toBe('shop_a,shop_b');
      await noHorizontalScroll(page);
      await page.getByRole('link', { name: 'Balmain' }).click();
      await expect(page).toHaveURL(new RegExp(`/${locale}/explore/\\?brand=Balmain&retailer=shop_b$`));
      expect(mock.errors).toEqual([]);
    });

    test('the promotions card links to Promotions and repeats no number', async ({ page }) => {
      await mockBackend(page, { onApi: api });
      await signIn(page, locale);
      await page.goto(`/app/${locale}/insights/`);
      const card = page
        .locator('main section')
        .filter({ has: page.getByRole('heading', { name: T.cards[3] }) });
      await expect(card.getByRole('link', { name: T.promo })).toHaveAttribute(
        'href',
        new RegExp(`/${locale}/promotions/$`),
      );
      await expect(card).not.toContainText(/\d/);
    });
  });
}
