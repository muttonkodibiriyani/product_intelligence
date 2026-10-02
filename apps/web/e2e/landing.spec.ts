import type { Page, Route } from '@playwright/test';
import { categoryCompareBody, THIN } from './category-compare-fixture';
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
  summaryPricesWithheld,
  summaryUlta,
} from './summary-fixture';

// The smallest valid PNG: one transparent pixel.
const PNG = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=',
  'base64',
);

type Meta = { data: { retailers: { id: string; status: string }[] } };
const goldenMeta = golden('meta') as Meta;
/** The golden /meta with shop_c blocked, so the Overview reports on exactly the pair shop_a/shop_b. */
const twoShops: Meta = {
  ...goldenMeta,
  data: {
    ...goldenMeta.data,
    retailers: goldenMeta.data.retailers.map((r) => (r.id === 'shop_c' ? { ...r, status: 'blocked' } : r)),
  },
};

type Summary = typeof summaryBody;
/** A /summary body as one of the pair's shops, with its own counts. */
const asShop = (body: Summary, retailer: string, data: Partial<Summary['data']> = {}): Summary => ({
  ...body,
  data: { ...body.data, retailer, ...data },
  meta: { ...body.meta, filters: { retailer } },
});
const shopA = asShop(summaryBody, 'shop_a');
const shopB = asShop(summaryBody, 'shop_b', { products: 4700, priced: 4680, promoSharePct: '12.0' });

const compare = golden('compare') as { data: { summary: unknown; rows: unknown[] } };
/** /compare with no matched product yet: the API's candidate and observed counts, no summary. */
const compareEmpty = { ...compare, data: { ...compare.data, summary: null, rows: [] } };

/**
 * The Overview's four requests: /meta, one /summary per retailer, and the pair's /compare and
 * /category-compare. `summary` answers by the retailer asked for; `categories: false` is a
 * backend without the category route, which the page treats as not available.
 */
const api =
  (
    summary: unknown | ((retailer: string | null) => unknown),
    {
      meta = goldenMeta,
      cmp = compare,
      categories = true,
    }: { meta?: Meta; cmp?: unknown; categories?: boolean } = {},
  ) =>
  async (r: Route) => {
    const url = new URL(r.request().url());
    const p = url.pathname;
    if (p === '/api/v1/summary')
      return r.fulfill({
        json: typeof summary === 'function' ? summary(url.searchParams.get('retailer')) : summary,
      });
    if (p === '/api/v1/meta') return r.fulfill({ json: meta });
    if (p === '/api/v1/compare') return r.fulfill({ json: cmp });
    if (p === '/api/v1/category-compare' && categories)
      return r.fulfill({ json: categoryCompareBody('shop_a', 'shop_b', THIN) });
    return r.fulfill({ status: 404, json: { error: { code: 'not_found', message: 'no route' } } });
  };
const byShop = (a: unknown, b: unknown) => (retailer: string | null) => (retailer === 'shop_b' ? b : a);

