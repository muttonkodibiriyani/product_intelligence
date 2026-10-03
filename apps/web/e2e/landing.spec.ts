import type { Page, Route } from '@playwright/test';
import { categoryCompareBody, THIN } from './category-compare-fixture';
import {
  expect,
  golden,
  mockBackend,
  noCardOverflow,
  noHorizontalScroll,
  openNav,
  signIn,
  test,
} from './fixtures';
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
const index = golden('index');

type Json = Record<string, unknown>;
/** /promotions as the Promotions page reads it: each shop's share with the counts behind it. */
const promotionsGolden = golden('promotions') as Json & { data: Json };
const promotions = {
  ...promotionsGolden,
  status: 'ok',
  reason: null,
  caveats: [],
  data: {
    ...promotionsGolden.data,
    retailers: [
      { retailer: 'shop_a', n: 4790, onPromo: 881, share: '18.4', reason: null },
      { retailer: 'shop_b', n: 4680, onPromo: 562, share: '12.0', reason: null },
    ],
  },
};
/** /promotions when no shop's was-prices are collected: a reason per shop, never a share. */
const promotionsNone = {
  ...promotionsGolden,
  status: 'not_enough_data',
  reason: 'field_not_collected',
  caveats: [],
  data: {
    items: [],
    total: 0,
    truncated: false,
    retailers: ['shop_a', 'shop_b'].map((retailer) => ({
      retailer,
      n: 0,
      onPromo: 0,
      share: null,
      reason: 'field_not_collected',
    })),
  },
};
/** /launches per shop over the Launches page's 30-day window: two at Shop A, one at Shop B. */
const launchesGolden = golden('launches') as Json;
const launchItems: Record<string, { firstSeen: string; id: string; name: string; retailer: string }[]> = {
  shop_a: [
    { firstSeen: '2026-09-27', id: 'p12', name: 'Product p12', retailer: 'shop_a' },
    { firstSeen: '2026-09-20', id: 'p09', name: 'Product p09', retailer: 'shop_a' },
  ],
  shop_b: [{ firstSeen: '2026-09-29', id: 'p14', name: 'Product p14', retailer: 'shop_b' }],
};
const launchesFor = (retailer: string | null) => {
  const items = launchItems[retailer ?? ''] ?? [];
  return { ...launchesGolden, caveats: [], data: { items, total: items.length, truncated: false } };
};

/**
 * The Overview's requests: /meta, one /summary per retailer, the pair's /compare, /category-compare
 * and /index, /promotions and one /launches per shop. `summary` answers by the retailer asked
 * for; `categories: false` is a backend without the category route, which the page treats as not
 * available.
 */
const api =
  (
    summary: unknown | ((retailer: string | null) => unknown),
    {
      meta = goldenMeta,
      cmp = compare,
      categories = true,
      promo = promotions,
    }: { meta?: Meta; cmp?: unknown; categories?: boolean; promo?: unknown } = {},
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
    if (p === '/api/v1/index') return r.fulfill({ json: index });
    if (p === '/api/v1/promotions') return r.fulfill({ json: promo });
    if (p === '/api/v1/launches') return r.fulfill({ json: launchesFor(url.searchParams.get('retailer')) });
    return r.fulfill({ status: 404, json: { error: { code: 'not_found', message: 'no route' } } });
  };
const byShop = (a: unknown, b: unknown) => (retailer: string | null) => (retailer === 'shop_b' ? b : a);

/** The band's tiles wrap cleanly at every width the owner looks at, phone to desktop, EN and AR. */
const WIDTHS = [390, 768, 1024, 1440] as const;
async function bandFits(page: Page) {
  const { width, height } = page.viewportSize()!;
  for (const w of WIDTHS) {
    await page.setViewportSize({ width: w, height });
    await page.waitForTimeout(150);
    await noCardOverflow(page, '#kpi-band [data-tile]');
    await noHorizontalScroll(page);
  }
  await page.setViewportSize({ width, height });
}

