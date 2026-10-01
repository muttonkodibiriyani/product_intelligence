import type { Route } from '@playwright/test';
import { expect, golden, mockBackend, noHorizontalScroll, signIn, test } from './fixtures';
import { summaryBody } from './summary-fixture';

/*
 * An imported retailer under API 1.5.0 (owner rule, 2026-10-01): its was-prices are unverified, so
 * promotions are withheld with that reason, never 0%; its date is an import date, never freshness;
 * its count may include parent listings. The labels key off the API's caveat codes.
 */

const caveat = (code: string, params: Record<string, string>, en: string, ar: string) => ({
  code,
  params,
  en,
  ar,
});
const C = {
  was: caveat(
    'was_price_unverified',
    { retailer: 'ulta_ae' },
    "Ulta Beauty UAE's was-prices are unverified: its discounts and promotions are not shown or measured.",
    'أسعار ما قبل الخصم لدى Ulta Beauty UAE غير موثّقة: لا تُعرض خصوماته وعروضه ولا تُقاس.',
  ),
  snap: caveat(
    'snapshot_import_date',
    { retailer: 'ulta_ae', date: '2026-09-30' },
    'Ulta Beauty UAE: snapshot imported 2026-09-30, capture date unknown.',
    'Ulta Beauty UAE: لقطة بيانات مستوردة بتاريخ 2026-09-30، وتاريخ جمعها غير معروف.',
  ),
  parents: caveat(
    'parent_listings_included',
    { retailer: 'ulta_ae' },
    "Ulta Beauty UAE's products may include parent listings that repeat their variants, so its counts can overstate distinct products.",
    'قد تتضمن منتجات Ulta Beauty UAE قوائم رئيسية تكرّر متغيراتها، فقد تزيد أعداده عن المنتجات الفعلية.',
  ),
};

/** /summary for the imported retailer, as #131 serves it. */
const summarySnapshot = {
  ...summaryBody,
  data: {
    ...summaryBody.data,
    retailer: 'ulta_ae',
    freshness: { cutoff: '2026-09-30T11:20:00Z', ageDays: 1, status: 'snapshot' },
    withheld: [{ section: 'promotions', reason: 'was_price_unverified' }],
    promoSharePct: null,
    promoDepth: null,
    topDiscounts: null,
  },
  meta: { ...summaryBody.meta, filters: { retailer: 'ulta_ae' } },
  caveats: [C.was, C.snap, C.parents],
};

const goldenMeta = golden('meta') as { data: { retailers: unknown[] }; caveats: unknown[] };
const meta = {
  ...goldenMeta,
  data: {
    ...goldenMeta.data,
    retailers: [
      ...goldenMeta.data.retailers,
      {
        country: 'AE',
        id: 'ulta_ae',
        name: 'Ulta Beauty UAE',
        note: null,
        since: '2026-09-30',
        status: 'supported',
      },
    ],
  },
  // /meta shows no prices, so it owes the date and parent caveats only.
  caveats: [C.snap, C.parents],
};

/** A product with one collected and one imported offer: the import time sits in `capturedAt`. */
const goldenProduct = golden('product') as {
  data: { card: { id: string }; offers: { retailer: string; evidence: { capturedAt: string } }[] };
  caveats: unknown[];
};
const productMixed = structuredClone(goldenProduct);
productMixed.data.offers[1]!.retailer = 'ulta_ae';
productMixed.data.offers[1]!.evidence.capturedAt = '2026-09-30T21:15:00Z';
productMixed.caveats = [C.was, C.snap];
const history = golden('history');

const api =
  (summary: unknown, product: unknown = productMixed) =>
  async (r: Route) => {
    const p = new URL(r.request().url()).pathname;
    if (p === '/api/v1/summary') return r.fulfill({ json: summary });
    if (p === '/api/v1/meta') return r.fulfill({ json: meta });
    if (/^\/api\/v1\/products\/[^/]+\/history$/.test(p)) return r.fulfill({ json: history });
    if (/^\/api\/v1\/products\/[^/]+$/.test(p)) return r.fulfill({ json: product });
    return r.fulfill({ status: 404, json: { error: { code: 'not_found', message: 'no route' } } });
  };

