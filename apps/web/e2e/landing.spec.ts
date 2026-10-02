import type { Page, Route } from '@playwright/test';
import { expect, golden, mockBackend, noHorizontalScroll, signIn, test } from './fixtures';
import {
  IMG,
  IMG_BROKEN,
  IMG_FOREIGN,
  IMG_ULTA,
  IMG_ULTA_BROKEN,
  summaryBlocked,
  summaryBody,
  summaryImages,
  summaryNoPromo,
  summaryPricesWithheld,
  summaryUlta,
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

/** A caveat box anywhere but inside the Dataset section, which is the one place allowed one. */
const noteOutsideDataset = (page: Page) => page.locator('main [role=note]:not(#dataset [role=note])');

/** Every chart drew: an SVG inside each chart box. */
async function chartsDrawn(page: Page, n: number) {
  const charts = page.locator('main [data-chart] svg');
  await expect(charts).toHaveCount(n, { timeout: 15_000 });
  // Each keeps its own label for screen readers: ECharts' generated English data dump never
  // replaces it (in Arabic too).
  for (const label of await page
    .locator('main [data-chart]')
    .evaluateAll((els) => els.map((e) => e.ariaLabel)))
    expect(label).not.toMatch(/^This is a chart|^$/);
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
        withheld: 'خصومات Sephora: غير متاحة بعد',
        depth: 'عمق العروض',
        top: 'أكبر التخفيضات',
        dataset: 'مجموعة البيانات الحالية',
        preview: 'معاينة للتصميم',
        index: 'مؤشر الأسعار عبر الزمن',
        blocked: 'هذا المتجر يمنع الجمع.',
        noRetailers: 'لا يوجد متجر مُجمَّع لعرض بياناته.',
        about: 'عن البيانات',
        navDataset: 'البيانات',
        aboutP1: /تُجمع الأسعار من كل متجر/,
        partial: 'مُجمَّع جزئيًا',
        pricesOff: 'مخططات الأسعار غير معروضة.',
        ratingsOff: 'مخطط التقييم غير معروض.',
        median: 'السعر الوسيط',
        none: 'غير مُقاس',
        noImage: 'لا توجد صورة',
        credit: 'صور المنتجات: Sephora، من img-product.sephora.me.',
        creditUlta: 'صور المنتجات: Ulta Beauty، من media.alshaya.com.',
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
        withheld: 'Sephora discounts: not available yet',
        depth: 'Promotion depth',
        top: 'Top discounts',
        dataset: 'Current dataset',
        preview: 'Layout preview',
        index: 'Price index over time',
        blocked: 'This retailer blocks collection.',
        noRetailers: 'No collected retailer to report on.',
        about: 'About the data',
        navDataset: 'Dataset',
        aboutP1: /Prices are collected from each shop on the dates shown/,
        partial: 'Partly collected',
        pricesOff: "Price charts aren't shown.",
        ratingsOff: "The rating chart isn't shown.",
        median: 'Median price',
        none: 'Not measured',
        noImage: 'No image',
        credit: 'Product images: Sephora, served from img-product.sephora.me.',
        creditUlta: 'Product images: Ulta Beauty, served from media.alshaya.com.',
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
      // No caveat box anywhere on the page; the only place one may live is the Dataset section.
      await expect(page.locator('main [role=note]')).toHaveCount(0);
      await expect(noteOutsideDataset(page)).toHaveCount(0);
      await expect(page.getByRole('link', { name: T.about }).first()).toBeVisible();
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

    test('prices and ratings withheld: their cards are simply missing, with no note box', async ({
      page,
    }) => {
      const mock = await mockBackend(page, { onApi: api(summaryPricesWithheld) });
      await signIn(page, locale);
      // Measured tiles stay; the median price reads as not measured, never as zero.
      await expect(page.getByText(T.products, { exact: true })).toBeVisible();
      await expect(page.locator('main [role=note]')).toHaveCount(0);
      await expect(page.locator('main')).not.toContainText(T.pricesOff);
      await expect(page.locator('main')).not.toContainText(T.ratingsOff);
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
      // A retailer /meta doesn't name (sephora_me) renders by the shop's own name, never its id.
      await expect(page.getByRole('heading', { level: 1, name: T.title })).toBeVisible();
      await expect(page.locator('main')).not.toContainText('sephora_me');
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

      // A failing image, a foreign host's and Ulta's (not Sephora's host) show the placeholder.
      for (const i of [1, 2, 3]) {
        await expect(rows.nth(i).locator('img')).toHaveCount(0);
        await expect(rows.nth(i).getByRole('img', { name: T.noImage })).toBeVisible();
      }
      // A row without an image at all, too.
      await expect(rows.nth(4).getByRole('img', { name: T.noImage })).toBeVisible();
      // The credit links to the image owner's home page, in a new tab, without a referrer.
      await expect(top.getByText(T.credit, { exact: true })).toBeVisible();
      const owner = top.getByRole('link', { name: 'Sephora', exact: true });
      await expect(owner).toHaveAttribute('href', 'https://www.sephora.me');
      await expect(owner).toHaveAttribute('target', '_blank');
      await expect(owner).toHaveAttribute('rel', 'noopener noreferrer');
      await expect(top.getByText(T.creditUlta, { exact: true })).toHaveCount(0);

      // Only the retailer's host was asked, without a referrer; the foreign host never was.
      expect(images.map((r) => r.url).sort()).toEqual([IMG, IMG_BROKEN]);
      expect(images.every((r) => r.referer === undefined)).toBe(true);
      expect(mock.external).toEqual([]);
      for (const url of [IMG_FOREIGN, IMG_ULTA]) expect(mock.external).not.toContain(url);
      expect(mock.errors.filter((e) => !/404/.test(e))).toEqual([]);
    });

    test('Ulta UAE: its own host renders and is credited; Sephora’s host is never asked', async ({
      page,
    }) => {
      const mock = await mockBackend(page, { onApi: api(summaryUlta) });
      const ulta: { url: string; referer?: string }[] = [];
      const sephora: string[] = [];
      await page.route('https://media.alshaya.com/**', (r) => {
        ulta.push({ url: r.request().url(), referer: r.request().headers()['referer'] });
        return r.request().url() === IMG_ULTA
          ? r.fulfill({ contentType: 'image/png', body: PNG })
          : r.fulfill({ status: 404, body: '' });
      });
      await page.route('https://img-product.sephora.me/**', (r) => {
        sephora.push(r.request().url());
        return r.fulfill({ status: 404, body: '' });
      });
      await signIn(page, locale);
      const top = page.locator('#w-top');
      await expect(h2(page, T.top)).toBeVisible();
      await top.scrollIntoViewIfNeeded();
      const rows = top.locator('tbody tr');
      await expect(rows).toHaveCount(5);
      const img = rows.nth(0).locator('img');
      await expect(img).toHaveAttribute('src', IMG_ULTA);
      await expect(img).toHaveAttribute('loading', 'lazy');
      await expect(img).toHaveAttribute('referrerpolicy', 'no-referrer');
      await expect.poll(() => img.evaluate((e: HTMLImageElement) => e.complete && e.naturalWidth)).toBe(1);
      // Failing, missing, Sephora's host on an Ulta snapshot, and a foreign host: placeholders.
      for (const i of [1, 2, 3, 4]) {
        await expect(rows.nth(i).locator('img')).toHaveCount(0);
        await expect(rows.nth(i).getByRole('img', { name: T.noImage })).toBeVisible();
      }
      await expect(top.getByRole('rowheader')).toHaveCount(5);
      // Credited to Ulta's owner only: nothing of Sephora's was shown.
      await expect(top.getByText(T.creditUlta, { exact: true })).toBeVisible();
      const owner = top.getByRole('link', { name: 'Ulta Beauty', exact: true });
      await expect(owner).toHaveAttribute('href', 'https://www.ulta.ae');
      await expect(owner).toHaveAttribute('rel', 'noopener noreferrer');
      await expect(top.getByText(T.credit, { exact: true })).toHaveCount(0);
      expect(ulta.map((r) => r.url).sort()).toEqual([IMG_ULTA, IMG_ULTA_BROKEN].sort());
      expect(ulta.every((r) => r.referer === undefined)).toBe(true);
      expect(sephora).toEqual([]);
      expect(mock.external).toEqual([]);
      expect(mock.errors.filter((e) => !/404/.test(e))).toEqual([]);
    });

    test('Dataset page: the nav opens it; About the data explains in plain words, once', async ({ page }) => {
      const mock = await mockBackend(page, { onApi: api(summaryNoPromo) });
      await signIn(page, locale);
      await page.getByRole('navigation').getByRole('link', { name: T.navDataset }).click();
      await expect(page).toHaveURL(new RegExp(`/app/${locale}/dataset/$`));
      await expect(page.getByRole('heading', { level: 1, name: T.dataset })).toBeVisible();
      await expect(page.getByRole('heading', { level: 2, name: T.about })).toBeVisible();
      await expect(page.locator('#about-data')).toContainText(T.aboutP1);
      // The retailers keep their status here, and only here: Shop C reads as partly collected.
      await expect(page.locator('#dataset tr').filter({ hasText: 'Shop C' })).toContainText(T.partial);
      // The footer's link lands on the same section.
      await expect(page.locator('footer').getByRole('link', { name: T.about })).toHaveAttribute(
        'href',
        new RegExp(`/${locale}/dataset/#about-data$`),
      );
      await expect(noteOutsideDataset(page)).toHaveCount(0);
      await noHorizontalScroll(page);
      expect(mock.external).toEqual([]);
      expect(mock.errors).toEqual([]);
    });

    test('a blocked retailer: one plain line and the dataset; no note box, tiles or charts', async ({
      page,
    }) => {
      const mock = await mockBackend(page, { onApi: api(summaryBlocked) });
      await signIn(page, locale);
      await expect(page.getByRole('heading', { level: 1, name: T.title })).toBeVisible();
      await expect(page.getByText(T.noRetailers)).toBeVisible();
      await expect(page.locator('main')).not.toContainText(T.blocked);
      await expect(page.locator('main [role=note]')).toHaveCount(0);
      await expect(h2(page, T.dataset)).toBeVisible();
      await expect(page.getByText(T.products, { exact: true })).toHaveCount(0);
      await expect(page.locator('main [data-chart]')).toHaveCount(0);
      expect(mock.external).toEqual([]);
    });
  });
}
