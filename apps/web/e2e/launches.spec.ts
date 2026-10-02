import type { Page, Route } from '@playwright/test';
import {
  expect,
  golden,
  mockBackend,
  noHorizontalScroll,
  openNav,
  signIn,
  test,
  type Mock,
} from './fixtures';

type Json = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any

const meta = golden('meta') as Json;
// ok, one item (p14 at shop_b) and a launches_withheld caveat.
const golden1 = golden('launches') as Json;
const items = [
  { firstSeen: '2026-09-29', id: 'p14', name: 'Product p14', retailer: 'shop_b' },
  { firstSeen: '2026-09-27', id: 'p12', name: 'Product p12', retailer: 'shop_a' },
  { firstSeen: '2026-09-20', id: 'p09', name: 'Product p09', retailer: 'shop_a' },
];
const launches = { ...golden1, data: { items, total: 3, truncated: false } };
const cut = { ...launches, data: { items, total: 40, truncated: true } };
const notApplicable = {
  ...golden1,
  status: 'not_enough_data',
  reason: 'not_applicable',
  caveats: [],
  data: { items: [], total: 0, truncated: false },
};
const product = golden('product') as Json;
const history = golden('history') as Json;

function api(launchesFor: (u: URL) => Json = () => launches) {
  return async (route: Route) => {
    const u = new URL(route.request().url());
    const p = u.pathname;
    if (p === '/api/v1/meta') return route.fulfill({ json: meta });
    if (p === '/api/v1/launches') return route.fulfill({ json: launchesFor(u) });
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
  mock.api.map((r) => new URL(r.url)).filter((u) => u.pathname === '/api/v1/launches');

for (const locale of ['en', 'ar'] as const) {
  const T =
    locale === 'ar'
      ? {
          nav: 'الجديد',
          title: 'المنتجات الجديدة',
          three: '3 منتجات',
          of40: '3 من 40 منتج',
          more: 'اعرض حتى 500',
          since: 'ظهر لأول مرة في هذا اليوم أو بعده',
          anyDay: 'أي يوم',
          notApplicable: 'هذا العرض لا ينطبق على هذا النوع من الكتالوجات.',
          back: 'العودة إلى المنتجات الجديدة',
        }
      : {
          nav: 'Launches',
          title: 'Launches',
          three: '3 products',
          of40: '3 of 40 products',
          more: 'Show up to 500',
          since: 'First seen on or after',
          anyDay: 'Any day',
          notApplicable: "This view doesn't apply to this kind of catalogue.",
          back: 'Back to launches',
        };

  test.describe(`${locale} launches`, () => {
    test('lists new products newest first, with the caveat on withheld ones', async ({ page }) => {
      const mock = await mockBackend(page, { onApi: api() });
      await signIn(page, locale);
      await openNav(page, T.nav);
      await expect(page).toHaveURL(new RegExp(`/app/${locale}/launches/$`));
      await expect(page.getByRole('heading', { level: 1, name: T.title })).toBeVisible();
      // The caveat's wording is the API's; take it from the same golden the mock serves.
      await expect(page.getByRole('note')).toContainText(golden1.caveats[0][locale]);
      await expect(page.getByText(T.three)).toBeVisible();
      const rows = page.locator('#rows table tbody tr');
      await expect(rows).toHaveCount(3);
      await expect(rows.first()).toContainText('Product p14');
      await expect(rows.first()).toContainText('Shop B');
      await expect(rows.first().locator('time')).toHaveAttribute('datetime', '2026-09-29');
      await expect(rows.last()).toContainText('Product p09');
      const first = calls(mock)[0]!;
      expect([...first.searchParams.keys()]).toEqual(['limit']);
      expect(first.searchParams.get('limit')).toBe('100');
      await noHorizontalScroll(page);
      expect(mock.external).toEqual([]);
      expect(mock.errors).toEqual([]);
    });

    test('retailers and a first-seen day go into the URL and the request', async ({ page }) => {
      const mock = await mockBackend(page, { onApi: api() });
      await signedIn(page, locale);
      await page.goto(`/app/${locale}/launches/`);
      await expect(page.locator('#rows table')).toBeVisible();
      await page.getByRole('checkbox', { name: /Shop B/ }).check();
      await expect(page).toHaveURL(/\?retailer=shop_b$/);
      await page.getByLabel(T.since).fill('2026-09-28');
      await expect(page).toHaveURL(/\?retailer=shop_b&since=2026-09-28$/);
      await expect.poll(() => calls(mock).at(-1)!.searchParams.get('since')).toBe('2026-09-28');
      expect(calls(mock).at(-1)!.searchParams.getAll('retailer')).toEqual(['shop_b']);
      await page.getByRole('button', { name: T.anyDay }).click();
      await expect(page).toHaveURL(/\?retailer=shop_b$/);
      expect(mock.errors).toEqual([]);
    });

    test('a cut list says N of total and can ask for up to 500', async ({ page }) => {
      const mock = await mockBackend(page, {
        onApi: api((u) => (u.searchParams.get('limit') === '500' ? launches : cut)),
      });
      await signedIn(page, locale);
      await page.goto(`/app/${locale}/launches/`);
      await expect(page.getByText(T.of40)).toBeVisible();
      await page.getByRole('button', { name: T.more }).click();
      await expect(page).toHaveURL(/limit=500/);
      await expect(page.getByText(T.three)).toBeVisible();
      expect(calls(mock).at(-1)!.searchParams.get('limit')).toBe('500');
      expect(mock.errors).toEqual([]);
    });

    test('a catalogue the view does not apply to says so, with no empty table', async ({ page }) => {
      const mock = await mockBackend(page, { onApi: api(() => notApplicable) });
      await signedIn(page, locale);
      await page.goto(`/app/${locale}/launches/`);
      await expect(page.getByRole('note')).toHaveText(T.notApplicable);
      await expect(page.locator('#rows')).toHaveCount(0);
      expect(mock.errors).toEqual([]);
    });

    test('a row opens its product, and Back returns to the same launches view', async ({ page }) => {
      const mock = await mockBackend(page, { onApi: api() });
      await signedIn(page, locale);
      await page.goto(`/app/${locale}/launches/?retailer=shop_a&since=2026-09-01`);
      await page.getByRole('link', { name: 'Product p12' }).click();
      await expect(page).toHaveURL(/\/product\/\?id=p12&back=launches&from=/);
      await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
      await page.getByRole('link', { name: T.back }).click();
      await expect(page).toHaveURL(
        new RegExp(`/app/${locale}/launches/\\?retailer=shop_a&since=2026-09-01$`),
      );
      await expect(page.locator('#rows table tbody tr')).toHaveCount(3);
      expect(mock.errors).toEqual([]);
    });
  });
}
