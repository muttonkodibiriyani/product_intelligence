import type { Page, Route } from '@playwright/test';
import { categoryCompareBody, THIN, wideCategoryCompareBody, type Counts } from './category-compare-fixture';
import { summaryBlocked, summaryBody } from './summary-fixture';
import { expect, golden, mockBackend, noHorizontalScroll, signedIn, test, type Mock } from './fixtures';

type Json = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any

const meta = golden('meta') as Json;
const compare = golden('compare') as Json;

/** Shop B's summary withheld: status not ok, a reason, counts null, no section drawn. */
const blockedB = { ...summaryBlocked, data: { ...summaryBlocked.data, retailer: 'shop_b' } };

/** /prices for shop_a vs shop_b: the summaries, the matched pairs and the category comparison. */
function api(counts: Counts = {}, withheld = false, wide = false) {
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
      return route.fulfill({
        json: wide ? wideCategoryCompareBody(base, other) : categoryCompareBody(base, other, counts),
      });
    }
    return route.fulfill({ status: 404, json: { error: { code: 'not_found', message: 'no route' } } });
  };
}

async function open(
  page: Page,
  locale: 'en' | 'ar',
  counts: Counts = {},
  withheld = false,
  wide = false,
): Promise<Mock> {
  const mock = await mockBackend(page, { onApi: api(counts, withheld, wide) });
  await signedIn(page, locale);
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
          gapLabel: 'الأزواج المطابقة لكل نطاق فرق سعر، 11 نطاقًا.',
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
          gapLabel: 'Matched pairs per price-gap band, 11 bands.',
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

    test('the Price range axis reads across four decades: no two labels overlap, each stays in its column', async ({
      page,
    }) => {
      test.skip(isPhone(), 'the phone shows stacked cards with no shared axis');
      const mock = await open(page, locale, {}, false, true);
      const head = page.locator('#p-buckets thead');
      await expect(head.locator('svg text').first()).toBeVisible();
      const axes = await head.locator('svg').all();
      expect(axes).toHaveLength(2);
      for (const svg of axes) {
        // Measured in the page: WebKit's Playwright boundingBox() puts every SVG <text> at the svg's
        // left edge (its width is right), which reads as an overlap that is not on screen.
        const { cell, boxes } = await svg.evaluate((el) => {
          const box = (r: DOMRect) => ({ x: r.x, width: r.width });
          return {
            cell: box(el.closest('th')!.getBoundingClientRect()),
            boxes: [...el.querySelectorAll('text')].map((t) => box(t.getBoundingClientRect())),
          };
        });
        boxes.sort((a, b) => a.x - b.x);
        expect(boxes.length).toBeGreaterThanOrEqual(2);
        for (const b of boxes) {
          expect(b.x).toBeGreaterThanOrEqual(cell.x);
          expect(b.x + b.width).toBeLessThanOrEqual(cell.x + cell.width);
        }
        for (let i = 1; i < boxes.length; i++)
          expect(boxes[i]!.x).toBeGreaterThan(boxes[i - 1]!.x + boxes[i - 1]!.width);
      }
      // Every column title sits on one line: Category, n, Median, Price range, Median gap.
      const tops = await head
        .locator('tr')
        .nth(1)
        .locator('th')
        .evaluateAll((ths) =>
          ths.map((th) => {
            const r = document.createRange();
            r.selectNodeContents(th.querySelector('span') ?? th);
            return Math.round(r.getClientRects()[0]!.top);
          }),
        );
      expect(tops).toHaveLength(8);
      expect(new Set(tops).size).toBe(1);
      expect(mock.errors).toEqual([]);
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
      // ECharts' aria module would replace the label with its own English data description; the
      // chart's translated label stays, once the chart has drawn too.
      const chart = card.locator('[data-chart]');
      await expect(chart).toHaveAttribute('role', 'img');
      await expect(chart.locator('svg')).toHaveCount(1);
      await expect(chart).toHaveAttribute('aria-label', T.gapLabel);
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

/**
 * The five live retailer ids, each with its own product count, so a page that showed another
 * retailer's summary under the asked-for id could not pass.
 */
const FIVE = { ulta_ae: 701, sephora_me: 502, faces_ae: 303, ounass_ae: 404, bloomingdales_ae: 905 };
const meta5 = {
  ...meta,
  data: {
    ...meta.data,
    retailers: Object.keys(FIVE).map((id) => ({
      country: 'AE',
      id,
      name: id,
      note: null,
      since: '2026-09-01',
      status: 'supported',
    })),
  },
};

function api5() {
  return async (route: Route) => {
    const u = new URL(route.request().url());
    const p = u.pathname;
    if (p === '/api/v1/meta') return route.fulfill({ json: meta5 });
    if (p === '/api/v1/summary') {
      const id = u.searchParams.get('retailer') as keyof typeof FIVE;
      return route.fulfill({
        json: { ...summaryBody, data: { ...summaryBody.data, retailer: id, products: FIVE[id] } },
      });
    }
    if (p === '/api/v1/compare') return route.fulfill({ json: compare });
    if (p === '/api/v1/category-compare') {
      const [base, other] = (u.searchParams.get('retailers') ?? '').split(',');
      return route.fulfill({ json: categoryCompareBody(base, other, {}) });
    }
    return route.fulfill({ status: 404, json: { error: { code: 'not_found', message: 'no route' } } });
  };
}

for (const locale of ['en', 'ar'] as const) {
  const T =
    locale === 'ar'
      ? {
          retailer: 'المتجر',
          products: 'المنتجات المتتبَّعة',
          unknown: 'يشير هذا الرابط إلى متجر لا تتوفر له بيانات أسعار هنا. اختر متجرًا من الأعلى.',
        }
      : {
          retailer: 'Retailer',
          products: 'Products tracked',
          unknown: 'This link names a retailer with no price data here. Pick one above.',
        };

  test.describe(`${locale} prices: the retailer in the link`, () => {
    async function at(page: Page, q: string): Promise<Mock> {
      const mock = await mockBackend(page, { onApi: api5() });
      await signedIn(page, locale);
      await page.goto(`/app/${locale}/prices/${q}`);
      return mock;
    }
    const section = (page: Page) => page.locator('section[aria-labelledby="per-retailer"]');
    const picker = (page: Page) => section(page).getByRole('group', { name: T.retailer });

    test("an id the API doesn't serve says so and shows no other retailer's number", async ({ page }) => {
      // sephora_ae is an old alias, not a served id; "nope" is a typo.
      const mock = await at(page, '?retailer=sephora_ae');
      for (const q of ['?retailer=sephora_ae', '?retailer=nope']) {
        if (q !== '?retailer=sephora_ae') await page.goto(`/app/${locale}/prices/${q}`);
        await expect(section(page).getByRole('status')).toHaveText(T.unknown);
        await expect(section(page).getByText(T.products)).toHaveCount(0);
        await expect(section(page).locator('dl')).toHaveCount(0);
        // No shop is pressed: the page has not picked one for the reader.
        await expect(picker(page).locator('[aria-pressed="true"]')).toHaveCount(0);
      }
      // Choosing one from there shows that one.
      await picker(page).getByRole('button', { name: 'Faces' }).click();
      await expect(page).toHaveURL(/[?&]retailer=faces_ae(&|$)/);
      await expect(section(page).locator('dd').first()).toHaveText('303');
      await expect(section(page).getByRole('status')).toHaveCount(0);
      expect(mock.errors).toEqual([]);
    });

    test('?retailer=sephora_me shows Sephora and its own count, not the first retailer', async ({ page }) => {
      const mock = await at(page, '?retailer=sephora_me');
      await expect(picker(page).getByRole('button', { name: 'Sephora' })).toHaveAttribute(
        'aria-pressed',
        'true',
      );
      await expect(section(page).locator('dd').first()).toHaveText('502');
      expect(mock.errors).toEqual([]);
    });

    test('choosing the first retailer clears the link and shows it because it was chosen', async ({
      page,
    }) => {
      const mock = await at(page, '?retailer=ounass_ae');
      await expect(section(page).locator('dd').first()).toHaveText('404');
      await picker(page).getByRole('button', { name: 'Ulta' }).click();
      await expect(page).not.toHaveURL(/[?&]retailer=/);
      await expect(picker(page).getByRole('button', { name: 'Ulta' })).toHaveAttribute(
        'aria-pressed',
        'true',
      );
      await expect(section(page).locator('dd').first()).toHaveText('701');
      await expect(section(page).getByRole('status')).toHaveCount(0);
      expect(mock.errors).toEqual([]);
    });
  });
}
