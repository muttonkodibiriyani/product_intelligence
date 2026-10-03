import type { Page, Route } from '@playwright/test';
import { categoryCompareBody } from './category-compare-fixture';
import { expect, golden, mockBackend, noHorizontalScroll, signIn, test, type Mock } from './fixtures';

type Json = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any

const meta = golden('meta') as Json;
const compare = golden('compare') as Json; // shop_a vs shop_b by brand: 15 rows, 6 matched, median +2.4
const limited = golden('compare-limited') as Json; // the same, cut to 3 of 15
const blocked = golden('compare-blocked') as Json; // shop_a vs shop_d: shop_d blocked, no summary
const product = golden('product') as Json;
const history = golden('history') as Json;

/** The pair collected on both sides with nothing matched yet: every row left out, n = 0. */
const unmatched: Json = {
  ...compare,
  data: {
    ...compare.data,
    rows: compare.data.rows.filter((r: Json) => !r.counted),
    summary: { ...compare.data.summary, n: 0, cheaperCounts: {}, equalCount: 0 },
    sides: {
      base: { ...compare.data.sides.base, counted: 0 },
      other: { ...compare.data.sides.other, counted: 0 },
    },
  },
};

const CSV = 'id,name\np05,Product p05\n';

function api(compareFor: (u: URL) => Json = () => compare, categories = false) {
  return async (route: Route) => {
    const u = new URL(route.request().url());
    const p = u.pathname;
    if (p === '/api/v1/meta') return route.fulfill({ json: meta });
    if (p === '/api/v1/compare') return route.fulfill({ json: compareFor(u) });
    if (p === '/api/v1/category-compare' && categories) {
      const [base, other] = (u.searchParams.get('retailers') ?? '').split(',');
      return route.fulfill({ json: categoryCompareBody(base, other) });
    }
    if (p === '/api/v1/export/compare')
      return route.fulfill({
        status: 200,
        headers: {
          'content-type': 'text/csv; charset=utf-8',
          'content-disposition': 'attachment; filename="pi-compare.csv"',
        },
        body: CSV,
      });
    if (/^\/api\/v1\/products\/[^/]+\/history$/.test(p)) return route.fulfill({ json: history });
    if (/^\/api\/v1\/products\/[^/]+$/.test(p)) return route.fulfill({ json: product });
    return route.fulfill({ status: 404, json: { error: { code: 'not_found', message: 'no route' } } });
  };
}

async function signedIn(page: Page, locale: 'en' | 'ar') {
  await signIn(page, locale);
  await expect(page.getByRole('navigation')).toBeVisible();
}

const calls = (mock: Mock, path: string) =>
  mock.api.map((r) => new URL(r.url)).filter((u) => u.pathname === path);
const compareCalls = (mock: Mock) => calls(mock, '/api/v1/compare');

