import type { Page, Route } from '@playwright/test';
import { expect, golden, mockBackend, noHorizontalScroll, signIn, test, type Mock } from './fixtures';

type Json = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any

const meta = golden('meta') as Json;
// not_enough_data (shop_c partial) with data: 3 items, shop_a 50.0%, shop_c and shop_d without a share.
const promotions = golden('promotions') as Json;
const cut = { ...promotions, data: { ...promotions.data, total: 40, truncated: true } };
const product = golden('product') as Json;
const history = golden('history') as Json;

function api(promotionsFor: (u: URL) => Json = () => promotions) {
  return async (route: Route) => {
    const u = new URL(route.request().url());
    const p = u.pathname;
    if (p === '/api/v1/meta') return route.fulfill({ json: meta });
    if (p === '/api/v1/promotions') return route.fulfill({ json: promotionsFor(u) });
    if (/^\/api\/v1\/products\/[^/]+\/history$/.test(p)) return route.fulfill({ json: history });
    if (/^\/api\/v1\/products\/[^/]+$/.test(p)) return route.fulfill({ json: product });
    return route.fulfill({ status: 404, json: { error: { code: 'not_found', message: 'no route' } } });
  };
}

async function signedIn(page: Page, locale: 'en' | 'ar') {
  await signIn(page, locale);
  await expect(page.getByRole('navigation')).toBeVisible();
}

const calls = (mock: Mock) =>
  mock.api.map((r) => new URL(r.url)).filter((u) => u.pathname === '/api/v1/promotions');

for (const locale of ['en', 'ar'] as const) {
  const T =
    locale === 'ar'
      ? {
          nav: 'العروض',
          title: 'العروض',
          detail: 'بيانات أحد المتاجر المحددة مجمّعة جزئياً فقط.',
          caveat: 'بيانات shop_c مجمّعة جزئياً.',
          partial: 'هذا المتجر مغطّى جزئيًا فقط.',
          three: '3 منتجات',
          of40: '3 من 40 منتج',
          more: 'اعرض حتى 500',
          minPct: 'أدنى خصم',
          back: 'العودة إلى العروض',
        }
      : {
          nav: 'Promotions',
          title: 'Promotions',
          detail: 'A selected retailer is only partly collected.',
          caveat: 'shop_c is only partly collected.',
          partial: 'This retailer is only partly covered.',
          three: '3 products',
          of40: '3 of 40 products',
          more: 'Show up to 500',
          minPct: 'Minimum discount',
          back: 'Back to promotions',
        };

  test.describe(`${locale} promotions`, () => {
    test('lists discounts deepest first with each retailer’s share, and says why one has none', async ({
      page,
    }) => {
      const mock = await mockBackend(page, { onApi: api() });
      await signIn(page, locale);
      await page.getByRole('navigation').getByRole('link', { name: T.nav }).click();
      await expect(page).toHaveURL(new RegExp(`/app/${locale}/promotions/$`));
      await expect(page.getByRole('heading', { level: 1, name: T.title })).toBeVisible();
      await expect(page.getByRole('note')).toContainText(T.detail);
      await expect(page.getByRole('note')).toContainText(T.caveat);
      await expect(page.getByRole('row', { name: /^Shop A/ })).toContainText('50.0%');
      await expect(page.getByRole('row', { name: /^Shop C/ })).toContainText(T.partial);
      await expect(page.getByText(T.three)).toBeVisible();
      await expect(page.locator('#rows table tbody tr')).toHaveCount(3);
      await expect(page.getByRole('row', { name: /Product p05/ })).toContainText('−33.3%');
      const first = calls(mock)[0]!;
      expect([...first.searchParams.keys()]).toEqual(['limit']);
      expect(first.searchParams.get('limit')).toBe('100');
      await noHorizontalScroll(page);
      expect(mock.external).toEqual([]);
      expect(mock.errors).toEqual([]);
    });

    test('retailers and a minimum discount go into the URL and the request', async ({ page }) => {
      const mock = await mockBackend(page, { onApi: api() });
      await signedIn(page, locale);
      await page.goto(`/app/${locale}/promotions/`);
      await expect(page.locator('#rows table')).toBeVisible();
      await page.getByRole('checkbox', { name: /Shop A/ }).check();
      await expect(page).toHaveURL(/\?retailer=shop_a$/);
      await page.getByLabel(T.minPct).selectOption('20');
      await expect(page).toHaveURL(/\?retailer=shop_a&minPct=20$/);
      await expect.poll(() => calls(mock).at(-1)!.searchParams.get('minPct')).toBe('20');
      expect(calls(mock).at(-1)!.searchParams.getAll('retailer')).toEqual(['shop_a']);
      expect(mock.errors).toEqual([]);
    });

    test('a cut list says N of total and can ask for up to 500', async ({ page }) => {
      const mock = await mockBackend(page, {
        onApi: api((u) => (u.searchParams.get('limit') === '500' ? promotions : cut)),
      });
      await signedIn(page, locale);
      await page.goto(`/app/${locale}/promotions/`);
      await expect(page.getByText(T.of40)).toBeVisible();
      await page.getByRole('button', { name: T.more }).click();
      await expect(page).toHaveURL(/limit=500/);
      await expect(page.getByText(T.three)).toBeVisible();
      expect(calls(mock).at(-1)!.searchParams.get('limit')).toBe('500');
      expect(mock.errors).toEqual([]);
    });

    test('a row opens its product, and Back returns to the same promotions view', async ({ page }) => {
      const mock = await mockBackend(page, { onApi: api() });
      await signedIn(page, locale);
      await page.goto(`/app/${locale}/promotions/?retailer=shop_a&minPct=10`);
      await page.getByRole('link', { name: 'Product p05' }).click();
      await expect(page).toHaveURL(/\/product\/\?id=p05&back=promotions&from=/);
      await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
      await page.getByRole('link', { name: T.back }).click();
      await expect(page).toHaveURL(new RegExp(`/app/${locale}/promotions/\\?retailer=shop_a&minPct=10$`));
      await expect(page.locator('#rows table tbody tr')).toHaveCount(3);
      expect(mock.errors).toEqual([]);
    });
  });
}