for (const locale of ['en', 'ar'] as const) {
  const ar = locale === 'ar';
  const T = ar
    ? {
        freshness: 'حداثة البيانات',
        snapshot: 'لقطة مستوردة',
        imported: /^استُوردت في .+، وتاريخ جمعها غير معروف$/,
        products: 'المنتجات المتتبَّعة',
        parents: 'منتجات (لقطة، قد تشمل قوائم رئيسية)',
        compare: 'المقارنة',
        offers: 'العروض',
        offersOn: /^العروض بتاريخ /,
        offerImported: /^استُوردت في .+، وتاريخ جمعها غير معروف$/,
        captured: /^رُصد /,
        collected: '(للمتاجر التي نجمع بياناتها)',
        promo: 'ضمن العروض',
        age: /عمرها|جُمعت اليوم|حتى /,
        subtitle: /· لقطة مستوردة في .+، وتاريخ جمعها غير معروف$/,
        withheld: 'أسعار ما قبل الخصم لدى هذا المتجر غير موثّقة، لذا لا تُعرض خصوماته وعروضه.',
        row: /^لقطة مستوردة في .+، وتاريخ جمعها غير معروف$/,
        top: 'أكبر التخفيضات',
        depth: 'عمق العروض',
      }
    : {
        freshness: 'Data freshness',
        snapshot: 'Snapshot',
        imported: /^Imported .+, capture date unknown$/,
        products: 'Products tracked',
        parents: 'Products (snapshot, may include parent listings)',
        compare: 'Compare',
        offers: 'Offers',
        offersOn: /^Offers on /,
        offerImported: /^Imported .+, capture date unknown$/,
        captured: /^Captured /,
        collected: '(collected retailers)',
        promo: 'On promotion',
        age: /days? old|collected today|as of /,
        subtitle: /· snapshot imported .+, capture date unknown$/,
        withheld: "This retailer's was-prices are unverified, so its discounts and promotions are not shown.",
        row: /^snapshot imported .+, capture date unknown$/,
        top: 'Top discounts',
        depth: 'Promotion depth',
      };

  test.describe(`imported snapshot (${locale})`, () => {
    test('never fresh, never 0%: an import date, a withheld reason and the API caveats', async ({ page }) => {
      const mock = await mockBackend(page, { onApi: api(summarySnapshot) });
      await signIn(page, locale);

      const kpis = page.locator('main dl').first();
      const tile = (k: string) =>
        kpis.locator(':scope > div').filter({ has: page.getByText(k, { exact: true }) });
      // Freshness: a neutral snapshot pill and the import date, with no "as of" and no age.
      const fresh = tile(T.freshness);
      await expect(fresh.getByText(T.snapshot, { exact: true })).toBeVisible();
      await expect(fresh.getByText(T.imported)).toBeVisible();
      await expect(fresh).not.toContainText(T.age);
      // The count says what it may include; no promotion share, so no percentage anywhere in the band.
      await expect(tile(T.products)).toContainText(T.parents);
      await expect(page.getByText(T.promo, { exact: true })).toHaveCount(0);
      await expect(kpis).not.toContainText('%');
      await expect(page.locator('main p').filter({ hasText: T.subtitle })).toBeVisible();

      // The API's own caveat text, in the user's language.
      for (const c of [C.was, C.snap, C.parents])
        await expect(page.getByText(ar ? c.ar : c.en, { exact: true }).first()).toBeVisible();

      // The dataset panel: the imported retailer has an import date, the others keep "since".
      const row = page.locator('#dataset tr').filter({ hasText: 'Ulta Beauty UAE' });
      await expect(row.locator('td').nth(1)).toHaveText(T.row);
      await expect(
        page.locator('#dataset tr').filter({ hasText: 'Shop A' }).locator('td').nth(1),
      ).not.toHaveText(T.row);
      // With an imported retailer present, the dataset cutoff says whose it is.
      await expect(page.locator('#dataset dl').first()).toContainText(T.collected);
      await noHorizontalScroll(page);

      // Promotion widgets stay off; on Compare their previews carry the reason, never a figure.
      for (const name of [T.top, T.depth])
        await expect(page.getByRole('heading', { level: 2, name, exact: true })).toHaveCount(0);
      await page.getByRole('tab', { name: T.compare }).click();
      await expect(page.locator('main [role=note]').filter({ hasText: T.withheld })).toHaveCount(2);
      await expect(page.locator('main')).not.toContainText(/\d%/);
      await noHorizontalScroll(page);
      expect(mock.external).toEqual([]);
      expect(mock.errors).toEqual([]);
    });

    test('product page: an imported offer shows its import date, and the heading drops the cutoff', async ({
      page,
    }) => {
      const mock = await mockBackend(page, { onApi: api(summaryBody) });
      await signIn(page, locale);
      await expect(page.getByRole('navigation')).toBeVisible();
      await page.goto(`/app/${locale}/product/?id=${productMixed.data.card.id}`);
      await expect(page.getByRole('heading', { name: T.offers, exact: true })).toBeVisible();
      await expect(page.getByRole('heading', { name: T.offersOn })).toHaveCount(0);
      const row = (name: string) =>
        page.locator('article table').first().locator('tbody tr').filter({ hasText: name });
      await expect(row('Ulta Beauty UAE').locator('time')).toHaveText(T.offerImported);
      await expect(row('Ulta Beauty UAE')).not.toContainText(T.captured);
      await expect(row('Shop A').locator('time')).toHaveText(T.captured);
      await noHorizontalScroll(page);
      expect(mock.external).toEqual([]);
      expect(mock.errors).toEqual([]);
    });

    test('product page: all offers collected keeps "Offers on <cutoff>" and capture dates', async ({
      page,
    }) => {
      const mock = await mockBackend(page, { onApi: api(summaryBody, goldenProduct) });
      await signIn(page, locale);
      await expect(page.getByRole('navigation')).toBeVisible();
      await page.goto(`/app/${locale}/product/?id=${goldenProduct.data.card.id}`);
      await expect(page.getByRole('heading', { name: T.offersOn })).toBeVisible();
      const offers = page.locator('article table').first();
      await expect(offers.locator('tbody time').first()).toHaveText(T.captured);
      await expect(offers).not.toContainText(/capture date unknown|وتاريخ جمعها غير معروف/);
      expect(mock.external).toEqual([]);
      expect(mock.errors).toEqual([]);
    });

    test('a collected retailer is unchanged: aged freshness, no snapshot wording', async ({ page }) => {
      const mock = await mockBackend(page, { onApi: api(summaryBody) });
      await signIn(page, locale);
      const kpis = page.locator('main dl').first();
      await expect(kpis.getByText(T.promo, { exact: true })).toBeVisible();
      await expect(kpis).toContainText(T.age);
      await expect(kpis.getByText(T.snapshot, { exact: true })).toHaveCount(0);
      await expect(kpis).not.toContainText(T.parents);
      expect(mock.external).toEqual([]);
      expect(mock.errors).toEqual([]);
    });
  });
}