for (const locale of ['en', 'ar'] as const) {
  const T =
    locale === 'ar'
      ? {
          nav: 'المقارنة',
          title: 'المقارنة',
          pick: 'اختر متجرين للمقارنة.',
          base: 'المتجر الأول',
          other: 'المتجر الثاني',
          groupBy: 'التجميع حسب',
          verdict: 'Shop A أرخص في 3 من 6 منتجات متطابقة؛ وShop B أرخص في 2، ومنتج واحد بالسعر نفسه.',
          matchedTitle: 'المنتجات المتطابقة (6)',
          fold: 'تعذّرت مقارنة 9 منتجات أخرى',
          show: 'اعرضها',
          hide: 'أخفِها',
          notSold: 'يبيعه Shop A فقط.',
          tooSmall: 'عدد المنتجات قليل جدًا',
          of15: 'يظهر 3 من 15 منتجًا',
          more: 'اعرض حتى 500',
          emptyPair: 'لا منتجات متطابقة بين Shop A وShop B بعد',
          p05: 'Shop B، أغلى بنسبة 25',
          reasonLead: 'لا يمكن مقارنة شيء لهذين المتجرين.',
          blocks: 'هذا المتجر يمنع الجمع.',
          detail: 'تعذّر جمع بيانات أحد المتاجر المحددة.',
          blocked: 'محظور',
          seen14: '14 منتجًا مرصودًا',
          awaiting: 'بانتظار المراجعة',
          prices: 'اعرض الأسعار حسب الفئة بدلًا من ذلك',
          peek: 'متاح الآن: السعر الوسيط حسب الفئة',
          open: 'العرضان',
          back: 'العودة إلى المقارنة',
          brand: 'العلامة التجارية: Fixture Beauty',
          exportLabel: 'تصدير كل صفوف هذه المقارنة',
        }
      : {
          nav: 'Compare',
          title: 'Compare',
          pick: 'Pick two shops to compare.',
          base: 'First shop',
          other: 'Second shop',
          groupBy: 'Group by',
          verdict:
            'Shop A is cheaper on 3 of the 6 matched products; Shop B is cheaper on 2, and 1 costs the same.',
          matchedTitle: 'The 6 matched products',
          fold: '9 more products could not be compared',
          show: 'Show them',
          hide: 'Hide them',
          notSold: 'Only Shop A sells it.',
          tooSmall: 'Too few products',
          of15: '3 of 15 products are listed',
          more: 'Show up to 500',
          emptyPair: 'No products are matched between Shop A and Shop B yet',
          p05: '+AED 20.00',
          reasonLead: 'Nothing can be compared for this pair.',
          blocks: 'This retailer blocks collection.',
          detail: 'A selected retailer could not be collected.',
          blocked: 'Blocked',
          seen14: '14 products seen',
          awaiting: 'Awaiting review',
          prices: 'See prices by category instead',
          peek: 'Available now: median price by category',
          open: 'Both listings',
          back: 'Back to comparison',
          brand: 'Brand: Fixture Beauty',
          exportLabel: 'Export all rows of this comparison',
        };

  // Arabic is written with Western digits here, as the page formats them.
  const matchedRows = (page: Page) => page.locator('#matched table tbody tr');

  test.describe(`${locale} compare`, () => {
    test('picking a pair answers first: who is cheaper on how many, the matched list, the rest folded', async ({
      page,
    }) => {
      const mock = await mockBackend(page, { onApi: api() });
      await signIn(page, locale);
      // The Overview asks /compare once for its headline; the Compare page itself asks nothing until a pair is picked.
      await expect.poll(() => compareCalls(mock).length).toBe(1);
      await page.getByRole('navigation').getByRole('link', { name: T.nav }).click();
      await expect(page).toHaveURL(new RegExp(`/app/${locale}/compare/$`));
      await expect(page.getByRole('heading', { level: 1, name: T.title })).toBeVisible();
      await expect(page.getByText(T.pick)).toBeVisible();
      expect(compareCalls(mock)).toHaveLength(1);

      await page.getByLabel(T.base).selectOption('shop_a');
      await page.getByLabel(T.other).selectOption('shop_b');
      await expect(page).toHaveURL(/\?retailers=shop_a%2Cshop_b$/);
      const call = compareCalls(mock).at(-1)!;
      expect(call.searchParams.get('retailers')).toBe('shop_a,shop_b');
      expect(call.searchParams.get('limit')).toBe('100');

      // The answer, in one sentence from the API's own counts; the median gap as sent.
      await expect(page.locator('#verdict-title')).toHaveText(T.verdict);
      await expect(page.getByText('+2.4%').first()).toBeVisible();

      // The API's caveat is not a box on this page (#171): it lives under About the data.
      await expect(page.getByRole('note')).toHaveCount(0);

      // Only the matched products are rows; everything else is one line with its reasons.
      await expect(page.locator('#matched-title')).toHaveText(T.matchedTitle);
      await expect(matchedRows(page)).toHaveCount(6);
      // p05: 80 vs 100 → +20.00; Shop B is 25% dearer (the gap is a share of Shop A's price).
      await expect(
        page.locator('#matched tr, #matched li').filter({ hasText: 'Product p05' }).first(),
      ).toContainText(T.p05);
      await expect(page.locator('#matched')).not.toContainText('Product p12');
      await expect(page.locator('#matched')).toContainText(T.fold);
      const fold = page.getByRole('button', { name: T.show });
      await expect(fold).toHaveAttribute('aria-expanded', 'false');
      await fold.click();
      await expect(page.getByRole('button', { name: T.hide })).toHaveAttribute('aria-expanded', 'true');
      await expect(matchedRows(page)).toHaveCount(15);
      await expect(page.getByRole('row', { name: /Product p12/ })).toContainText(T.notSold);

      await page.getByLabel(T.groupBy).selectOption('brand');
      await expect(page).toHaveURL(/groupBy=brand/);
      await expect(page.locator('#groups').getByText(new RegExp(T.tooSmall)).first()).toBeVisible();
      await page.getByRole('button', { name: 'Fixture Beauty' }).click();
      await expect(page).toHaveURL(/brand=Fixture\+Beauty/);
      expect(compareCalls(mock).at(-1)!.searchParams.getAll('brand')).toEqual(['Fixture Beauty']);
      await page.getByRole('button', { name: new RegExp(T.brand) }).click();
      await expect(page).not.toHaveURL(/brand=/);

      // Choosing the other side's shop as the first swaps the pair.
      await page.getByLabel(T.base).selectOption('shop_b');
      await expect(page).toHaveURL(/retailers=shop_b%2Cshop_a/);
      expect(compareCalls(mock).at(-1)!.searchParams.get('retailers')).toBe('shop_b,shop_a');
      await noHorizontalScroll(page);
      expect(mock.external).toEqual([]);
      expect(mock.errors).toEqual([]);
    });

    test('a cut list says N of total and can ask for up to 500', async ({ page }) => {
      const mock = await mockBackend(page, {
        onApi: api((u) => (u.searchParams.get('limit') === '500' ? compare : limited)),
      });
      await signedIn(page, locale);
      await page.goto(`/app/${locale}/compare/?retailers=shop_a%2Cshop_b`);
      await expect(page.getByText(T.of15)).toBeVisible();
      await expect(matchedRows(page)).toHaveCount(3);
      await page.getByRole('button', { name: T.more }).click();
      await expect(page).toHaveURL(/limit=500/);
      await expect(page.locator('#matched-title')).toHaveText(T.matchedTitle);
      await expect(matchedRows(page)).toHaveCount(6);
      expect(compareCalls(mock).at(-1)!.searchParams.get('limit')).toBe('500');
      await noHorizontalScroll(page);
      expect(mock.errors).toEqual([]);
    });

    test('a blocked retailer: no verdict, the API reason and detail, the side marked blocked', async ({
      page,
    }) => {
      const mock = await mockBackend(page, { onApi: api(() => blocked) });
      await signedIn(page, locale);
      await page.goto(`/app/${locale}/compare/?retailers=shop_a%2Cshop_d`);
      // The API withheld the comparison: its reason is the headline, not a claim about products.
      await expect(page.locator('#empty-title')).toHaveText(T.blocks);
      await expect(page.locator('#empty-title + p')).toHaveText(`${T.reasonLead} ${T.detail}`);
      await expect(page.locator('main')).not.toContainText(T.emptyPair.replace('Shop B', 'Shop D'));
      await expect(page.getByRole('listitem').filter({ hasText: 'Shop D' })).toContainText(T.blocked);
      await expect(page.locator('#verdict-title')).toHaveCount(0);
      await expect(page.locator('#matched')).toHaveCount(0);
      // /category-compare is 404 for this pair, so no medians are offered either.
      await expect(page.locator('#peek-title')).toHaveCount(0);
      await noHorizontalScroll(page);
      expect(mock.errors).toEqual([]);
    });

    test('nothing matched yet: what each side has, who is waiting, and the category medians that exist', async ({
      page,
    }) => {
      const mock = await mockBackend(page, { onApi: api(() => unmatched, true) });
      await signedIn(page, locale);
      await page.goto(`/app/${locale}/compare/?retailers=shop_a%2Cshop_b`);
      await expect(page.locator('#empty-title')).toHaveText(T.emptyPair);
      await expect(page.getByRole('listitem').filter({ hasText: 'Shop A' })).toContainText(T.seen14);
      await expect(page.getByRole('listitem').filter({ hasText: T.awaiting })).toContainText('1');
      await expect(page.getByRole('link', { name: T.prices })).toHaveAttribute(
        'href',
        `/app/${locale}/prices/`,
      );
      await expect(page.locator('#verdict-title')).toHaveCount(0);
      await expect(page.locator('#peek-title')).toHaveText(T.peek);
      await expect(page.locator('section:has(#peek-title) tbody tr')).toHaveCount(9);
      expect(calls(mock, '/api/v1/category-compare').at(-1)!.searchParams.get('retailers')).toBe(
        'shop_a,shop_b',
      );
      await noHorizontalScroll(page);
      expect(mock.errors).toEqual([]);
    });

    test('a row opens both listings, and Back returns to the same comparison', async ({ page }) => {
      const mock = await mockBackend(page, { onApi: api() });
      await signedIn(page, locale);
      await page.goto(`/app/${locale}/compare/?retailers=shop_a%2Cshop_b&groupBy=brand`);
      await page.getByRole('link', { name: `${T.open}: Product p05` }).click();
      await expect(page).toHaveURL(/\/product\/\?id=p05&back=compare&from=/);
      await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
      await page.getByRole('link', { name: T.back }).click();
      await expect(page).toHaveURL(
        new RegExp(`/app/${locale}/compare/\\?retailers=shop_a%2Cshop_b&groupBy=brand$`),
      );
      await expect(matchedRows(page)).toHaveCount(6);
      expect(mock.errors).toEqual([]);
    });

    test('the export sends the pair and filters, and the file arrives', async ({ page }) => {
      const mock = await mockBackend(page, { onApi: api() });
      await signedIn(page, locale);
      await page.goto(`/app/${locale}/compare/?retailers=shop_a%2Cshop_b&brand=Fixture+Beauty`);
      await expect(page.locator('#verdict-title')).toBeVisible();
      const [download] = await Promise.all([
        page.waitForEvent('download'),
        page.getByRole('button', { name: T.exportLabel }).click(),
      ]);
      expect(download.suggestedFilename()).toBe('pi-compare.csv');
      const call = calls(mock, '/api/v1/export/compare').at(-1)!;
      expect(call.searchParams.get('format')).toBe('csv');
      expect(call.searchParams.get('retailers')).toBe('shop_a,shop_b');
      expect(call.searchParams.getAll('brand')).toEqual(['Fixture Beauty']);
      expect(mock.errors).toEqual([]);
    });
  });
}
