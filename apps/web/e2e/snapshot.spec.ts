import type { Route } from '@playwright/test';
import { categoryCompareBody, THIN } from './category-compare-fixture';
import { expect, golden, mockBackend, noCardOverflow, noHorizontalScroll, signIn, test } from './fixtures';
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
const compare = golden('compare');
const categories = categoryCompareBody('shop_a', 'shop_b', THIN);
const index = golden('index');
const launches = golden('launches');
/** /promotions: the imported retailer's share is withheld with the was-price reason, never 0. */
const promotionsGolden = golden('promotions') as { data: Record<string, unknown> };
const promotions = {
  ...promotionsGolden,
  status: 'not_enough_data',
  reason: 'was_price_unverified',
  caveats: [C.was],
  data: {
    items: [],
    total: 0,
    truncated: false,
    retailers: [{ retailer: 'ulta_ae', n: 0, onPromo: 0, share: null, reason: 'was_price_unverified' }],
  },
};

const api =
  (summary: unknown, product: unknown = productMixed) =>
  async (r: Route) => {
    const p = new URL(r.request().url()).pathname;
    if (p === '/api/v1/summary') return r.fulfill({ json: summary });
    if (p === '/api/v1/meta') return r.fulfill({ json: meta });
    if (p === '/api/v1/compare') return r.fulfill({ json: compare });
    if (p === '/api/v1/category-compare') return r.fulfill({ json: categories });
    if (p === '/api/v1/index') return r.fulfill({ json: index });
    if (p === '/api/v1/promotions') return r.fulfill({ json: promotions });
    if (p === '/api/v1/launches') return r.fulfill({ json: launches });
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
        offers: 'العروض',
        offersOn: /^العروض بتاريخ /,
        offerImported: /^استُوردت في .+، وتاريخ جمعها غير معروف$/,
        captured: /^رُصد /,
        collected: '(للمتاجر التي نجمع بياناتها)',
        promo: 'ضمن العروض',
        none: 'غير مُقاس',
        fresh: 'حديثة',
        age: /عمرها|جُمعت اليوم|حتى /,
        subtitle: /Ulta: لقطة لمرة واحدة مستوردة في /,
        withheldWhy: 'أسعار ما قبل الخصم لدى هذا المتجر غير موثّقة، لذا لا تُقاس عروضه.',
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
        offers: 'Offers',
        offersOn: /^Offers on /,
        offerImported: /^Imported .+, capture date unknown$/,
        captured: /^Captured /,
        collected: '(collected retailers)',
        promo: 'On promotion',
        none: 'Not measured',
        fresh: 'Fresh',
        age: /days? old|collected today|as of /,
        subtitle: /Ulta: one-off snapshot imported /,
        withheldWhy: "This retailer's was-prices are unverified, so its promotions are not measured.",
        row: /^snapshot imported .+, capture date unknown$/,
        top: 'Top discounts',
        depth: 'Promotion depth',
      };

  test.describe(`imported snapshot (${locale})`, () => {
    test('never fresh, never 0%: an import date, a withheld reason and the API caveats', async ({ page }) => {
      const mock = await mockBackend(page, { onApi: api(summarySnapshot) });
      await signIn(page, locale);

      // The imported shop's tile: a neutral Snapshot chip with the import date in its tooltip, no
      // "as of" and no age; the count flagged as possibly including parent listings; its
      // promotion share one "Not measured" chip whose tooltip carries the reason, never a figure.
      const kpis = page.locator('#kpi-band');
      const ulta = kpis.locator('[data-tile="shop:ulta_ae"]');
      const tips = ulta.locator('[role=tooltip]');
      await expect(ulta.getByText(T.snapshot, { exact: true })).toBeVisible();
      await expect(tips.filter({ hasText: T.imported })).toHaveCount(1);
      await expect(ulta).not.toContainText(T.age);
      await expect(tips.filter({ hasText: T.parents })).toHaveCount(1);
      await expect(ulta.getByText(T.none, { exact: true })).toBeVisible();
      await expect(tips.filter({ hasText: T.withheldWhy })).toHaveCount(1);
      // The promotions tile says the same of Ulta, once, and draws no depth strip for it; the
      // launches tile reads Ulta as a snapshot (one collection: nothing to compare against).
      const promo = kpis.locator('[data-tile=promotions]');
      // Every /summary here answers for Ulta (the snapshot body), so the band has the one shop and
      // the promotions tile one row for it: not measured, never a share.
      await expect(promo.locator('dt')).toHaveCount(1);
      await expect(promo.locator('dd').filter({ has: page.getByText(T.none, { exact: true }) })).toHaveCount(
        1,
      );
      await expect(promo.locator('[role=img]')).toHaveCount(0);
      await expect(kpis.locator('[data-tile=launches]').getByText(T.snapshot, { exact: true })).toBeVisible();
      await expect(kpis).not.toContainText('%');
      await expect(page.locator('main').getByText(T.subtitle)).toBeVisible();
      // Chips wrap inside their tiles at this width: nothing runs past a card's edge.
      await noCardOverflow(page, '#kpi-band [data-tile]');

      // No caveat note boxes on the Overview (owner decision, #171): the tiles carry the states and
      // the Dataset page the detail; the raw was-price caveat is never pasted onto the page.
      await expect(page.getByText(ar ? C.was.ar : C.was.en)).toHaveCount(0);
      await expect(page.locator('main [role=note]')).toHaveCount(0);
      await expect(page.locator('#dataset')).toHaveCount(0);
      await noHorizontalScroll(page);

      // The Dataset page names the shop, never /meta's long name or the id; the imported retailer
      // has an import date, the others keep "since"; with an imported retailer present, the
      // dataset cutoff says whose it is.
      await page.goto(`/app/${locale}/dataset/`);
      const row = page.locator('#dataset tr').filter({ hasText: 'Ulta' });
      await expect(row.locator('th')).toHaveText('Ulta');
      await expect(row.locator('td').nth(1)).toHaveText(T.row);
      await expect(
        page.locator('#dataset tr').filter({ hasText: 'Shop A' }).locator('td').nth(1),
      ).not.toHaveText(T.row);
      await expect(page.locator('#dataset dl').first()).toContainText(T.collected);
      await noHorizontalScroll(page);
      await page.goBack();

      // Promotion widgets stay off: no discounts card, and no tabs to a view that would show one.
      for (const name of [T.top, T.depth])
        await expect(page.getByRole('heading', { level: 2, name, exact: true })).toHaveCount(0);
      await expect(page.getByRole('tab')).toHaveCount(0);
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
      // Retailers are the offer sheet's columns: the evidence cell under each one's heading.
      const sheet = page.locator('[data-offer-sheet]');
      await expect(sheet.locator('thead th')).toHaveCount(productMixed.data.offers.length);
      const heads = await sheet.locator('thead th').allTextContents();
      const evidence = (name: string) =>
        sheet.locator('tr[data-attr=evidence] td').nth(heads.findIndex((h) => h.includes(name)));
      await expect(evidence('Ulta').locator('time')).toHaveText(T.offerImported);
      await expect(evidence('Ulta')).not.toContainText(T.captured);
      await expect(page.locator('main')).not.toContainText('Ulta Beauty UAE');
      await expect(evidence('Shop A').locator('time')).toHaveText(T.captured);
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
      // The collected fixture answers for Sephora.
      const a = page.locator('#kpi-band [data-tile="shop:sephora_ae"]');
      await expect(a.getByText(T.promo, { exact: true })).toBeVisible();
      await expect(a).toContainText(/18\.4\u200e?%/);
      await expect(a.getByText(T.fresh, { exact: true })).toBeVisible();
      await expect(a.locator('[role=tooltip]').filter({ hasText: T.age })).toHaveCount(1);
      await expect(a.getByText(T.snapshot, { exact: true })).toHaveCount(0);
      await expect(a).not.toContainText(T.parents);
      expect(mock.external).toEqual([]);
      expect(mock.errors).toEqual([]);
    });
  });
}
