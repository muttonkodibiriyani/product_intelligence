import type { Page, Route } from '@playwright/test';
import { expect, golden, mockBackend, noHorizontalScroll, signIn, test, type Mock } from './fixtures';

type Json = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
const clone = <T>(v: T): T => structuredClone(v);

const meta = golden('meta') as Json;
const products = golden('products') as Json; // page 1 of 3, sort=price_asc golden, nextCursor set
const gapPage = golden('products-gap') as Json; // shop_a vs shop_b, with gaps
const emptyPage = golden('products-filtered') as Json; // total 0
const product = golden('product') as Json;
const history = golden('history') as Json;
const stale = golden('error-stale-cursor') as Json;

/** The explorer's API: answers by path and by query, and records what was asked. */
function api(over: { products?: (u: URL) => Json; product?: Json; history?: Json; meta?: Json } = {}) {
  return async (route: Route) => {
    const u = new URL(route.request().url());
    const p = u.pathname;
    if (p === '/api/v1/meta') return route.fulfill({ json: over.meta ?? meta });
    if (p === '/api/v1/products') return route.fulfill({ json: over.products?.(u) ?? products });
    if (/^\/api\/v1\/products\/[^/]+\/history$/.test(p))
      return route.fulfill({ json: over.history ?? history });
    if (/^\/api\/v1\/products\/[^/]+$/.test(p)) return route.fulfill({ json: over.product ?? product });
    return route.fulfill({ status: 404, json: { error: { code: 'not_found', message: 'no route' } } });
  };
}

/** Signs in and waits until the session is live, so a following goto doesn't race it. */
async function signedIn(page: Page, locale: 'en' | 'ar') {
  await signIn(page, locale);
  await expect(page.getByRole('navigation')).toBeVisible();
}

const productCalls = (mock: Mock) =>
  mock.api.map((r) => new URL(r.url)).filter((u) => u.pathname === '/api/v1/products');

