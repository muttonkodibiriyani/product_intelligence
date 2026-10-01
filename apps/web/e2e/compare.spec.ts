import type { Page, Route } from '@playwright/test';
import { expect, golden, mockBackend, noHorizontalScroll, signIn, test, type Mock } from './fixtures';

type Json = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any

const meta = golden('meta') as Json;
const compare = golden('compare') as Json; // shop_a vs shop_b by brand: 15 rows, n=6, median 2.4
const limited = golden('compare-limited') as Json; // the same, cut to 3 of 15
const blocked = golden('compare-blocked') as Json; // shop_a vs shop_d: shop_d blocked, no summary
const product = golden('product') as Json;
const history = golden('history') as Json;

function api(compareFor: (u: URL) => Json = () => compare) {
  return async (route: Route) => {
    const u = new URL(route.request().url());
    const p = u.pathname;
    if (p === '/api/v1/meta') return route.fulfill({ json: meta });
    if (p === '/api/v1/compare') return route.fulfill({ json: compareFor(u) });
    if (/^\/api\/v1\/products\/[^/]+\/history$/.test(p)) return route.fulfill({ json: history });
    if (/^\/api\/v1\/products\/[^/]+$/.test(p)) return route.fulfill({ json: product });
    return route.fulfill({ status: 404, json: { error: { code: 'not_found', message: 'no route' } } });
  };
}

async function signedIn(page: Page, locale: 'en' | 'ar') {
  await signIn(page, locale);
  await expect(page.getByRole('navigation')).toBeVisible();
}

const compareCalls = (mock: Mock) =>
  mock.api.map((r) => new URL(r.url)).filter((u) => u.pathname === '/api/v1/compare');

