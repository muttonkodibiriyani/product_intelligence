import type { Page, Route } from '@playwright/test';
import { expect, golden, mockBackend, noHorizontalScroll, signIn, test } from './fixtures';
import {
  IMG,
  IMG_BROKEN,
  IMG_FOREIGN,
  summaryBlocked,
  summaryBody,
  summaryImages,
  summaryNoPromo,
  summaryPricesWithheld,
} from './summary-fixture';

// The smallest valid PNG: one transparent pixel.
const PNG = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=',
  'base64',
);

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
        blocked: 'هذا المتجر يمنع الجمع.',
        pricesOff: 'مخططات الأسعار غير معروضة. هذا الحقل غير مُجمَّع بعد.',
        ratingsOff: 'مخطط التقييم غير معروض. غير مُجمَّع لهذا المتجر.',
        median: 'السعر الوسيط',
        none: 'غير مُقاس',
        noImage: 'لا توجد صورة',
        credit: 'صور المنتجات: Shop A، من img-product.sephora.me.',
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
        blocked: 'This retailer blocks collection.',
        pricesOff: "Price charts aren't shown. This field isn't collected yet.",
        ratingsOff: "The rating chart isn't shown. Not collected for this retailer.",
        median: 'Median price',
        none: 'Not measured',
        noImage: 'No image',
        credit: 'Product images: Shop A, served from img-product.sephora.me.',
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

      // A treemap tile drills into its category code, the path's first step, not the leaf.
      await page.goBack();
      const mix = page.locator('#w-mix [role=img]');
      await expect(mix.locator('svg')).toBeVisible({ timeout: 15_000 });
      await mix.scrollIntoViewIfNeeded();
      const tile = (await mix.boundingBox())!;
      await page.mouse.click(tile.x + 12, tile.y + 12); // the largest tile, Skincare › Moisturizers
      await expect(page).toHaveURL(/\/explore\/\?category=Skincare$/);

      expect(mock.external).toEqual([]);
      expect(mock.errors.filter((e) => !/404/.test(e))).toEqual([]);
    });

    test('prices and ratings withheld: the note says why their cards are missing', async ({ page }) => {
      const mock = await mockBackend(page, { onApi: api(summaryPricesWithheld) });
      await signIn(page, locale);
      const note = page.locator('main [role=note]');
      await expect(note).toHaveCount(1);
      await expect(note.locator('p')).toHaveText([T.pricesOff, T.ratingsOff]);
      // Measured tiles stay; the median price reads as not measured, never as zero.
      await expect(page.getByText(T.products, { exact: true })).toBeVisible();
      const median = page.locator('main dl > div').filter({ has: page.getByText(T.median, { exact: true }) });
      await expect(median.locator('dd')).toHaveText(T.none);
      for (const name of [T.ladder, T.brands, T.hist, T.rating, T.share, T.depth, T.top])
        await expect(h2(page, name)).toHaveCount(0);
      await expect(h2(page, T.mix)).toBeVisible();
      await chartsDrawn(page, 1);
      await noHorizontalScroll(page);
      expect(mock.external).toEqual([]);
      expect(mock.errors).toEqual([]);
    });

    test('product images: lazy, no referrer, the retailer host only, a placeholder otherwise', async ({
      page,
    }) => {
      const mock = await mockBackend(page, { onApi: api(summaryImages) });
      const images: { url: string; referer?: string }[] = [];
      // Registered after mockBackend, so it answers the image host before the catch-all does.
      await page.route('https://img-product.sephora.me/**', (r) => {
        images.push({ url: r.request().url(), referer: r.request().headers()['referer'] });
        return r.request().url() === IMG
          ? r.fulfill({ contentType: 'image/png', body: PNG })
          : r.fulfill({ status: 404, body: '' });
      });
      await signIn(page, locale);
      const top = page.locator('#w-top');
      await expect(h2(page, T.top)).toBeVisible();
      const rows = top.locator('tbody tr');
      await expect(rows).toHaveCount(5);

      // Hotlinked by decision B: lazy, and without telling the host which page asked.
      const img = rows.nth(0).locator('img');
      await expect(img).toHaveAttribute('loading', 'lazy');
      await expect(img).toHaveAttribute('referrerpolicy', 'no-referrer');
      await expect(img).toHaveAttribute('src', IMG);
      await top.scrollIntoViewIfNeeded();
      await expect.poll(() => img.evaluate((e: HTMLImageElement) => e.complete && e.naturalWidth)).toBe(1);

      // A failing image and one from another host both show the placeholder.
      for (const i of [1, 2]) {
        await expect(rows.nth(i).locator('img')).toHaveCount(0);
        await expect(rows.nth(i).getByRole('img', { name: T.noImage })).toBeVisible();
      }
      // The two placeholder rows without an image at all, too.
      for (const i of [3, 4]) await expect(rows.nth(i).getByRole('img', { name: T.noImage })).toBeVisible();
      await expect(top.getByText(T.credit, { exact: true })).toBeVisible();

      // Only the retailer's host was asked, without a referrer; the foreign host never was.
      expect(images.map((r) => r.url).sort()).toEqual([IMG, IMG_BROKEN]);
      expect(images.every((r) => r.referer === undefined)).toBe(true);
      expect(mock.external).toEqual([]);
      expect(mock.external).not.toContain(IMG_FOREIGN);
      expect(mock.errors.filter((e) => !/404/.test(e))).toEqual([]);
    });

    test('a blocked retailer: why, and the dataset; no tiles or charts', async ({ page }) => {
      const mock = await mockBackend(page, { onApi: api(summaryBlocked) });
      await signIn(page, locale);
      await expect(page.getByRole('heading', { level: 1, name: T.title })).toBeVisible();
      await expect(page.getByRole('note').filter({ hasText: T.blocked })).toBeVisible();
      await expect(h2(page, T.dataset)).toBeVisible();
      await expect(page.getByText(T.products, { exact: true })).toHaveCount(0);
      await expect(page.locator('main [data-chart]')).toHaveCount(0);
      expect(mock.external).toEqual([]);
    });
  });
}