for (const locale of ['en', 'ar'] as const) {
  const rtl = locale === 'ar';
  const T = rtl
    ? {
        nav: 'المنتجات',
        title: 'المنتجات',
        count16: '16 منتجًا',
        more: /اعرض \d+ أخرى/,
        restarted: 'تحدّثت البيانات أثناء التصفح',
        empty: 'لا منتجات تطابق عوامل التصفية هذه.',
        gap: 'الفرق',
        swap: 'بدّل الأساس',
        sort: 'الترتيب',
        notCounted: 'غير محسوب',
        back: 'العودة إلى المنتجات',
        offers: 'العروض بتاريخ',
        pairs: 'فروق الأسعار',
        history: 'سجل الأسعار',
        table: 'اعرض كجدول',
        source: 'افتح الصفحة',
        noSource: 'لا رابط للصفحة',
        filters: 'عوامل التصفية',
      }
    : {
        nav: 'Products',
        title: 'Products',
        count16: '16 products',
        more: /Show \d+ more/,
        restarted: 'The data was updated while you browsed',
        empty: 'No products match these filters.',
        gap: 'Gap',
        swap: 'Swap base',
        sort: 'Sort',
        notCounted: 'Not counted',
        back: 'Back to products',
        offers: 'Offers on',
        pairs: 'Price gaps',
        history: 'Price history',
        table: 'Show as table',
        source: 'Open page',
        noSource: 'No page link',
        filters: 'Filters',
      };

  /** Opens the filters on a narrow screen, where they start folded away. */
  async function filters(page: Page) {
    const toggle = page.getByRole('button', { name: new RegExp(`^${T.filters}`) });
    if (await toggle.isVisible()) await toggle.click();
  }

  test.describe(`${locale} explorer`, () => {
    test('lists products with a Bearer token; columns, counts and facets come from the API', async ({
      page,
      context,
    }) => {
      const mock = await mockBackend(page, { onApi: api() });
      await signIn(page, locale);
      await page.getByRole('navigation').getByRole('link', { name: T.nav }).click();
      await expect(page).toHaveURL(new RegExp(`/app/${locale}/explore/$`));
      await expect(page.getByRole('heading', { level: 1, name: T.title })).toBeVisible();
      await expect(page.getByText(T.count16)).toBeVisible();
      const rows = page.getByRole('table').getByRole('row');
      await expect(rows).toHaveCount(1 + products.data.items.length);
      await expect(page.getByRole('columnheader', { name: 'Shop A' })).toBeVisible();
      await expect(page.getByRole('link', { name: products.data.items[0].name })).toBeVisible();
      await noHorizontalScroll(page);

      const first = productCalls(mock)[0]!;
      expect(first.searchParams.get('sort')).toBe('name');
      expect(first.searchParams.get('limit')).toBe('50');
      expect(first.searchParams.has('cursor')).toBe(false);
      for (const r of mock.api) {
        expect(r.headers.authorization).toMatch(/^Bearer /);
        expect(r.headers.cookie).toBeUndefined();
      }
      expect(await context.cookies()).toEqual([]);
      expect(mock.external).toEqual([]);
      expect(mock.errors).toEqual([]);
    });

    test('two retailers make a pair: gap column, gap sort, swap keeps the order in the request', async ({
      page,
    }) => {
      const mock = await mockBackend(page, {
        onApi: api({
          products: (u) => (u.searchParams.getAll('retailer').length === 2 ? gapPage : products),
        }),
      });
      await signedIn(page, locale);
      await page.goto(`/app/${locale}/explore/`);
      await expect(page.getByRole('table')).toBeVisible();
      const sort = page.getByLabel(T.sort);
      await expect(sort.locator('option[value=gap]')).toBeDisabled();

      await filters(page);
      await page.getByRole('checkbox', { name: /Shop A/ }).check();
      await page.getByRole('checkbox', { name: /Shop B/ }).check();
      await expect(page).toHaveURL(/retailer=shop_a&retailer=shop_b/);
      await expect(page.getByRole('columnheader', { name: new RegExp(T.gap) })).toBeVisible();
      // p05: base 80, other 100 → +20.00, +25.0%
      await expect(page.getByRole('row', { name: /Product p05/ })).toContainText('+25.0%');

      await sort.selectOption('gap');
      await expect(page).toHaveURL(/sort=gap/);
      await page.getByRole('button', { name: T.swap }).click();
      await expect(page).toHaveURL(/retailer=shop_b&retailer=shop_a/);
      const last = productCalls(mock).at(-1)!;
      expect(last.searchParams.getAll('retailer')).toEqual(['shop_b', 'shop_a']);
      expect(last.searchParams.get('sort')).toBe('gap');
      await noHorizontalScroll(page);
      expect(mock.errors).toEqual([]);
    });

    test('next page with the cursor; a stale cursor restarts the list and says so', async ({ page }) => {
      let stalePage = true;
      const mock = await mockBackend(page, {
        onApi: async (route) => {
          const u = new URL(route.request().url());
          if (u.pathname === '/api/v1/products' && u.searchParams.has('cursor') && stalePage) {
            stalePage = false;
            return route.fulfill({ status: 409, json: stale });
          }
          return api()(route);
        },
      });
      await signedIn(page, locale);
      await page.goto(`/app/${locale}/explore/`);
      await page.getByRole('button', { name: T.more }).click();
      await expect(page.getByText(T.restarted)).toBeVisible();
      // Restarted from page 1: the list is not doubled.
      await expect(page.getByRole('table').getByRole('row')).toHaveCount(1 + products.data.items.length);
      const calls = productCalls(mock);
      expect(calls.at(-2)!.searchParams.get('cursor')).toBe(products.data.nextCursor);
      expect(calls.at(-1)!.searchParams.has('cursor')).toBe(false);

      await page.getByRole('button', { name: T.more }).click();
      await expect(page.getByRole('table').getByRole('row')).toHaveCount(1 + 2 * products.data.items.length);
      expect(mock.errors).toEqual([]);
    });

    test('no results: says so plainly', async ({ page }) => {
      await mockBackend(page, { onApi: api({ products: () => emptyPage }) });
      await signedIn(page, locale);
      await page.goto(`/app/${locale}/explore/?brand=Sample+Labs&retailer=shop_c`);
      await expect(page.getByText(T.empty)).toBeVisible();
      await expect(page.getByRole('table')).toHaveCount(0);
    });

    test('product page: offers with evidence, gaps, history; back keeps the filters', async ({ page }) => {
      const p = clone(product);
      p.data.offers[0].evidence.url = 'https://shop-a.example/p01';
      p.data.offers[1].evidence.url = 'javascript:alert(1)';
      const mock = await mockBackend(page, { onApi: api({ product: p }) });
      await signedIn(page, locale);
      await page.goto(`/app/${locale}/explore/?brand=Fixture+Beauty`);
      await page.getByRole('link', { name: products.data.items[0].name }).click();
      await expect(page).toHaveURL(
        new RegExp(`/app/${locale}/product/\\?id=${products.data.items[0].id}&from=`),
      );

      await expect(page.getByRole('heading', { level: 1, name: p.data.card.name })).toBeVisible();
      await expect(page.getByRole('heading', { name: new RegExp(T.offers) })).toBeVisible();
      const source = page.getByRole('link', { name: new RegExp(T.source) });
      await expect(source).toHaveCount(1);
      await expect(source).toHaveAttribute('href', 'https://shop-a.example/p01');
      await expect(source).toHaveAttribute('rel', /noopener/);
      await expect(page.getByText(T.noSource)).toBeVisible();
      await expect(page.locator('a[href^="javascript"]')).toHaveCount(0);

      await expect(page.getByRole('heading', { name: T.pairs })).toBeVisible();
      await expect(page.getByRole('heading', { name: T.history })).toBeVisible();
      await expect(page.getByRole('img', { name: /Shop A/ })).toBeVisible();
      await page.getByText(T.table).click();
      await expect(page.getByRole('rowheader', { name: /2026/ })).toHaveCount(3);
      await noHorizontalScroll(page);

      const paths = mock.api.map((r) => new URL(r.url).pathname);
      expect(paths).toContain(`/api/v1/products/${products.data.items[0].id}`);
      expect(paths).toContain(`/api/v1/products/${products.data.items[0].id}/history`);

      await page.getByRole('link', { name: T.back }).click();
      await expect(page).toHaveURL(new RegExp(`/app/${locale}/explore/\\?brand=Fixture\\+Beauty$`));
      expect(mock.external).toEqual([]);
      expect(mock.errors).toEqual([]);
    });

    test('product page: an uncounted pair says why; unknown values show as sent', async ({ page }) => {
      const p = clone(product);
      p.data.pairs[0].gap = null;
      p.data.pairs[0].excludedReason = 'match_unreviewed';
      p.data.offers[0].availability = 'teleported';
      await mockBackend(page, { onApi: api({ product: p }) });
      await signedIn(page, locale);
      await page.goto(`/app/${locale}/product/?id=p01`);
      await expect(page.getByText(T.notCounted)).toBeVisible();
      await expect(page.getByText('teleported', { exact: true })).toHaveAttribute('dir', 'ltr');
      await expect(page.getByText('availability.teleported')).toHaveCount(0);
    });

    test('product page: unknown product and a malformed id', async ({ page }) => {
      const mock = await mockBackend(page, {
        onApi: (route) =>
          new URL(route.request().url()).pathname === '/api/v1/meta'
            ? route.fulfill({ json: meta })
            : route.fulfill({ status: 404, json: { error: { code: 'not_found', message: '<b>p999</b>' } } }),
      });
      await signedIn(page, locale);
      await page.goto(`/app/${locale}/product/?id=p999`);
      await expect(page.locator('main').getByRole('alert')).toBeVisible();
      await expect(page.locator('main')).not.toContainText('<b>');

      const before = mock.api.length;
      await page.goto(`/app/${locale}/product/?id=${encodeURIComponent('../admin')}`);
      await expect(page.getByRole('link', { name: T.back })).toBeVisible();
      await expect(page.getByRole('heading', { level: 1 })).toHaveCount(0);
      expect(mock.api.slice(before).some((r) => new URL(r.url).pathname.includes('admin'))).toBe(false);
    });
  });
}