for (const locale of ['en', 'ar'] as const) {
  const T =
    locale === 'ar'
      ? {
          nav: 'المقارنة',
          title: 'مقارنة الأسعار',
          pick: 'اختر متجرين للمقارنة.',
          base: 'الأساس',
          other: 'مقارنةً بـ',
          groupBy: 'التجميع حسب',
          counted: 'المنتجات المحتسبة',
          tooSmall: 'عدد المنتجات قليل جدًا',
          caveat: 'لم تُحتسب 1 من عناصر العينة المبكرة.',
          all15: '15 منتجًا',
          of15: '3 من 15 منتج',
          more: 'اعرض حتى 500',
          detail: 'تعذّر جمع بيانات أحد المتاجر المحددة.',
          blocked: 'محظور',
          noSummary: 'لا ملخص',
          notCounted: 'غير محسوب',
          back: 'العودة إلى المقارنة',
          brand: 'العلامة التجارية: Fixture Beauty',
        }
      : {
          nav: 'Compare',
          title: 'Compare prices',
          pick: 'Pick two retailers to compare.',
          base: 'Base',
          other: 'Compared with',
          groupBy: 'Group by',
          counted: 'Products counted',
          tooSmall: 'Too few products',
          caveat: '1 early sample items are not counted.',
          all15: '15 products',
          of15: '3 of 15 products',
          more: 'Show up to 500',
          detail: 'A selected retailer could not be collected.',
          blocked: 'Blocked',
          noSummary: 'No summary',
          notCounted: 'Not counted',
          back: 'Back to comparison',
          brand: 'Brand: Fixture Beauty',
        };

  test.describe(`${locale} compare`, () => {
    test('picking a pair asks with base first and a limit; summary, sides and groups come from the API', async ({
      page,
    }) => {
      const mock = await mockBackend(page, { onApi: api() });
      await signIn(page, locale);
      await page.getByRole('navigation').getByRole('link', { name: T.nav }).click();
      await expect(page).toHaveURL(new RegExp(`/app/${locale}/compare/$`));
      await expect(page.getByRole('heading', { level: 1, name: T.title })).toBeVisible();
      await expect(page.getByText(T.pick)).toBeVisible();
      expect(compareCalls(mock)).toEqual([]);

      await page.getByLabel(T.base).selectOption('shop_a');
      await page.getByLabel(T.other).selectOption('shop_b');
      await expect(page).toHaveURL(/\?retailers=shop_a%2Cshop_b$/);
      const call = compareCalls(mock).at(-1)!;
      expect(call.searchParams.get('retailers')).toBe('shop_a,shop_b');
      expect(call.searchParams.get('limit')).toBe('100');

      const counted = page.locator('dt', { hasText: T.counted }).locator('xpath=..');
      await expect(counted).toContainText('6');
      await expect(page.getByText('+2.4%').first()).toBeVisible();
      await expect(page.getByText(T.caveat)).toBeVisible();
      await expect(page.getByText(T.all15)).toBeVisible();
      await expect(page.locator('#rows table tbody tr')).toHaveCount(15);
      // p05: 80 vs 100 → +25.0%; an excluded row says it isn't counted.
      await expect(page.getByRole('row', { name: /Product p05/ })).toContainText('+25.0%');
      await expect(page.locator('#rows').getByText(T.notCounted).first()).toBeVisible();

      await page.getByLabel(T.groupBy).selectOption('brand');
      await expect(page).toHaveURL(/groupBy=brand/);
      await expect(page.getByText(new RegExp(T.tooSmall)).first()).toBeVisible();
      await page.getByRole('button', { name: 'Fixture Beauty' }).click();
      await expect(page).toHaveURL(/brand=Fixture\+Beauty/);
      expect(compareCalls(mock).at(-1)!.searchParams.getAll('brand')).toEqual(['Fixture Beauty']);
      await page.getByRole('button', { name: new RegExp(T.brand) }).click();
      await expect(page).not.toHaveURL(/brand=/);

      // Choosing the other side's retailer as base swaps the pair.
      await page.getByLabel(T.base).selectOption('shop_b');
      await expect(page).toHaveURL(/retailers=shop_b%2Cshop_a/);
      await noHorizontalScroll(page);
      expect(mock.external).toEqual([]);
      expect(mock.errors).toEqual([]);
    });

    test('a cut list says N of total and can ask for up to 500', async ({ page }) => {
      const mock = await mockBackend(page, {
        onApi: api((u) => (u.searchParams.get('limit') === '500' ? compare : limited)),
      });
      await signedIn(page, locale);
      await page.goto(`/app/${locale}/compare/?retailers=shop_a%2Cshop_b`);
      await expect(page.getByText(T.of15)).toBeVisible();
      await expect(page.locator('#rows table tbody tr')).toHaveCount(3);
      await page.getByRole('button', { name: T.more }).click();
      await expect(page).toHaveURL(/limit=500/);
      await expect(page.getByText(T.all15)).toBeVisible();
      expect(compareCalls(mock).at(-1)!.searchParams.get('limit')).toBe('500');
      await noHorizontalScroll(page);
      expect(mock.errors).toEqual([]);
    });

    test('a blocked retailer: the API detail, the side marked blocked, no summary numbers', async ({
      page,
    }) => {
      const mock = await mockBackend(page, { onApi: api(() => blocked) });
      await signedIn(page, locale);
      await page.goto(`/app/${locale}/compare/?retailers=shop_a%2Cshop_d`);
      await expect(page.getByRole('note')).toContainText(T.detail);
      await expect(page.getByRole('row', { name: /^Shop D/ })).toContainText(T.blocked);
      await expect(page.getByText(T.noSummary)).toBeVisible();
      await expect(page.locator('dl')).toHaveCount(0);
      await noHorizontalScroll(page);
      expect(mock.errors).toEqual([]);
    });

    test('a row opens its product, and Back returns to the same comparison', async ({ page }) => {
      const mock = await mockBackend(page, { onApi: api() });
      await signedIn(page, locale);
      await page.goto(`/app/${locale}/compare/?retailers=shop_a%2Cshop_b&groupBy=brand`);
      await page.getByRole('link', { name: 'Product p05' }).click();
      await expect(page).toHaveURL(/\/product\/\?id=p05&back=compare&from=/);
      await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
      await page.getByRole('link', { name: T.back }).click();
      await expect(page).toHaveURL(
        new RegExp(`/app/${locale}/compare/\\?retailers=shop_a%2Cshop_b&groupBy=brand$`),
      );
      await expect(page.locator('#rows table tbody tr')).toHaveCount(15);
      expect(mock.errors).toEqual([]);
    });
  });
}
