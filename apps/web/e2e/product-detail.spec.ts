import type { Page, Route } from '@playwright/test';
import { expect, golden, mockBackend, noHorizontalScroll, signIn, test } from './fixtures';

type Json = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
const clone = <T>(v: T): T => structuredClone(v);

const meta = golden('meta') as Json;
const history = golden('history') as Json;

/** Every attribute row the sheet draws, in order. */
const ROWS = [
  'price',
  'regular',
  'promo',
  'availability',
  'rating',
  'size',
  'shades',
  'sku',
  'channel',
  'evidence',
];

/** The golden product with every attribute filled: a SKU, shades, a page link, a size label. */
function full(): Json {
  const p = clone(golden('product') as Json);
  p.data.offers[0].sku = 'SA-1001';
  p.data.offers[0].shadeCount = 12;
  p.data.offers[0].evidence.url = 'https://shop-a.example/p01';
  p.data.offers[1].sku = 'SB-77';
  p.data.offers[1].sizeLabel = 'M';
  p.data.offers[1].sizeSystem = 'EU';
  return p;
}

/**
 * Every optional attribute null, as the API sends a thin listing: Shop A has no price at all,
 * Shop B (an imported retailer) has a price but its was-price is withheld.
 */
function sparse(): Json {
  const p = clone(golden('product') as Json);
  for (const o of p.data.offers)
    Object.assign(o, {
      regular: null,
      promoPct: null,
      availability: null,
      rating: null,
      size: null,
      sizeLabel: null,
      sizeSystem: null,
      shadeCount: null,
      sku: null,
    });
  p.data.offers[0].price = null;
  p.data.card.size = null;
  p.data.card.category = [];
  p.caveats = [{ code: 'was_price_unverified', params: { retailer: 'shop_b' }, en: 'x', ar: 'x' }];
  return p;
}

function api(product: Json) {
  return async (route: Route) => {
    const p = new URL(route.request().url()).pathname;
    if (p === '/api/v1/meta') return route.fulfill({ json: meta });
    if (/^\/api\/v1\/products\/[^/]+\/history$/.test(p)) return route.fulfill({ json: history });
    if (/^\/api\/v1\/products\/[^/]+$/.test(p)) return route.fulfill({ json: product });
    return route.fulfill({ status: 404, json: { error: { code: 'not_found', message: 'no route' } } });
  };
}

async function open(page: Page, locale: 'en' | 'ar', product: Json) {
  const mock = await mockBackend(page, { onApi: api(product) });
  await signIn(page, locale);
  await expect(page.getByRole('navigation').first()).toBeVisible();
  await page.goto(`/app/${locale}/product/?id=${product.data.card.id}`);
  await expect(page.getByRole('heading', { level: 1, name: product.data.card.name })).toBeVisible();
  return mock;
}

/** The sheet's cell for one attribute, by retailer column (0 = Shop A). */
const cell = (page: Page, attr: string, col: number) =>
  page.locator(`[data-offer-sheet] tr[data-attr=${attr}] td`).nth(col);

/** The sheet fits a phone: two retailers side by side, no sideways scroll inside it or the page. */
async function fits(page: Page) {
  await noHorizontalScroll(page);
  const wrap = page.locator('[data-offer-sheet]').locator('..');
  expect(await wrap.evaluate((e) => e.scrollWidth - e.clientWidth)).toBeLessThanOrEqual(1);
}

