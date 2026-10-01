import type { Page, Route } from '@playwright/test';
import { expect, golden, mockBackend, noHorizontalScroll, signIn, test } from './fixtures';
import { summaryBody, summaryNoPromo } from './summary-fixture';

const meta = golden('meta');

const api = (summary: unknown) => async (r: Route) => {
  const p = new URL(r.request().url()).pathname;
  if (p === '/api/v1/summary') return r.fulfill({ json: summary });
  if (p === '/api/v1/meta') return r.fulfill({ json: meta });
  return r.fulfill({ status: 404, json: { error: { code: 'not_found', message: 'no route' } } });
};

/** Every chart drew: an SVG inside each chart box. */
async function chartsDrawn(page: Page, n: number) {
  const charts = page.locator('main [data-chart] svg');
  await expect(charts).toHaveCount(n, { timeout: 15_000 });
}

for (const locale of ['en', 'ar'] as const) {
  const ar = locale === 'ar';
  const T = ar
    ? {
        title: 'نظرة عامة',
        compare: 'المقارنة',
        products: 'المنتجات المتتبَّعة',
        promo: 'ضمن العروض',
        ladder: 'سلّم الأسعار حسب الفئة',
        brands: 'تموضع أسعار العلامات التجارية',
        hist: 'توزيع الأسعار',
        rating: 'التقييم مقابل السعر',
        mix: 'توزيع الفئات',
        share: 'تركّز العلامات التجارية',
        withheld: 'لا تُجمع العروض لهذا المتجر بعد.',
        depth: 'عمق العروض',
        top: 'أكبر التخفيضات',
        dataset: 'مجموعة البيانات الحالية',
        preview: 'معاينة للتصميم',
        index: 'مؤشر الأسعار عبر الزمن',
      }
    : {
        title: 'Overview',
        compare: 'Compare',
        products: 'Products tracked',
        promo: 'On promotion',
        ladder: 'Price ladder by category',
        brands: 'Brand price positioning',
        hist: 'Price distribution',
        rating: 'Rating vs price',
        mix: 'Category mix',
        share: 'Brand concentration',
        withheld: 'Promotions are not collected for this retailer yet.',
        depth: 'Promotion depth',
        top: 'Top discounts',
        dataset: 'Current dataset',
        preview: 'Layout preview',
        index: 'Price index over time',
      };
  const h2 = (page: Page, name: string) => page.getByRole('heading', { level: 2, name, exact: true });

  test.describe(locale, () => {
    test('today’s snapshot: only widgets with data, promotions wait on Compare', async ({ page }) => {
      const mock = await mockBackend(page, { onApi: api(summaryNoPromo) });
      await signIn(page, locale);
      await expect(page.getByRole('heading', { level: 1, name: T.title })).toBeVisible();
      await expect(page.getByText(T.products, { exact: true })).toBeVisible();
      await expect(page.getByText(T.promo, { exact: true })).toHaveCount(0);
      for (const name of [T.ladder, T.brands, T.hist, T.rating, T.mix, T.share, T.dataset])
        await expect(h2(page, name)).toBeVisible();
      for (const name of [T.depth, T.top]) await expect(h2(page, name)).toHaveCount(0);
      await expect(page.locator('main [role=note]')).toHaveCount(0);
      await chartsDrawn(page, 6);
      await noHorizontalScroll(page);

      await page.getByRole('tab', { name: T.compare }).click();
      await expect(page).toHaveURL(/\?view=compare$/);
      await expect(h2(page, T.index)).toBeVisible();
      await expect(h2(page, T.depth)).toBeVisible();
      await expect(page.locator('main [role=note]')).toHaveCount(5);
      await expect(page.locator('main [role=note]').first()).toContainText(T.preview);
      await expect(page.locator('main [role=note]').nth(3)).toContainText(T.withheld);
      await noHorizontalScroll(page);

      expect(mock.external).toEqual([]);
      expect(mock.errors).toEqual([]);
    });

    test('with regular prices: promotion widgets join, marks drill into the list', async ({ page }) => {
      const mock = await mockBackend(page, { onApi: api(summaryBody) });
      await signIn(page, locale);
      await expect(page.getByText(T.promo, { exact: true })).toBeVisible();
      for (const name of [T.depth, T.top]) await expect(h2(page, name)).toBeVisible();
      await chartsDrawn(page, 7);
      const top = page.locator('#w-top');
      await expect(top.getByRole('rowheader')).toHaveCount(5);
      await expect(top.getByRole('link', { name: 'Pillow Talk Matte Revolution Lipstick' })).toHaveAttribute(
        'href',
        /\/app\/(en|ar)\/product\/\?id=p-2$/,
      );
      await noHorizontalScroll(page);

      // A tooltip on hover, then a click on a ladder bar opens that category in the explorer.
      const ladder = page.locator('#w-ladder [role=img]');
      await ladder.scrollIntoViewIfNeeded(); // page.mouse does not scroll
      const box = (await ladder.boundingBox())!;
      const firstRow = page.locator('#w-ladder svg path, #w-ladder svg rect').first();
      await expect(firstRow).toBeVisible();
      await page.mouse.move(box.x + box.width / 2, box.y + 26);
      await page.mouse.click(box.x + box.width / 2, box.y + 26);
      await expect(page).toHaveURL(/\/explore\/\?category=Lipstick$/);

      expect(mock.external).toEqual([]);
      expect(mock.errors.filter((e) => !/404/.test(e))).toEqual([]);
    });
  });
}