test('S2: an unknown retailer status renders as sent, not as a key path', async ({ page }) => {
  const m = clone(meta);
  m.data.retailers[0].status = 'paused';
  await mockBackend(page, { onApi: (r) => r.fulfill({ json: m }) });
  await signIn(page, 'ar');
  await expect(page.getByRole('cell', { name: 'paused', exact: true })).toBeVisible();
  await expect(page.getByText('status.paused')).toHaveCount(0);
});

test('language switch on a product keeps the product and the filters', async ({ page }) => {
  await mockBackend(page, { onApi: api() });
  await signedIn(page, 'en');
  await page.goto('/app/en/product/?id=p01&from=brand%3DFixture%2BBeauty');
  await expect(page.getByRole('heading', { level: 1, name: product.data.card.name })).toBeVisible();
  await page.getByRole('link', { name: 'Switch to Arabic' }).click();
  await expect(page).toHaveURL(/\/app\/ar\/product\/\?id=p01&from=brand%3DFixture%2BBeauty$/);
  await expect(page.locator('html')).toHaveAttribute('dir', 'rtl');
  await expect(page.getByRole('heading', { level: 1, name: product.data.card.name })).toBeVisible();
});

test('keyboard: the product list is reachable and opens a product with Enter', async ({ page }) => {
  await mockBackend(page, { onApi: api() });
  await signedIn(page, 'en');
  await page.goto('/app/en/explore/');
  const link = page.getByRole('link', { name: products.data.items[0].name });
  await expect(link).toBeVisible();
  await link.focus();
  await expect(link).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(page).toHaveURL(/\/app\/en\/product\/\?id=/);
});