for (const locale of ['en', 'ar'] as const) {
  const ar = locale === 'ar';
  const T = ar
    ? {
        title: 'نظرة عامة',
        early: 'قراءة مبكرة:',
        earlyNote: 'عناصر العينة المبكرة غير المحتسبة: 1.',
        lead: 'Shop A أرخص في 3 من 6 منتجات مطابَقة. Shop B أرخص في 2، و1 بالسعر نفسه.',
        of: '6 من 15',
        scope: 'أي 6 من 15 منتجًا يبيعها أحد المتجرين؛ ولا يمكن مقارنة الباقي بعد.',
        see: 'اعرض المنتجات الـ6',
        noneYet: 'لا منتجات مطابَقة بعد',
        total: '15 إجمالًا',
        openCompare: 'افتح المقارنة',
        categoryLead: 'Shop B أرخص في 5 من 8 فئات',
        categoryNone: 'مقارنة الفئات غير متاحة بعد.',
        products: 'المنتجات',
        brands: 'العلامات',
        median: 'السعر الوسيط',
        none: 'غير مُقاس',
        promo: 'ضمن العروض',
        depth: 'عمق التخفيض',
        launches: 'المنتجات الجديدة',
        days: '30 يومًا',
        sparkA: 'Shop A: منتجان جديدان، لكل يوم',
        fresh: 'حديثة',
        asOf: /^حتى /,
        categories: 'أين يكون كل متجر أرخص',
        tooFew: 'عدد قليل جدًا (n = 3)',
        same: 'متساويان',
        cheaper: 'Shop B أرخص',
        basket: 'المنتجات المطابَقة وجهًا لوجه',
        tally: 'Shop A أرخص في 3، السعر نفسه في 1، Shop B أرخص في 2',
        top: 'أكبر التخفيضات',
        topAt: 'أعمق التخفيضات لدى Shop A',
        dataset: 'مجموعة البيانات الحالية',
        blocked: 'هذا المتجر يمنع الجمع.',
        noRetailers: 'لا يوجد متجر مُجمَّع لعرض بياناته.',
        about: 'عن البيانات',
        navDataset: 'البيانات',
        aboutP1: /تُجمع الأسعار من كل متجر/,
        partial: 'مُجمَّع جزئيًا',
        noImage: 'لا توجد صورة',
        credit: 'صور المنتجات: Sephora، من img-product.sephora.me.',
        creditUlta: 'صور المنتجات: Ulta Beauty، من media.alshaya.com.',
      }
    : {
        title: 'Overview',
        early: 'Early read:',
        earlyNote: '1 early sample item is not counted.',
        lead: 'Shop A is cheaper on 3 of the 6 matched products. Shop B is cheaper on 2; 1 costs the same.',
        of: '6 of 15',
        scope: 'That is 6 of the 15 products either shop sells; the rest cannot be compared yet.',
        see: 'See the 6 products',
        noneYet: 'No matched products yet',
        total: '15 in total',
        openCompare: 'Open compare',
        categoryLead: 'Shop B cheaper in 5 of 8 categories',
        categoryNone: 'Category comparison is not available yet.',
        products: 'Products',
        brands: 'Brands',
        median: 'Median price',
        none: 'Not measured',
        promo: 'On promotion',
        depth: 'Discount depth',
        launches: 'Launches',
        days: '30 days',
        sparkA: 'Shop A: 2 launches, per day',
        fresh: 'Fresh',
        asOf: /^as of /,
        categories: 'Where each shop is cheaper',
        tooFew: 'too few (n = 3)',
        same: 'same',
        cheaper: 'Shop B cheaper',
        basket: 'Matched products, head to head',
        tally: 'Shop A cheaper on 3, same price on 1, Shop B cheaper on 2',
        top: 'Top discounts',
        topAt: 'Deepest discounts at Shop A',
        dataset: 'Current dataset',
        blocked: 'This retailer blocks collection.',
        noRetailers: 'No collected retailer to report on.',
        about: 'About the data',
        navDataset: 'Dataset',
        aboutP1: /Prices are collected from each shop on the dates shown/,
        partial: 'Partly collected',
        noImage: 'No image',
        credit: 'Product images: Sephora, served from img-product.sephora.me.',
        creditUlta: 'Product images: Ulta Beauty, served from media.alshaya.com.',
      };
  const h2 = (page: Page, name: string) => page.getByRole('heading', { level: 2, name, exact: true });
  const tile = (page: Page, id: string) => page.locator(`#kpi-band [data-tile="${id}"]`);
  const tips = (page: Page, id: string) => tile(page, id).locator('[role=tooltip]');

  test.describe(locale, () => {
    test('two shops: the band, one line, where each is cheaper, the basket, the charts, the discounts', async ({
      page,
    }) => {
      const mock = await mockBackend(page, { onApi: api(byShop(shopA, shopB), { meta: twoShops }) });
      await signIn(page, locale);
      await expect(page.getByRole('heading', { level: 1, name: T.title })).toBeVisible();
      // One page: no Overview/Compare tabs any more; About the data is not on the Overview itself,
      // only the page footer's one link to the Dataset page.
      await expect(page.getByRole('tab')).toHaveCount(0);
      await expect(page.locator('main').getByRole('link', { name: T.about })).toHaveCount(0);
      await expect(page.locator('footer').getByRole('link', { name: T.about })).toHaveAttribute(
        'href',
        new RegExp(`/${locale}/dataset/#about-data$`),
      );

      // The band: a tile per shop, then promotions and launches. Each shop's /summary counts, the
      // freshness as a chip with its date in the tooltip, the tile linking to the shop's list.
      await expect(page.locator('#kpi-band [data-tile]')).toHaveCount(4);
      const a = tile(page, 'shop:shop_a');
      await expect(a).toContainText('4,812');
      await expect(a).toContainText('236');
      await expect(a).toContainText('61');
      await expect(a).toContainText('139.00');
      await expect(a).toContainText(/18\.4\u200e?%/);
      await expect(a.getByText(T.fresh, { exact: true })).toBeVisible();
      await expect(tips(page, 'shop:shop_a').filter({ hasText: T.asOf })).toHaveCount(1);
      await expect(a.getByRole('link', { name: 'Shop A' })).toHaveAttribute(
        'href',
        /\/explore\/\?.*retailer=shop_a/,
      );
      await expect(tile(page, 'shop:shop_b')).toContainText('4,700');
      await expect(tile(page, 'shop:shop_b')).toContainText(/12\u200e?%/);
      // Promotions: the Promotions page's share per shop, its counts in the tooltip, and the depth strip.
      const promo = tile(page, 'promotions');
      await expect(promo.getByRole('link', { name: T.promo })).toHaveAttribute('href', /\/promotions\/$/);
      await expect(promo).toContainText(/18\.4\u200e?%/);
      await expect(promo).toContainText(/12\u200e?%/);
      await expect(tips(page, 'promotions').filter({ hasText: '881' })).toHaveCount(1);
      await expect(promo.getByText(T.depth, { exact: true })).toBeVisible();
      await expect(promo.locator('[role=img] i[data-band]').first()).toBeVisible();
      // Launches: /launches per shop over the 30-day window, as a count and a sparkline per day.
      const launches = tile(page, 'launches');
      await expect(launches.getByRole('link', { name: T.launches })).toHaveAttribute('href', /\/launches\/$/);
      await expect(launches).toContainText(T.days);
      await expect(launches.locator(`[role=img][aria-label="${T.sparkA}"] i`)).toHaveCount(30);
      await expect(launches.locator('dd').filter({ hasText: /^2$/ })).toHaveCount(1);
      await expect(launches.locator('dd').filter({ hasText: /^1$/ })).toHaveCount(1);
      // No prose in the band: not one paragraph longer than a label.
      for (const text of await page.locator('#kpi-band p').allTextContents())
        expect(text.trim().split(/\s+/).length).toBeLessThanOrEqual(6);

      // The headline from /compare's own counts: 3 + 2 + 1 of 6, of the 15 products either shop
      // sells, the scope as a chip with its tooltip; "early" is a pill (the golden /compare carries
      // an early_excluded caveat), with the caveat as its tooltip, never a paragraph.
      const headline = page.locator('#headline-title');
      await expect(headline).toHaveText(T.lead);
      const sentence = page.locator('section', { has: headline });
      await expect(sentence.getByText(T.early, { exact: true })).toBeVisible();
      await expect(sentence.getByText(T.of, { exact: true })).toBeVisible();
      await expect(sentence.locator('[role=tooltip]').filter({ hasText: T.scope })).toHaveCount(1);
      await expect(sentence.locator('[role=tooltip]').filter({ hasText: T.earlyNote })).toHaveCount(1);
      await expect(sentence.locator('p')).toHaveCount(0);
      await expect(sentence).not.toContainText(/candidate|مرشح/);
      await expect(page.getByRole('link', { name: T.see, exact: true })).toHaveAttribute(
        'href',
        /\/compare\/\?retailers=shop_a(,|%2C)shop_b$/,
      );

      // Where each shop is cheaper: the finding as the title, nine category rows ranked by gap,
      // HTML only, with the API's gap on each; the method in the About tip, not under the table.
      const cats = page.locator('#w-categories');
      await expect(h2(page, T.categoryLead)).toBeVisible();
      await expect(cats).toContainText(T.categories);
      await expect(cats.getByRole('rowheader')).toHaveCount(9);
      await expect(cats.getByRole('rowheader').first()).toHaveText(ar ? 'الجسم' : 'Body');
      // The gap bar is in the cheaper shop's colour and names it; never a green/red verdict.
      await expect(cats.locator('.gapbar i[data-shop=shop_b]')).toHaveCount(5);
      await expect(cats.locator('.gapbar i[data-shop=shop_a]')).toHaveCount(2);
      await expect(cats.getByText(T.cheaper, { exact: true })).toHaveCount(5);
      await expect(cats.locator('[data-side], .text-good, .text-bad')).toHaveCount(0);
      await expect(cats.getByText(T.tooFew, { exact: true })).toBeVisible();
      await expect(cats.getByText(T.same, { exact: true })).toBeVisible();
      await expect(cats.locator('[role=tooltip]')).toHaveCount(1);
      await expect(cats.locator('table ~ p, tfoot')).toHaveCount(0);

      // The matched basket: both totals and the tally of who is cheaper how often.
      const basket = page.locator('#w-basket');
      await expect(h2(page, T.basket)).toBeVisible();
      await expect(basket.getByRole('img')).toHaveAttribute('aria-label', T.tally);
      await expect(basket).toContainText('580.75');
      await expect(basket).toContainText('600.00');

      // The insights: the pair's gaps by category (widest gap in the title), the index over time,
      // launches per day, then each shop's price bands, ladder, brands, share and discount depth.
      await expect(page.locator('#i-gaps')).toContainText('-10.9%');
      await expect(page.locator('#i-index')).toContainText('103.3');
      await expect(page.locator('#i-launches')).toContainText('30');
      for (const id of [
        'i-hist-0',
        'i-ladder-0',
        'i-brands-0',
        'i-share-0',
        'i-depth-0',
        'i-hist-1',
        'i-depth-1',
      ])
        await expect(page.locator(`#${id} [data-chart]`)).toHaveCount(1);
      expect(await page.locator('main [data-chart]').count()).toBeGreaterThanOrEqual(13);
      // Each insight is one headline and a chart: no explanatory paragraph under any of them.
      for (const id of ['i-gaps', 'i-index', 'i-launches', 'i-hist-0'])
        await expect(page.locator(`#${id} p`)).toHaveCount(1);

      // The deepest discounts, one card per shop, each row linking to its product.
      const top = page.locator('#w-top');
      await expect(h2(page, T.topAt)).toBeVisible();
      await expect(top.getByRole('rowheader')).toHaveCount(5);
      await expect(top.getByRole('link', { name: 'Pillow Talk Matte Revolution Lipstick' })).toHaveAttribute(
        'href',
        /\/app\/(en|ar)\/product\/\?id=p-2$/,
      );
      await expect(page.locator('#w-top-shop_b')).toBeVisible();

      // The dataset block lives on its own page now: not on the Overview.
      await expect(h2(page, T.dataset)).toHaveCount(0);
      await expect(page.locator('#dataset')).toHaveCount(0);
      await expect(page.locator('main [role=note]')).toHaveCount(0);
      await bandFits(page);
      expect(mock.external).toEqual([]);
      expect(mock.errors).toEqual([]);
    });

    test('no matched product yet: one quiet line of chips, the category read and the charts stay', async ({
      page,
    }) => {
      const mock = await mockBackend(page, {
        onApi: api(byShop(shopA, shopB), { meta: twoShops, cmp: compareEmpty }),
      });
      await signIn(page, locale);
      // Not a headline: a chip saying so, each side's observed count and the total as chips
      // (from /compare's own sides; with no summary there is no confirmed count, never "0"),
      // and the link to compare. The definition sits in the chip's tooltip.
      const line = page.locator('#no-match');
      await expect(line).toBeVisible();
      await expect(page.locator('#headline-title')).toHaveCount(0);
      await expect(line.getByText(T.noneYet, { exact: true })).toBeVisible();
      await expect(line.getByText('14', { exact: true })).toBeVisible();
      await expect(line.getByText('12', { exact: true })).toBeVisible();
      await expect(line.getByText(T.total, { exact: true })).toBeVisible();
      await expect(line).not.toContainText(/\b0\b|candidate|مرشح/);
      await expect(line.locator('[role=tooltip]')).toHaveCount(4);
      await expect(line.getByRole('link', { name: T.openCompare, exact: true })).toHaveAttribute(
        'href',
        /\/compare\/\?retailers=shop_a(,|%2C)shop_b$/,
      );
      // No basket without a matched product; the category table, the band and the charts stay.
      await expect(page.locator('#w-basket')).toHaveCount(0);
      await expect(h2(page, T.categoryLead)).toBeVisible();
      await expect(page.locator('#w-categories').getByRole('rowheader')).toHaveCount(9);
      await expect(page.locator('#kpi-band [data-tile]')).toHaveCount(4);
      await expect(page.locator('#i-gaps [data-chart]')).toHaveCount(1);
      await expect(page.locator('#i-hist-0 [data-chart]')).toHaveCount(1);
      await expect(h2(page, T.dataset)).toHaveCount(0);
      await bandFits(page);
      expect(mock.external).toEqual([]);
      expect(mock.errors).toEqual([]);
    });

    test('prices withheld, no category route: not measured as chips, never as zero, and no chart of it', async ({
      page,
    }) => {
      const withheld = (id: string) => asShop(summaryPricesWithheld as unknown as Summary, id);
      const mock = await mockBackend(page, {
        onApi: api(byShop(withheld('shop_a'), withheld('shop_b')), {
          meta: twoShops,
          categories: false,
          promo: promotionsNone,
        }),
      });
      await signIn(page, locale);
      await expect(page.locator('#headline-title')).toContainText(T.lead);
      // Each shop's median and promotion share, and the promotions tile's rows: one chip each
      // with the reason in its tooltip; the counts /summary did send stay.
      const a = tile(page, 'shop:shop_a');
      await expect(a).toContainText('4,812');
      await expect(a.getByText(T.none, { exact: true })).toHaveCount(2);
      await expect(tile(page, 'promotions').getByText(T.none, { exact: true })).toHaveCount(2);
      await expect(page.locator('#kpi-band')).not.toContainText('%');
      await expect(page.locator('#kpi-band')).not.toContainText(/\b0\b/);
      await expect(tile(page, 'promotions').getByText(T.depth, { exact: true })).toHaveCount(0);
      await expect(page.locator('#w-categories')).toContainText(T.categoryNone);
      await expect(page.locator('#w-top')).toHaveCount(0);
      // Nothing is charted from a withheld section: only the index and the launches draw.
      await expect(page.locator('#i-gaps')).toHaveCount(0);
      await expect(
        page.locator('[id^=i-hist-], [id^=i-ladder-], [id^=i-brands-], [id^=i-share-], [id^=i-depth-]'),
      ).toHaveCount(0);
      await expect(page.locator('#i-index [data-chart]')).toHaveCount(1);
      await expect(page.locator('#i-launches [data-chart]')).toHaveCount(1);
      await bandFits(page);
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
      const mock = await mockBackend(page, { onApi: api(byShop(shopA, shopB)) });
      await signIn(page, locale);
      // The footer's link to the data, before the nav is used.
      await expect(page.locator('footer').getByRole('link', { name: T.about })).toHaveAttribute(
        'href',
        new RegExp(`/${locale}/dataset/#about-data$`),
      );
      await openNav(page, T.navDataset);
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
      await expect(page.locator('main [role=note]:not(#dataset [role=note])')).toHaveCount(0);
      await noHorizontalScroll(page);
      expect(mock.external).toEqual([]);
      expect(mock.errors).toEqual([]);
    });
    test('a blocked retailer: one plain line with the link to the data; no note box, band, line or charts', async ({
      page,
    }) => {
      const mock = await mockBackend(page, { onApi: api(summaryBlocked) });
      await signIn(page, locale);
      await expect(page.getByRole('heading', { level: 1, name: T.title })).toBeVisible();
      await expect(page.getByText(T.noRetailers)).toBeVisible();
      await expect(page.getByText(T.noRetailers).getByRole('link', { name: T.about })).toHaveAttribute(
        'href',
        new RegExp(`/${locale}/dataset/#about-data$`),
      );
      await expect(page.locator('main')).not.toContainText(T.blocked);
      await expect(page.locator('main [role=note]')).toHaveCount(0);
      await expect(h2(page, T.dataset)).toHaveCount(0);
      await expect(page.locator('#kpi-band')).toHaveCount(0);
      await expect(page.locator('#headline-title, #no-match')).toHaveCount(0);
      await expect(page.locator('main [data-chart]')).toHaveCount(0);
      expect(mock.external).toEqual([]);
    });
  });
}
