import type { Page, Route } from '@playwright/test';
import { expect, golden, mockBackend, noHorizontalScroll, signIn, test, type Mock } from './fixtures';

type Json = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any

const meta = golden('meta') as Json;
// not_enough_data (shop_c partial) with data: 3 items, all shop_a; shop_a 50.0%, shop_b 0.0%,
// shop_c (retailer_partial) and shop_d (retailer_blocked) without a share.
const promotions = golden('promotions') as Json;
const cut = { ...promotions, data: { ...promotions.data, total: 40, truncated: true } };
const product = golden('product') as Json;
const history = golden('history') as Json;
const CSV = '﻿"# {""view"":""promotions"",""rows"":3}"\nid,name\np05,Product p05\n';

function api(promotionsFor: (u: URL) => Json = () => promotions) {
  return async (route: Route) => {
    const u = new URL(route.request().url());
    const p = u.pathname;
    if (p === '/api/v1/meta') return route.fulfill({ json: meta });
    if (p === '/api/v1/promotions') return route.fulfill({ json: promotionsFor(u) });
    if (p === '/api/v1/export/promotions')
      return route.fulfill({
        status: 200,
        body: CSV,
        headers: {
          'Content-Type': 'text/csv; charset=utf-8',
          'Content-Disposition': 'attachment; filename="pi-promotions-20260930T0000Z.csv"',
        },
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

const calls = (mock: Mock, path = '/api/v1/promotions') =>
  mock.api.map((r) => new URL(r.url)).filter((u) => u.pathname === path);

for (const locale of ['en', 'ar'] as const) {
  const T =
    locale === 'ar'
      ? {
          nav: 'العروض',
          title: 'العروض',
          tiles: 'نسبة المنتجات المخفّضة حسب المتجر',
          priced6: '6 منتج مسعّر',
          deepest: 'أكبر خصم: −33.3%.',
          none: 'لا منتج يحمل سعرًا أقل من سعره المعتاد.',
          notMeasured: 'الخصومات غير مقيسة',
          notMeasuredFilters: 'الخصومات غير مقيسة لعوامل التصفية هذه.',
          notMeasuredAtA: 'خصومات Shop A غير مقيسة.',
          notCollected: 'غير مُجمَّع لهذا المتجر.',
          empty: 'لا منتجات مخفّضة لعوامل التصفية هذه.',
          partial: 'هذا المتجر مغطّى جزئيًا فقط.',
          blocked: 'هذا المتجر يمنع الجمع.',
          products: 'المنتجات',
          heading: 'أكبر الخصومات',
          headingA: 'أكبر الخصومات في Shop A',
          results: 'المنتجات المخفّضة',
          three: '3 منتجات',
          of40: '3 من 40 منتج',
          more: 'اعرض حتى 500',
          minPct: 'أدنى خصم',
          grid: 'شبكة',
          list: 'قائمة',
          shopChip: 'المتجر: Shop A',
          csv: /بصيغة CSV$/,
          saved: 'حُفظ الملف pi-promotions-20260930T0000Z.csv.',
          back: 'العودة إلى العروض',
        }
      : {
          nav: 'Promotions',
          title: 'Promotions',
          tiles: 'Share on promotion by shop',
          priced6: '6 priced products',
          deepest: 'Deepest cut: −33.3%.',
          none: 'No product carries a lower price than its regular price.',
          notMeasured: 'Discounts not measured',
          notMeasuredFilters: 'Discounts aren’t measured for these filters.',
          notMeasuredAtA: 'Discounts at Shop A aren’t measured.',
          notCollected: 'Not collected for this retailer.',
          empty: 'No product is discounted for these filters.',
          partial: 'This retailer is only partly covered.',
          blocked: 'This retailer blocks collection.',
          products: 'Products',
          heading: 'Deepest discounts',
          headingA: 'Deepest discounts at Shop A',
          results: 'Discounted products',
          three: '3 products',
          of40: '3 of 40 products',
          more: 'Show up to 500',
          minPct: 'Minimum discount',
          grid: 'Grid',
          list: 'List',
          shopChip: 'Shop: Shop A',
          csv: /as CSV$/,
          saved: 'Saved pi-promotions-20260930T0000Z.csv.',
          back: 'Back to promotions',
        };

  const tiles = (page: Page) => page.getByRole('list', { name: T.tiles }).getByRole('listitem');
  const cards = (page: Page) =>
    page.getByRole('list', { name: T.results, exact: true }).getByRole('listitem');

  test.describe(`${locale} promotions`, () => {
    test('one tile per shop from the API, then the discounted products as cards, deepest first', async ({
      page,
    }) => {
      const mock = await mockBackend(page, { onApi: api() });
      await signIn(page, locale);
      await page.getByRole('navigation').getByRole('link', { name: T.nav }).click();
      await expect(page).toHaveURL(new RegExp(`/app/${locale}/promotions/$`));
      await expect(page.getByRole('heading', { level: 1, name: T.title })).toBeVisible();

      // No caveat box anywhere: a shop without data says so in its own tile, in one line.
      await expect(page.getByRole('note')).toHaveCount(0);
      await expect(tiles(page)).toHaveCount(4);
      const a = tiles(page).filter({ hasText: 'Shop A' });
      await expect(a).toContainText('50.0%');
      await expect(a).toContainText(T.priced6);
      await expect(a).toContainText(T.deepest);
      const b = tiles(page).filter({ hasText: 'Shop B' });
      await expect(b).toContainText('0.0%');
      await expect(b).toContainText(T.none);
      const c = tiles(page).filter({ hasText: 'Shop C' });
      await expect(c).toContainText(T.notMeasured);
      await expect(c).toContainText(T.partial);
      await expect(c).not.toContainText(/not available|غير متاح/);
      await expect(c.getByRole('link', { name: T.products })).toHaveAttribute(
        'href',
        new RegExp(`/${locale}/explore/?\\?retailer=shop_c$`),
      );
      await expect(c).not.toContainText('%');
      const d = tiles(page).filter({ hasText: 'Shop D' });
      await expect(d).toContainText(T.notMeasured);
      await expect(d).toContainText(T.blocked);

      // The list is named from the user's pick (none here), never from the rows; each card shows
      // now, was and the depth.
      await expect(page.getByRole('heading', { level: 2, name: T.heading, exact: true })).toBeVisible();
      await expect(page.getByRole('heading', { level: 2, name: T.headingA })).toHaveCount(0);
      await expect(page.getByRole('status').filter({ hasText: T.three })).toBeVisible();
      await expect(cards(page)).toHaveCount(3);
      await expect(page.getByRole('button', { name: T.grid, exact: true })).toHaveAttribute(
        'aria-pressed',
        'true',
      );
      const first = cards(page).first();
      await expect(first.getByRole('link', { name: 'Product p05' })).toBeVisible();
      await expect(first).toContainText('−33.3%');
      await expect(first).toContainText('80.00');
      await expect(first.locator('s')).toContainText('120.00');
      await expect(first).toContainText('Shop A');

      const call = calls(mock)[0]!;
      expect([...call.searchParams.keys()]).toEqual(['limit']);
      expect(call.searchParams.get('limit')).toBe('100');
      await noHorizontalScroll(page);
      expect(mock.external).toEqual([]);
      expect(mock.errors).toEqual([]);
    });

    test('the list is one click away and stays the choice after a reload', async ({ page }) => {
      const mock = await mockBackend(page, { onApi: api() });
      await signedIn(page, locale);
      await page.goto(`/app/${locale}/promotions/`);
      await expect(cards(page)).toHaveCount(3);
      // Exact: the phone menu button ("القائمة") would otherwise match the Arabic "قائمة".
      await page.getByRole('button', { name: T.list, exact: true }).click();
      const rows = page.getByRole('table').getByRole('row');
      await expect(rows).toHaveCount(1 + 3);
      await expect(page.getByRole('row', { name: /Product p05/ })).toContainText('−33.3%');
      await noHorizontalScroll(page);
      await page.reload();
      await expect(page.getByRole('button', { name: T.list, exact: true })).toHaveAttribute(
        'aria-pressed',
        'true',
      );
      await expect(rows).toHaveCount(1 + 3);
      await page.getByRole('button', { name: T.grid, exact: true }).click();
      await expect(cards(page)).toHaveCount(3);
      expect(mock.errors).toEqual([]);
    });

    test('a minimum discount goes into the URL and the request; a shop from the URL is a removable chip', async ({
      page,
    }) => {
      const mock = await mockBackend(page, { onApi: api() });
      await signedIn(page, locale);
      await page.goto(`/app/${locale}/promotions/?retailer=shop_a`);
      await expect(cards(page)).toHaveCount(3);
      // Now the user picked one shop, so the list is headed with it.
      await expect(page.getByRole('heading', { level: 2, name: T.headingA })).toBeVisible();
      await page.getByLabel(T.minPct).selectOption('20');
      await expect(page).toHaveURL(/\?retailer=shop_a&minPct=20$/);
      await expect.poll(() => calls(mock).at(-1)!.searchParams.get('minPct')).toBe('20');
      expect(calls(mock).at(-1)!.searchParams.getAll('retailer')).toEqual(['shop_a']);

      const chip = page.getByRole('button', { name: new RegExp(`^${T.shopChip}`) });
      await expect(chip).toBeVisible();
      await chip.click();
      await expect(page).toHaveURL(/\?minPct=20$/);
      await expect.poll(() => calls(mock).at(-1)!.searchParams.getAll('retailer')).toEqual([]);
      expect(mock.errors).toEqual([]);
    });

    test('when promotions cannot be measured at all, the page says so with the API’s reason, never "no product is discounted"', async ({
      page,
    }) => {
      // pi_metrics answers capability_off / field_not_collected / not_applicable with no shops
      // and no items: that is withheld data, not an empty result.
      const off = {
        ...promotions,
        status: 'not_enough_data',
        reason: 'capability_off',
        detail: { en: 'Promotions are not collected.', ar: 'العروض غير مُجمَّعة.' },
        caveats: [],
        data: { retailers: [], items: [], total: 0, truncated: false },
      };
      const mock = await mockBackend(page, { onApi: api(() => off) });
      await signedIn(page, locale);
      await page.goto(`/app/${locale}/promotions/`);
      await expect(page.getByRole('heading', { level: 1, name: T.title })).toBeVisible();
      await expect(page.getByText(T.notMeasuredFilters)).toBeVisible();
      await expect(page.getByText(T.notCollected)).toBeVisible();
      await expect(page.getByText(T.empty)).toHaveCount(0);
      await expect(page.getByRole('heading', { level: 2, name: T.heading, exact: true })).toBeVisible();
      await expect(page.getByRole('list', { name: T.tiles })).toHaveCount(0);
      await expect(page.getByRole('status').filter({ hasText: /0/ })).toHaveCount(0);
      await expect(page.getByLabel(T.minPct)).toHaveCount(0);
      await expect(page.getByRole('note')).toHaveCount(0);
      await expect(page.getByText(off.detail[locale])).toHaveCount(0);

      // With a shop picked, the line names that shop.
      await page.goto(`/app/${locale}/promotions/?retailer=shop_a`);
      await expect(page.getByText(T.notMeasuredAtA)).toBeVisible();
      await expect(page.getByText(T.notCollected)).toBeVisible();
      await expect(page.getByText(T.empty)).toHaveCount(0);
      await expect(page.getByRole('heading', { level: 2, name: T.headingA })).toBeVisible();
      await noHorizontalScroll(page);
      expect(mock.errors).toEqual([]);
    });

    test('a cut list says N of total and can ask for up to 500', async ({ page }) => {
      const mock = await mockBackend(page, {
        onApi: api((u) => (u.searchParams.get('limit') === '500' ? promotions : cut)),
      });
      await signedIn(page, locale);
      await page.goto(`/app/${locale}/promotions/`);
      await expect(page.getByRole('status').filter({ hasText: T.of40 })).toBeVisible();
      await page.getByRole('button', { name: T.more }).click();
      await expect(page).toHaveURL(/limit=500/);
      await expect(page.getByRole('status').filter({ hasText: T.three })).toBeVisible();
      expect(calls(mock).at(-1)!.searchParams.get('limit')).toBe('500');
      expect(mock.errors).toEqual([]);
    });

    test('Export sends the list’s filters to the promotions export and saves the file', async ({ page }) => {
      const mock = await mockBackend(page, { onApi: api() });
      await signedIn(page, locale);
      await page.goto(`/app/${locale}/promotions/?retailer=shop_a&minPct=10`);
      await expect(cards(page)).toHaveCount(3);
      const csv = page.getByRole('button', { name: T.csv });
      await expect(csv).toBeEnabled();
      const [download] = await Promise.all([page.waitForEvent('download'), csv.click()]);
      expect(download.suggestedFilename()).toBe('pi-promotions-20260930T0000Z.csv');
      await expect(page.getByRole('status').filter({ hasText: T.saved })).toBeVisible();
      const call = calls(mock, '/api/v1/export/promotions')[0]!;
      expect(call.searchParams.getAll('retailer')).toEqual(['shop_a']);
      expect(call.searchParams.get('minPct')).toBe('10');
      expect(call.searchParams.get('format')).toBe('csv');
      expect(call.searchParams.has('limit')).toBe(false);
      expect(mock.errors).toEqual([]);
    });

    test('a card opens its product, and Back returns to the same promotions view', async ({ page }) => {
      const mock = await mockBackend(page, { onApi: api() });
      await signedIn(page, locale);
      await page.goto(`/app/${locale}/promotions/?retailer=shop_a&minPct=10`);
      await cards(page).first().getByRole('link', { name: 'Product p05' }).click();
      await expect(page).toHaveURL(/\/product\/\?id=p05&back=promotions&from=/);
      await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
      await page.getByRole('link', { name: T.back }).click();
      await expect(page).toHaveURL(new RegExp(`/app/${locale}/promotions/\\?retailer=shop_a&minPct=10$`));
      await expect(cards(page)).toHaveCount(3);
      expect(mock.errors).toEqual([]);
    });
  });
}