for (const locale of ['en', 'ar'] as const) {
  const T =
    locale === 'ar'
      ? {
          shopA: 'Shop A',
          inStock: 'متوفر',
          ml: '50 ml',
          none: 'لا يوجد',
          noRange: 'لا توجد درجات لونية لهذا المنتج.',
          online: 'عبر الإنترنت',
          notPublished: 'غير منشور',
          notMeasured: 'غير مُقاس',
          noPrice: 'لا سعر في صفحة المنتج في هذا التاريخ.',
          wasPrice: 'أسعار ما قبل الخصم لدى هذا المتجر غير موثّقة.',
          notCollected: 'غير مُجمَّع لهذا المتجر.',
          needsPrice: 'لا سعر يُحسب منه.',
          noSku: 'لا تعرض الصفحة رمز المنتج.',
          source: 'افتح الصفحة',
        }
      : {
          shopA: 'Shop A',
          inStock: 'In stock',
          ml: '50 ml',
          none: 'None',
          noRange: 'The listing has no shade range.',
          online: 'Online',
          notPublished: 'Not published',
          notMeasured: 'Not measured',
          noPrice: 'No price on the listing on this date.',
          wasPrice: 'This retailer’s was-prices are unverified.',
          notCollected: 'Not collected for this retailer.',
          needsPrice: 'No price to work it out from.',
          noSku: 'The listing shows no SKU.',
          source: 'Open page',
        };

  test.describe(`${locale} product detail`, () => {
    test('full listing: every attribute, both retailers side by side', async ({ page }) => {
      const p = full();
      const mock = await open(page, locale, p);
      const sheet = page.locator('[data-offer-sheet]');
      await expect(sheet.locator('thead th')).toHaveText(['Shop A', 'Shop B']);
      await expect(sheet.locator('tr[data-attr]')).toHaveCount(ROWS.length);
      expect(
        await sheet.locator('tr[data-attr]').evaluateAll((r) => r.map((e) => e.getAttribute('data-attr'))),
      ).toEqual(ROWS);
      // Every row has a header and one cell per retailer, none of them empty.
      for (const attr of ROWS)
        for (const col of [0, 1]) await expect(cell(page, attr, col)).not.toHaveText(/^\s*$/);

      await expect(cell(page, 'price', 0)).toContainText('90.00');
      await expect(cell(page, 'regular', 0)).toContainText('100.00');
      await expect(cell(page, 'promo', 0)).toHaveText('10.0%');
      await expect(cell(page, 'availability', 0)).toHaveText(T.inStock);
      await expect(cell(page, 'size', 0)).toHaveText(T.ml);
      await expect(cell(page, 'size', 1)).toContainText('M');
      await expect(cell(page, 'size', 1)).toContainText('(EU)');
      await expect(cell(page, 'shades', 0)).toHaveText('12');
      await expect(cell(page, 'sku', 0)).toHaveText('SA-1001');
      await expect(cell(page, 'channel', 0)).toHaveText(T.online);
      await expect(
        cell(page, 'evidence', 0).getByRole('link', { name: new RegExp(T.source) }),
      ).toHaveAttribute('href', 'https://shop-a.example/p01');
      // Shop B sells at its regular price: no discount, and it says so.
      await expect(cell(page, 'promo', 1)).toContainText(T.none);
      // The golden's 0 shades is no shade range, never a count of 0.
      await expect(cell(page, 'shades', 1)).toContainText(T.noRange);
      await fits(page);
      expect(mock.external).toEqual([]);
      expect(mock.errors).toEqual([]);
    });

    test('sparse listing: each missing attribute says why, never 0 or blank', async ({ page }) => {
      const p = sparse();
      const mock = await open(page, locale, p);
      await expect(cell(page, 'price', 0)).toHaveText(`${T.notPublished}${T.noPrice}`);
      await expect(cell(page, 'price', 1)).toContainText('100.00');
      await expect(cell(page, 'regular', 1)).toHaveText(`${T.notMeasured}${T.wasPrice}`);
      await expect(cell(page, 'promo', 0)).toHaveText(`${T.notMeasured}${T.needsPrice}`);
      await expect(cell(page, 'promo', 1)).toHaveText(`${T.notMeasured}${T.wasPrice}`);
      await expect(cell(page, 'availability', 0)).toHaveText(`${T.notMeasured}${T.notCollected}`);
      await expect(cell(page, 'sku', 1)).toHaveText(`${T.notPublished}${T.noSku}`);
      // Every optional attribute, in both columns, is a reasoned state.
      for (const attr of ['regular', 'promo', 'availability', 'rating', 'size', 'shades', 'sku'])
        for (const col of [0, 1])
          await expect(cell(page, attr, col).locator('[data-missing]')).toHaveCount(1);
      expect(
        await page
          .locator('[data-offer-sheet] tr[data-attr] td')
          .evaluateAll((c) => c.filter((e) => /^\s*(0|0%|0\.00)?\s*$/.test(e.textContent ?? '')).length),
      ).toBe(0);
      // The header names the size and category as not published, not as gaps.
      const facts = page.locator('article header dl');
      await expect(facts).toContainText(T.notPublished);
      await fits(page);
      expect(mock.external).toEqual([]);
      expect(mock.errors).toEqual([]);
    });
  });
}

test('a retailer seen in two places gets a column for each, named by place', async ({ page }) => {
  const p = full();
  const pickup = { ...clone(p.data.offers[0]), context: 'shop_a_pickup', channel: 'pickup' };
  p.data.offers.splice(1, 0, pickup);
  const m = clone(meta);
  m.data.contexts.push({
    channel: 'pickup',
    id: 'shop_a_pickup',
    label: { en: 'Shop A pickup' },
    location: { id: 'dxb_mall', area: null, city: 'Dubai', label: { en: 'Dubai Mall' } },
    retailer: 'shop_a',
  });
  await mockBackend(page, {
    onApi: (r) =>
      new URL(r.request().url()).pathname === '/api/v1/meta' ? r.fulfill({ json: m }) : api(p)(r),
  });
  await signIn(page, 'en');
  await expect(page.getByRole('navigation').first()).toBeVisible();
  await page.goto(`/app/en/product/?id=${p.data.card.id}`);
  const heads = page.locator('[data-offer-sheet] thead th');
  await expect(heads).toHaveCount(3);
  await expect(heads.nth(0)).toContainText('Shop A');
  await expect(heads.nth(1)).toContainText('Shop A pickup');
  await expect(cell(page, 'channel', 1)).toHaveText('PickupDubai Mall');
  await noHorizontalScroll(page);
});
