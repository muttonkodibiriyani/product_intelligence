import type { Page, Route } from '@playwright/test';
import { categoryCompareBody, THIN, type Counts } from './category-compare-fixture';
import { summaryBlocked, summaryBody } from './summary-fixture';
import { expect, golden, mockBackend, noHorizontalScroll, signIn, test, type Mock } from './fixtures';

type Json = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any

const meta = golden('meta') as Json;
const compare = golden('compare') as Json;

/** Shop B's summary withheld: status not ok, a reason, counts null, no section drawn. */
const blockedB = { ...summaryBlocked, data: { ...summaryBlocked.data, retailer: 'shop_b' } };

/** /prices for shop_a vs shop_b: the summaries, the matched pairs and the category comparison. */
function api(counts: Counts = {}, withheld = false) {
  return async (route: Route) => {
    const u = new URL(route.request().url());
    const p = u.pathname;
    if (p === '/api/v1/meta') return route.fulfill({ json: meta });
    if (p === '/api/v1/summary')
      return route.fulfill({
        json: withheld && u.searchParams.get('retailer') === 'shop_b' ? blockedB : summaryBody,
      });
    if (p === '/api/v1/compare') return route.fulfill({ json: compare });
    if (p === '/api/v1/category-compare') {
      const [base, other] = (u.searchParams.get('retailers') ?? '').split(',');
      return route.fulfill({ json: categoryCompareBody(base, other, counts) });
    }
    return route.fulfill({ status: 404, json: { error: { code: 'not_found', message: 'no route' } } });
  };
}

async function open(page: Page, locale: 'en' | 'ar', counts: Counts = {}, withheld = false): Promise<Mock> {
  const mock = await mockBackend(page, { onApi: api(counts, withheld) });
  await signIn(page, locale);
  await expect(page.getByRole('navigation')).toBeVisible();
  await page.goto(`/app/${locale}/prices/`);
  return mock;
}

const isPhone = () => test.info().project.name.includes('mobile');

/** Charts the redesign dropped from Prices: the treemap, the heatmap, the shares, the gap list, the trend. */
const DROPPED = ['#p-mix', '#p-cross', '#p-share', '#p-rating', '#p-gaps', '#p-index', '#p-group-gap'];