for (const locale of ['en', 'ar'] as const) {
  const ar = locale === 'ar';
  const T = ar
    ? {
        title: 'نظرة عامة',
        early: 'قراءة مبكرة:',
        lead: 'Shop A أرخص في 3 من 6 منتجات مطابَقة. Shop B أرخص في 2، و1 بالسعر نفسه.',
        see: 'اعرض المنتجات الـ6',
        emptyTitle: 'لا توجد منتجات مطابَقة بين Shop A وShop B بعد.',
        categoryRead: 'بحسب الأسعار الوسيطة للفئات، Shop B أرخص في 5 من 8 فئات مقارَنة.',
        categoryNone: 'مقارنة الفئات غير متاحة بعد.',
        observed: 'منتجًا مرصودًا',
        confirmed: '0 مؤكدة كمطابقات',
        openPrices: 'قارن حسب الفئة',
        browse: 'تصفح كل المنتجات',
        products: 'المنتجات المتتبَّعة',
        more: 'Shop A يعرض 112 منتجًا أكثر',
        byCategory: 'السعر الوسيط حسب الفئة',
        catCheaper: 'من 8 فئة أرخص لدى Shop B',
        median: 'السعر الوسيط',
        none: 'غير مُقاس',
        promo: 'ضمن العروض',
        deepest: /أعمق تخفيض 50.{0,4}، لدى Shop A/,
        collected: /جُمعت بيانات Shop A في /,
        categories: 'أين يكون كل متجر أرخص',
        tooFew: 'عدد قليل جدًا (n = 3)',
        same: 'متساويان',
        basket: 'المنتجات المطابَقة وجهًا لوجه',
        tally: 'Shop A أرخص في 3، السعر نفسه في 1، Shop B أرخص في 2',
        top: 'أكبر التخفيضات',
        topAt: 'أعمق التخفيضات لدى Shop A',
        dataset: 'مجموعة البيانات الحالية',
        blocked: 'هذا المتجر يمنع الجمع.',
        noImage: 'لا توجد صورة',
        credit: 'صور المنتجات: Sephora، من img-product.sephora.me.',
        creditUlta: 'صور المنتجات: Ulta Beauty، من media.alshaya.com.',
      }
    : {
        title: 'Overview',
        early: 'Early read:',
        lead: 'Shop A is cheaper on 3 of the 6 matched products. Shop B is cheaper on 2; 1 costs the same.',
        see: 'See the 6 products',
        emptyTitle: 'No products are matched between Shop A and Shop B yet.',
        categoryRead: 'By category medians, Shop B is cheaper in 5 of the 8 compared categories.',
        categoryNone: 'Category comparison is not available yet.',
        observed: 'products seen',
        confirmed: '0 confirmed as matches',
        openPrices: 'Compare by category',
        browse: 'Browse all products',
        products: 'Products tracked',
        more: 'Shop A lists 112 more products',
        byCategory: 'Median price by category',
        catCheaper: 'of 8 categories cheaper at Shop B',
        median: 'Median price',
        none: 'Not measured',
        promo: 'On promotion',
        deepest: /Deepest cut 50% off, at Shop A/,
        collected: /Shop A collected /,
        categories: 'Where each shop is cheaper',
        tooFew: 'too few (n = 3)',
        same: 'same',
        basket: 'Matched products, head to head',
        tally: 'Shop A cheaper on 3, same price on 1, Shop B cheaper on 2',
        top: 'Top discounts',
        topAt: 'Deepest discounts at Shop A',
        dataset: 'Current dataset',
        blocked: 'This retailer blocks collection.',
        noImage: 'No image',
        credit: 'Product images: Sephora, served from img-product.sephora.me.',
        creditUlta: 'Product images: Ulta Beauty, served from media.alshaya.com.',
      };
  const h2 = (page: Page, name: string) => page.getByRole('heading', { level: 2, name, exact: true });
  const tile = (page: Page, k: string) =>
    page.locator('#kpi-band dl > div').filter({ has: page.getByText(k, { exact: true }) });

  test.describe(locale, () => {
    test('two shops: one sentence, four numbers, where each is cheaper, the basket, the discounts', async ({
      page,
    }) => {
      const mock = await mockBackend(page, { onApi: api(byShop(shopA, shopB), { meta: twoShops }) });
      await signIn(page, locale);
      await expect(page.getByRole('heading', { level: 1, name: T.title })).toBeVisible();
      // One page: no Overview/Compare tabs any more.
      await expect(page.getByRole('tab')).toHaveCount(0);

      // The headline from /compare's own counts: 3 + 2 + 1 of 6, out of 15 candidate pairs.
      const headline = page.locator('#headline-title');
      await expect(headline).toHaveText(`${T.early} ${T.lead}`);
      await expect(page.getByRole('link', { name: T.see, exact: true })).toHaveAttribute(
        'href',
        /\/compare\/\?retailers=shop_a(,|%2C)shop_b$/,
      );

      // The band: one hero per card, both shops under it, and who leads from the two values shown.
      await expect(page.locator('#kpi-band dl > div')).toHaveCount(4);
      await expect(tile(page, T.products)).toContainText('9,512');
      await expect(tile(page, T.products)).toContainText(T.more);
      await expect(tile(page, T.byCategory)).toContainText('5');
      await expect(tile(page, T.byCategory)).toContainText(T.catCheaper);
      await expect(tile(page, T.median)).toHaveCount(0);
      await expect(tile(page, T.promo)).toContainText('18.4');
      await expect(tile(page, T.promo)).toContainText('12');
      await expect(tile(page, T.promo)).toContainText(T.deepest);
      await expect(page.locator('#kpi-band')).toContainText(T.collected);

      // Where each shop is cheaper: nine category rows, HTML only, with the API's gap on each.
      const cats = page.locator('#w-categories');
      await expect(h2(page, T.categories)).toBeVisible();
      await expect(cats.getByRole('rowheader')).toHaveCount(9);
      await expect(cats.locator('.gapbar i[data-side=good]')).toHaveCount(5);
      await expect(cats.locator('.gapbar i[data-side=bad]')).toHaveCount(2);
      await expect(cats.getByText(T.tooFew, { exact: true })).toBeVisible();
      await expect(cats.getByText(T.same, { exact: true })).toBeVisible();

      // The matched basket: both totals and the tally of who is cheaper how often.
      const basket = page.locator('#w-basket');
      await expect(h2(page, T.basket)).toBeVisible();
      await expect(basket.getByRole('img')).toHaveAttribute('aria-label', T.tally);
      await expect(basket).toContainText('580.75');
      await expect(basket).toContainText('600.00');

      // The deepest discounts, one card per shop, each row linking to its product.
      const top = page.locator('#w-top');
      await expect(h2(page, T.topAt)).toBeVisible();
      await expect(top.getByRole('rowheader')).toHaveCount(5);
      await expect(top.getByRole('link', { name: 'Pillow Talk Matte Revolution Lipstick' })).toHaveAttribute(
        'href',
        /\/app\/(en|ar)\/product\/\?id=p-2$/,
      );
      await expect(page.locator('#w-top-shop_b')).toBeVisible();

      // No chart on the Overview; the dataset panel closes the page.
      await expect(page.locator('main [data-chart]')).toHaveCount(0);
      await expect(h2(page, T.dataset)).toBeVisible();
      await noHorizontalScroll(page);
      expect(mock.external).toEqual([]);
      expect(mock.errors).toEqual([]);
    });

    test('no matched product yet: it says so, what each side has ready, and the category read', async ({
      page,
    }) => {
      const mock = await mockBackend(page, {
        onApi: api(byShop(shopA, shopB), { meta: twoShops, cmp: compareEmpty }),
      });
      await signIn(page, locale);
      await expect(page.locator('#headline-title')).toHaveText(T.emptyTitle);
      const headline = page.locator('section', { has: page.locator('#headline-title') });
      await expect(headline).toContainText(T.categoryRead);
      // Readiness from /compare's own sides: what each shop has observed, and the candidate pairs.
      const tiles = headline.getByRole('listitem');
      await expect(tiles).toHaveCount(3);
      await expect(tiles.nth(0)).toContainText('14');
      await expect(tiles.nth(0)).toContainText(T.observed);
      await expect(tiles.nth(1)).toContainText('12');
      await expect(tiles.nth(2)).toContainText('15');
      await expect(tiles.nth(2)).toContainText(T.confirmed);
      await expect(headline.getByRole('link', { name: T.openPrices, exact: true })).toHaveAttribute(
        'href',
        /\/prices\/$/,
      );
      await expect(headline.getByRole('link', { name: T.browse, exact: true })).toHaveAttribute(
        'href',
        /\/explore\/$/,
      );
      // No basket without a matched product; the category table and the band stay.
      await expect(page.locator('#w-basket')).toHaveCount(0);
      await expect(h2(page, T.categories)).toBeVisible();
      await expect(page.locator('#kpi-band dl > div')).toHaveCount(4);
      await expect(h2(page, T.dataset)).toBeVisible();
      await noHorizontalScroll(page);
      expect(mock.external).toEqual([]);
      expect(mock.errors).toEqual([]);
    });

    test('prices withheld, no category route: the median reads as not measured, never as zero', async ({
      page,
    }) => {
      const withheld = (id: string) => asShop(summaryPricesWithheld as unknown as Summary, id);
      const mock = await mockBackend(page, {
        onApi: api(byShop(withheld('shop_a'), withheld('shop_b')), { meta: twoShops, categories: false }),
      });
      await signIn(page, locale);
      await expect(page.locator('#headline-title')).toContainText(T.lead);
      // Without the category comparison the second card is the median, and nothing is measured.
      const median = tile(page, T.median);
      await expect(median.locator('dd').first()).toHaveText(T.none);
      await expect(tile(page, T.byCategory)).toHaveCount(0);
      await expect(tile(page, T.promo).locator('dd').first()).toHaveText(T.none);
      await expect(page.locator('#kpi-band')).not.toContainText('%');
      await expect(page.locator('#w-categories')).toContainText(T.categoryNone);
      await expect(page.locator('#w-top')).toHaveCount(0);
      await expect(page.locator('main [data-chart]')).toHaveCount(0);
      await noHorizontalScroll(page);
      expect(mock.external).toEqual([]);
      expect(mock.errors.filter((e) => !/404/.test(e))).toEqual([]);
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
      // A retailer /meta doesn't name (sephora_me) still renders, by its id.
      await expect(page.getByRole('heading', { level: 1, name: T.title })).toBeVisible();
      await expect(page.locator('main').getByText('sephora_me').first()).toBeVisible();
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

    test('a blocked retailer: why, and the dataset; no sentence, tiles or charts', async ({ page }) => {
      const mock = await mockBackend(page, { onApi: api(summaryBlocked) });
      await signIn(page, locale);
      await expect(page.getByRole('heading', { level: 1, name: T.title })).toBeVisible();
      await expect(page.getByRole('note').filter({ hasText: T.blocked })).toBeVisible();
      await expect(h2(page, T.dataset)).toBeVisible();
      await expect(page.locator('#headline-title')).toHaveCount(0);
      await expect(page.getByText(T.products, { exact: true })).toHaveCount(0);
      await expect(page.locator('main [data-chart]')).toHaveCount(0);
      expect(mock.external).toEqual([]);
    });
  });
}
