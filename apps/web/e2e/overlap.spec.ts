import type { Page, Route } from '@playwright/test';
import { expect, golden, mockBackend, noHorizontalScroll, signedIn, test, type Mock } from './fixtures';

type Json = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any

const meta = golden('meta') as Json;
const compare = golden('compare') as Json;
// shop_a vs shop_b, rows=overlap&sort=gap: 6 reviewed pairs (4 Fixture Beauty incl. p07, 3 Sample Labs) and p07 unreviewed.
const overlap = golden('compare-overlap') as Json;
const product = golden('product') as Json;
const history = golden('history') as Json;

const only = (body: Json, keep: (r: Json) => boolean): Json => {
  const rows = body.data.rows.filter(keep);
  return { ...body, data: { ...body.data, rows, total: rows.length } };
};

/** /compare answers the Overlap page from the golden, narrowed by brand as the API would. */
function api(
  overlapFor: (u: URL) => Json = (u) => {
    const brand = u.searchParams.getAll('brand');
    return brand.length ? only(overlap, (r) => brand.includes(r.brand)) : overlap;
  },
) {
  return async (route: Route) => {
    const u = new URL(route.request().url());
    const p = u.pathname;
    if (p === '/api/v1/meta') return route.fulfill({ json: meta });
    if (p === '/api/v1/compare')
      return route.fulfill({ json: u.searchParams.get('rows') === 'overlap' ? overlapFor(u) : compare });
    if (/^\/api\/v1\/products\/[^/]+\/history$/.test(p)) return route.fulfill({ json: history });
    if (/^\/api\/v1\/products\/[^/]+$/.test(p)) return route.fulfill({ json: product });
    return route.fulfill({ status: 404, json: { error: { code: 'not_found', message: 'no route' } } });
  };
}

const overlapCalls = (mock: Mock) =>
  mock.api
    .map((r) => new URL(r.url))
    .filter((u) => u.pathname === '/api/v1/compare' && u.searchParams.get('rows') === 'overlap');