for (const locale of ['en', 'ar'] as const) {
  const T =
    locale === 'ar'
      ? {
          title: 'الأسعار حسب الفئة',
          meta: /الكتالوج الكامل · 9 فئات مشتركة · /,
          headToHead: 'المنتجات المطابقة فقط',
          names: [
            'العطور',
            'العناية بالبشرة',
            'العيون',
            'الشفاه',
            'الجسم',
            'الخدود',
            'كريم الأساس',
            'الكونسيلر',
            'أخرى',
          ],
          tooFew: 'عدد قليل جدًا (n = 3)',
          tooFewList: /عدد قليل جدًا للمقارنة: الكونسيلر/,
          hist: 'توزيع الأسعار',
          ladder: 'سلّم الأسعار حسب الفئة',
          brands: 'تموضع أسعار العلامات التجارية',
          top5: 'أكبر 5',
          gapHist: 'توزيع فروق الأسعار',
          nPairs: 'n = 6 أزواج قابلة للمقارنة',
          // Arabic percentages carry LRM marks (50‎%‎); the retailer names stay as the API sent them.
          gapTakeaway:
            /Shop B أغلى في 50\u200e?%\u200e? من 6 أزواج مطابقة وأرخص في 33\.3\u200e?%\u200e?؛ و16\.7\u200e?%\u200e? في النطاق المحيط بالصفر\./,
          retailer: 'المتجر',
          noSummary: 'لا يوجد ملخص أسعار لـShop B بعد. هذا المتجر يمنع الجمع.',
        }
      : {
          title: 'Prices by category',
          meta: /Full catalogues · 9 shared categories · /,
          headToHead: 'Exact matches only',
          names: [
            'Fragrance',
            'Skincare',
            'Eyes',
            'Lips',
            'Body',
            'Cheek',
            'Foundation',
            'Concealer',
            'Other',
          ],
          tooFew: 'too few (n = 3)',
          tooFewList: /Too few to compare: Concealer/,
          hist: 'Price distribution',
          ladder: 'Price ladder by category',
          brands: 'Brand price positioning',
          top5: 'Top 5',
          gapHist: 'Spread of price gaps',
          nPairs: 'n = 6 comparable pairs',
          gapTakeaway:
            'Shop B is dearer on 50% of 6 matched pairs and cheaper on 33.3%; 16.7% sit in the band around zero.',
          retailer: 'Retailer',
          noSummary: 'No price summary for Shop B yet. This retailer blocks collection.',
        };

  test.describe(`${locale} prices`, () => {
    test('at most four charts, each led by a line computed from its own data; the treemap and heatmap are gone', async ({
      page,
    }) => {
      const mock = await open(page, locale);
      const hist = page.locator('#p-hist');
      await expect(hist.getByRole('heading', { name: T.hist })).toBeVisible();
      // summary-fixture: the 50–100 band holds 1,140 of the 4,812 products in the histogram.
      const histLine = hist.locator('[data-takeaway]');
      await expect(histLine).toContainText(/23\.7\u200e?%/);
      if (locale === 'en')
        await expect(histLine).toHaveText('The fullest band is AED 50 to AED 100: 23.7% of priced products.');

      const ladder = page.locator('#p-ladder');
      await expect(ladder.getByRole('heading', { name: T.ladder })).toBeVisible();
      // Medians are 3 × (30 + 12 i): Lipstick 90 at the bottom, Eyeshadow Palette 342 at the top.
      const ladderLine = ladder.locator('[data-takeaway]');
      await expect(ladderLine).toContainText('Lipstick');
      await expect(ladderLine).toContainText('Eyeshadow Palette');
      await expect(ladderLine).toContainText('90.00');
      await expect(ladderLine).toContainText('342.00');

      const brands = page.locator('#p-brands');
      await expect(brands.getByRole('heading', { name: T.brands })).toBeVisible();
      // Of the ten largest brands, Dior's median (240) is the highest and The Ordinary's (42) the lowest.
      const brandLine = brands.locator('[data-takeaway]');
      await expect(brandLine).toContainText('Dior');
      await expect(brandLine).toContainText('240.00');
      await expect(brandLine).toContainText('The Ordinary');
      await expect(brandLine).toContainText('42.00');
      // Narrowing to the five largest changes the line with the chart: Rare Beauty (99) is now the lowest.
      await brands.getByRole('button', { name: T.top5 }).click();
      await expect(page).toHaveURL(/[?&]top=5(&|$)/);
      await expect(brandLine).toContainText('Rare Beauty');
      await expect(brandLine).toContainText('99.00');
      await expect(brandLine).not.toContainText('The Ordinary');

      // Four drawings on the page, and none of the dropped ones.
      await expect(page.locator('[data-chart]')).toHaveCount(4);
      for (const id of DROPPED) await expect(page.locator(id)).toHaveCount(0);

      if (isPhone()) await noHorizontalScroll(page);
      expect(mock.errors).toEqual([]);
      expect(mock.external).toEqual([]);
    });

    test('by category leads the pair: all 9 shared categories in a fixed order, other included, before exact matches', async ({
      page,
    }) => {
      const mock = await open(page, locale);
      const card = page.locator('#p-buckets');
      await expect(card.getByRole('heading', { name: T.title })).toBeVisible();
      await expect(card).toContainText(T.meta);
      await expect(card).not.toContainText(/finer|later|لاحقًا/i);

      const calls = mock.api
        .map((r) => new URL(r.url))
        .filter((u) => u.pathname === '/api/v1/category-compare');
      expect(calls.length).toBeGreaterThan(0);
      expect(calls[0]!.searchParams.get('retailers')).toBe('shop_a,shop_b');
      expect(calls[0]!.searchParams.get('level')).toBe('bucket');

      // The API ranks rows by count; the page keeps the owner's order.
      const names = isPhone()
        ? card.locator('ul li h3')
        : card.getByRole('table').locator('tbody th[scope=row]');
      await expect(names).toHaveText(T.names);
      // Nothing is too few at the live counts.
      await expect(card).not.toContainText(T.tooFew);
      // The table has no chart of its own any more: the gaps are drawn once, under exact matches.
      await expect(card.locator('[data-chart]')).toHaveCount(0);

      const byCategory = await page.locator('#by-category').boundingBox();
      const exact = page.getByRole('heading', { name: T.headToHead });
      await expect(exact).toBeVisible();
      expect(byCategory!.y).toBeLessThan((await exact.boundingBox())!.y);
      if (isPhone()) await noHorizontalScroll(page);
      expect(mock.errors).toEqual([]);
      expect(mock.external).toEqual([]);
    });

    test('a side with too few products says so with its n and its row has no gap', async ({ page }) => {
      const mock = await open(page, locale, THIN);
      const card = page.locator('#p-buckets');
      if (isPhone()) {
        const concealer = card.locator('ul li').filter({ hasText: T.names[7]! });
        await expect(concealer).toContainText(T.tooFew);
        await expect(concealer.locator('svg')).toHaveCount(1); // Shop A's range only.
      } else {
        const row = card.getByRole('table').locator('tbody tr').nth(7);
        await expect(row.locator('th')).toHaveText(T.names[7]!);
        const cells = row.locator('td');
        await expect(cells.nth(3)).toHaveText(T.tooFew);
        await expect(cells.nth(3).locator('svg')).toHaveCount(0);
        await expect(cells.last()).toHaveText('–');
      }
      await expect(card).toContainText(T.tooFewList);
      expect(mock.errors).toEqual([]);
    });

    test('a retailer whose summary is withheld says why: no blank chart, no zero', async ({ page }) => {
      const mock = await open(page, locale, {}, true);
      await expect(page.locator('#p-hist [data-takeaway]')).toBeVisible();
      await page.getByRole('group', { name: T.retailer }).getByRole('button', { name: 'Shop B' }).click();
      await expect(page).toHaveURL(/[?&]retailer=shop_b(&|$)/);
      const section = page.locator('section[aria-labelledby="per-retailer"]');
      await expect(section.getByRole('status')).toHaveText(T.noSummary);
      await expect(section.locator('[data-chart]')).toHaveCount(0);
      await expect(section.locator('[data-takeaway]')).toHaveCount(0);
      await expect(section.locator('dl')).toHaveCount(0);
      await expect(section).not.toContainText(/\b0\b/);
      // The pair's own charts are untouched by one side's summary.
      await expect(page.locator('#p-gap-hist [data-takeaway]')).toBeVisible();
      if (isPhone()) await noHorizontalScroll(page);
      expect(mock.errors).toEqual([]);
    });

    test('the spread of price gaps: every band of the served histogram, its split in one line, n beside it, under exact matches', async ({
      page,
    }) => {
      const mock = await open(page, locale);
      const section = page.locator('section[aria-labelledby="head-to-head"]');
      // Counts keep Latin digits in Arabic too (WebKit defaults ar to Arabic-Indic).
      await expect(section.getByRole('heading', { name: T.headToHead })).toBeVisible();
      await expect(section).toContainText(T.nPairs);

      const card = page.locator('#p-gap-hist');
      await expect(card.getByRole('heading', { name: T.gapHist })).toBeVisible();
      await expect(card).toContainText(T.nPairs);
      // Golden compare: of the 6 pairs, 3 sit in bands above zero, 2 below, 1 in the band astride it.
      await expect(card.locator('[data-takeaway]')).toHaveText(T.gapTakeaway);
      // ECharts' aria module replaces the label with its own data description once it renders.
      const chart = card.locator('[data-chart]');
      await expect(chart).toHaveAttribute('role', 'img');
      // One y-axis label per served band: 11 (zero bands included), each in the visible text.
      const bands = chart.locator('svg text').filter({ hasText: '%' });
      await expect(bands).toHaveCount(11);
      if (locale === 'en') await expect(bands.first()).toHaveText('< −50%');
      const exact = await page.getByRole('heading', { name: T.headToHead }).boundingBox();
      expect(exact!.y).toBeLessThan((await card.boundingBox())!.y);
      if (isPhone()) await noHorizontalScroll(page);
      expect(mock.errors).toEqual([]);
      expect(mock.external).toEqual([]);
    });
  });
}
