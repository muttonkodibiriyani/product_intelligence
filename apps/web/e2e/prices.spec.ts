import type { Page, Route } from '@playwright/test';
import { categoryCompareBody, THIN, type Counts } from './category-compare-fixture';
import {
  expect,
  golden,
  mockBackend,
  noHorizontalScroll,
  signIn,
  test,
  withSummary,
  type Mock,
} from './fixtures';

type Json = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any

const meta = golden('meta') as Json;
const compare = golden('compare') as Json;
const index = golden('index') as Json;

/** /prices for shop_a vs shop_b: the summaries, the matched pairs and the category comparison. */
function api(counts: Counts = {}) {
  return withSummary(async (route: Route) => {
    const u = new URL(route.request().url());
    const p = u.pathname;
    if (p === '/api/v1/meta') return route.fulfill({ json: meta });
    if (p === '/api/v1/compare') return route.fulfill({ json: compare });
    if (p === '/api/v1/index') return route.fulfill({ json: index });
    if (p === '/api/v1/category-compare') {
      const [base, other] = (u.searchParams.get('retailers') ?? '').split(',');
      return route.fulfill({ json: categoryCompareBody(base, other, counts) });
    }
    return route.fulfill({ status: 404, json: { error: { code: 'not_found', message: 'no route' } } });
  });
}

async function open(page: Page, locale: 'en' | 'ar', counts: Counts = {}): Promise<Mock> {
  const mock = await mockBackend(page, { onApi: api(counts) });
  await signIn(page, locale);
  await expect(page.getByRole('navigation')).toBeVisible();
  await page.goto(`/app/${locale}/prices/`);
  return mock;
}

const isPhone = () => test.info().project.name.includes('mobile');

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
          gapHist: 'توزيع فروق الأسعار',
          gapHistMeta: 'n = 6 أزواج قابلة للمقارنة',
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
          gapHist: 'Spread of price gaps',
          gapHistMeta: 'n = 6 comparable pairs',
        };

  test.describe(`${locale} prices by category`, () => {
    test('leads the page: all 9 shared categories in a fixed order, other included, before exact matches', async ({
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

      const byCategory = await page.locator('#by-category').boundingBox();
      const exact = page.getByRole('heading', { name: T.headToHead });
      await expect(exact).toBeVisible();
      expect(byCategory!.y).toBeLessThan((await exact.boundingBox())!.y);
      if (isPhone()) await noHorizontalScroll(page);
      expect(mock.errors).toEqual([]);
      expect(mock.external).toEqual([]);
    });

    test('a side with too few products says so with its n; its row has no gap and it stays off the chart', async ({
      page,
    }) => {
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

    test('the spread of price gaps: every band of the served histogram, under exact matches', async ({
      page,
    }) => {
      const mock = await open(page, locale);
      const card = page.locator('#p-gap-hist');
      await expect(card.getByRole('heading', { name: T.gapHist })).toBeVisible();
      await expect(card).toContainText(T.gapHistMeta);
      // ECharts' aria module replaces the label with its own data description once it renders.
      const chart = card.locator('[data-chart]');
      await expect(chart).toHaveAttribute('role', 'img');
      // One y-axis label per served band: 11 (zero bands included), each in the visible text.
      const bands = chart.locator('svg text').filter({ hasText: '%' });
      await expect(bands).toHaveCount(11);
      if (locale === 'en') await expect(bands.first()).toHaveText('< \u221250%');
      const exact = await page.getByRole('heading', { name: T.headToHead }).boundingBox();
      expect(exact!.y).toBeLessThan((await card.boundingBox())!.y);
      if (isPhone()) await noHorizontalScroll(page);
      expect(mock.errors).toEqual([]);
      expect(mock.external).toEqual([]);
    });
  });
}