for (const locale of ['en', 'ar'] as const) {
  const T =
    locale === 'ar'
      ? {
          tab: 'كل المطابقات',
          summary: 'الملخص',
          count: '7 منتجات في المتجرين',
          split: 'أكّدها مراجِع: 6. لم تُراجَع بعد: 1.',
          unreviewed: 'مطابقة غير مُراجَعة',
          locked: 'مطابقة تامة · مُثبَّتة',
          human: 'قرّرها مراجِع',
          brand: 'العلامة التجارية',
          sampleLabs: 'Sample Labs (3)',
          back: 'العودة إلى كل المطابقات',
          empty: 'لم يُطابَق بعد أي منتج بين Shop A وShop B.',
          emptyLink: 'قارن حسب الفئة',
          emptyFiltered: 'لا يوجد منتج مطابَق في هذه العلامة التجارية أو الفئة.',
          clear: 'امسح عوامل التصفية',
        }
      : {
          tab: 'Every match',
          summary: 'Summary',
          count: '7 products at both shops',
          split: 'Confirmed by a reviewer: 6. Not reviewed yet: 1.',
          unreviewed: 'Unreviewed match',
          locked: 'Exact · Locked',
          human: 'Decided by a reviewer',
          brand: 'Brand',
          sampleLabs: 'Sample Labs (3)',
          back: 'Back to every match',
          empty: 'No product is matched between Shop A and Shop B yet.',
          emptyLink: 'Compare by category',
          emptyFiltered: 'No matched product in this brand or category.',
          clear: 'Clear filters',
        };

  // The table on a wide screen, the list on a phone: whichever is showing.
  const rows = (page: Page) =>
    page.locator('section[aria-labelledby="overlap-count"]').locator('tbody tr:visible, ul > li:visible');

  test.describe(`${locale} overlap`, () => {
    test('every pair at both shops, biggest gap first, the unreviewed one labelled, evidence on focus', async ({
      page,
    }) => {
      const mock = await mockBackend(page, { onApi: api() });
      await signedIn(page, locale);
      await page.goto(`/app/${locale}/compare/?retailers=shop_a%2Cshop_b`);
      await page.getByRole('link', { name: T.tab }).click();
      await expect(page).toHaveURL(
        new RegExp(`/app/${locale}/compare/overlap/\\?retailers=shop_a%2Cshop_b$`),
      );
      await expect(page.getByRole('link', { name: T.tab })).toHaveAttribute('aria-current', 'page');
      await expect(page.getByRole('heading', { level: 1, name: T.tab })).toBeVisible();

      const call = overlapCalls(mock).at(-1)!;
      expect(call.searchParams.get('retailers')).toBe('shop_a,shop_b');
      expect(call.searchParams.get('sort')).toBe('gap');
      expect(call.searchParams.get('limit')).toBe('500');

      await expect(page.locator('#overlap-count')).toHaveText(T.count);
      await expect(page.getByText(T.split)).toBeVisible();
      await expect(rows(page)).toHaveCount(7);
      await expect(rows(page).first()).toContainText('Product p05');
      await expect(rows(page).getByText(T.unreviewed)).toHaveCount(1);
      await expect(rows(page).last()).toContainText(T.unreviewed);

      // How p05 was matched, on keyboard focus, wired to the trigger.
      const p05 = rows(page).first();
      await p05.locator('[aria-describedby]', { hasText: T.locked }).focus();
      await expect(p05.getByRole('tooltip')).toBeVisible();
      await expect(p05.getByRole('tooltip')).toContainText(T.human);

      // A brand narrows in the API; the menu still lists every brand with its count.
      await page.getByLabel(T.brand, { exact: true }).selectOption('Sample Labs');
      await expect(page).toHaveURL(/brand=Sample\+Labs/);
      expect(overlapCalls(mock).at(-1)!.searchParams.getAll('brand')).toEqual(['Sample Labs']);
      await expect(rows(page)).toHaveCount(3);
      await expect(page.getByLabel(T.brand, { exact: true }).locator('option')).toContainText([
        'Fixture Beauty (4)',
        T.sampleLabs,
      ]);
      await noHorizontalScroll(page);

      // A product opens with Back to this view and its filters.
      await rows(page).first().getByRole('link').first().click();
      await expect(page).toHaveURL(/\/product\/\?id=p06&back=overlap&from=/);
      await page.getByRole('link', { name: T.back }).click();
      await expect(page).toHaveURL(
        new RegExp(`/app/${locale}/compare/overlap/\\?retailers=shop_a%2Cshop_b&brand=Sample\\+Labs$`),
      );
      await page.getByRole('link', { name: T.summary }).click();
      await expect(page).toHaveURL(
        new RegExp(`/app/${locale}/compare/\\?retailers=shop_a%2Cshop_b&brand=Sample\\+Labs$`),
      );
      expect(mock.external).toEqual([]);
      expect(mock.errors).toEqual([]);
    });

    test('nothing matched yet names the pair and points to the prices by category', async ({ page }) => {
      const mock = await mockBackend(page, { onApi: api(() => only(overlap, () => false)) });
      await signedIn(page, locale);
      await page.goto(`/app/${locale}/compare/overlap/?retailers=shop_a%2Cshop_b`);
      await expect(page.getByText(T.empty)).toBeVisible();
      await expect(page.getByRole('link', { name: T.emptyLink })).toHaveAttribute(
        'href',
        new RegExp(`/app/${locale}/prices/?$`),
      );

      await page.goto(`/app/${locale}/compare/overlap/?retailers=shop_a%2Cshop_b&brand=Nope`);
      await expect(page.getByText(T.emptyFiltered)).toBeVisible();
      await page.getByRole('button', { name: T.clear }).click();
      await expect(page).toHaveURL(new RegExp(`/compare/overlap/\\?retailers=shop_a%2Cshop_b$`));
      expect(mock.errors).toEqual([]);
    });
  });
}
