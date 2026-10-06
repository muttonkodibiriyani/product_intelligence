import type { Page, Route } from '@playwright/test';
import {
  expect,
  golden,
  mockBackend,
  noHorizontalScroll,
  openNav,
  servingMeta,
  signIn,
  test,
} from './fixtures';

type Json = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any

const meta = servingMeta(golden('meta') as Json);
const compare = golden('compare') as Json;
const gaps = golden('assortment-gaps') as Json;
const promotions = golden('promotions') as Json;
const coverage = golden('coverage') as Json;
const products = golden('products') as Json;
const base = golden('insights') as Json;
// The golden with stock-outs at Shop B: one brand partly out, one whole brand the source reports unavailable.
const insights = {
  ...base,
  data: {
    ...base.data,
    stockouts: base.data.stockouts.map((s: Json) =>
      s.retailer === 'shop_b'
        ? {
            ...s,
            outOfStock: 6,
            qualifying: 1,
            brands: [{ brand: 'Half', observed: 12, outOfStock: 6 }],
            unavailableBrands: 1,
            unavailableListings: 113,
          }
        : s,
    ),
  },
};

// The live API before #231: every response says 1.16.0, and /insights does not exist.
const meta116 = { ...meta, meta: { ...meta.meta, apiVersion: '1.16.0' } };

async function api116(route: Route) {
  const p = new URL(route.request().url()).pathname;
  if (p === '/api/v1/meta') return route.fulfill({ json: meta116 });
  return route.fulfill({ status: 404, json: { error: { code: 'not_found', message: 'no route' } } });
}

// API with the new version on /meta, but /insights not deployed (404): honest, never an error card.
/**
 * Signed in and settled before a full reload. The shell shows once the session is stored; a reload
 * earlier lands on sign-in on Firefox and WebKit. Network idle means the Overview's own calls
 * (it asks /compare) have all been made, so a cleared log holds only what the next page asks.
 */
async function signedIn(page: Page, locale: 'en' | 'ar') {
  await signIn(page, locale);
  await expect(page.getByRole('navigation').first()).toBeVisible();
  await page.waitForLoadState('networkidle');
}

async function apiNoRoute(route: Route) {
  const p = new URL(route.request().url()).pathname;
  if (p === '/api/v1/meta') return route.fulfill({ json: meta });
  return route.fulfill({ status: 404, json: { error: { code: 'not_found', message: 'no route' } } });
}

async function api(route: Route) {
  const p = new URL(route.request().url()).pathname;
  const json = {
    '/api/v1/meta': meta,
    '/api/v1/insights': insights,
    '/api/v1/compare': compare,
    '/api/v1/assortment-gaps': gaps,
    '/api/v1/promotions': promotions,
    '/api/v1/coverage': coverage,
    '/api/v1/products': products,
  }[p];
  if (json) return route.fulfill({ json });
  return route.fulfill({ status: 404, json: { error: { code: 'not_found', message: 'no route' } } });
}

for (const locale of ['en', 'ar'] as const) {
  const T =
    locale === 'ar'
      ? {
          nav: 'الرؤى',
          title: 'الرؤى',
          sections: [
            'نظرة سريعة',
            'الأسعار بين المتاجر',
            'المخزون اليوم',
            'أفضل قيمة، حسب فئات كل متجر',
            'الأحجام الأكبر، السعر لكل مل أو غ',
            'أعمق التخفيضات',
          ],
          all: 'كل المتاجر',
          shops: 'المتاجر',
          unavailableLine: /يذكر المصدر أنها غير متاحة/,
          promo: 'كل التخفيضات لدى Shop A',
          unavailable: /الرؤى غير متاحة بعد/,
          noRoute: 'الرؤى غير متاحة بعد: خدمة البيانات لا تقدّمها. لن يُعرض شيء حتى تُحدَّث الخدمة.',
        }
      : {
          nav: 'Insights',
          title: 'Insights',
          sections: [
            'At a glance',
            'Prices across shops',
            'Stock today',
            "Best value, by each shop's own categories",
            'Bigger sizes, price per ml or g',
            'Deepest discounts',
          ],
          all: 'All shops',
          shops: 'Shops',
          unavailableLine: /Source reports unavailable/,
          promo: 'All discounts at Shop A',
          unavailable: /^Insights is not available yet/,
          noRoute:
            'Insights is not available yet: the data service does not serve it. Nothing is shown until the service is updated.',
        };

  test.describe(`${locale} insights`, () => {
    test('from the nav: every shop at a glance, sections in order, numbers open their lists', async ({
      page,
    }) => {
      const mock = await mockBackend(page, { onApi: api });
      await signIn(page, locale);
      await openNav(page, T.nav);
      await expect(page).toHaveURL(new RegExp(`/${locale}/insights/`));
      await expect(page.getByRole('heading', { name: T.title, level: 1 })).toBeVisible();
      await expect(page.getByRole('main').getByRole('heading', { level: 2 })).toHaveText(T.sections);
      const picker = page.getByRole('group', { name: T.shops });
      await expect(picker.getByRole('button')).toHaveCount(4);
      await expect(picker.getByRole('button', { name: T.all })).toHaveAttribute('aria-pressed', 'true');
      // One /insights per pair of collected shops (A, B, C), never a sum.
      const asked = mock.api
        .map((r) => new URL(r.url))
        .filter((u) => u.pathname === '/api/v1/insights')
        .map((u) => u.searchParams.get('retailers'));
      expect(new Set(asked)).toEqual(new Set(['shop_a,shop_b', 'shop_a,shop_c', 'shop_b,shop_c']));
      const stock = page.locator('section[aria-labelledby="ins-stock"]');
      await expect(stock.getByText(T.unavailableLine)).toBeVisible();
      await expect(stock).not.toContainText('%');
      await noHorizontalScroll(page);
      await stock.getByRole('link', { name: '6', exact: true }).first().click();
      await expect(page).toHaveURL(
        new RegExp(
          `/${locale}/explore/\\?retailer=shop_b&availability=out_of_stock&unavailableBrands=exclude$`,
        ),
      );
      expect(mock.errors).toEqual([]);
    });

    test('the selector narrows to one shop, and the old three-shop link lands on Insights', async ({
      page,
    }) => {
      await mockBackend(page, { onApi: api });
      await signedIn(page, locale);
      await page.goto(`/app/${locale}/insights/three/`);
      await expect(page).toHaveURL(new RegExp(`/${locale}/insights/$`));
      const picker = page.getByRole('group', { name: T.shops });
      await picker.getByRole('button', { name: 'Shop A' }).click();
      await expect(page).toHaveURL(new RegExp(`/${locale}/insights/\\?shop=shop_a$`));
      const promo = page.locator('section[aria-labelledby="ins-promo"]');
      await expect(promo.getByRole('heading', { level: 3 })).toHaveText(['Shop A']);
      await expect(promo.getByRole('link', { name: T.promo })).toHaveAttribute(
        'href',
        new RegExp(`/${locale}/promotions/\\?retailer=shop_a$`),
      );
    });

    test('an API without /insights (1.16.0): no nav entry; the page says so and requests nothing', async ({
      page,
    }) => {
      const mock = await mockBackend(page, { onApi: api116 });
      await signedIn(page, locale);
      await expect(page.getByRole('link', { name: T.nav, exact: true })).toHaveCount(0);
      mock.api.length = 0; // from here on, only what the Insights page asks
      await page.goto(`/app/${locale}/insights/`);
      await expect(page.getByText(T.unavailable)).toBeVisible();
      await expect(page.getByRole('heading', { level: 2 })).toHaveCount(0);
      const paths = mock.api.map((r) => new URL(r.url).pathname);
      expect(paths.filter((p) => /\/(insights|compare|assortment-gaps|promotions)$/.test(p))).toEqual([]);
      expect(mock.errors).toEqual([]);
    });

    test('/insights answers 404: the honest "not available yet", no error card, no section', async ({
      page,
    }) => {
      const mock = await mockBackend(page, { onApi: apiNoRoute });
      await signedIn(page, locale);
      mock.api.length = 0;
      await page.goto(`/app/${locale}/insights/`);
      await expect(page.getByText(T.noRoute)).toBeVisible();
      // A true 404: the page did ask /insights, and that is what it answered.
      expect(mock.api.map((r) => new URL(r.url).pathname)).toContain('/api/v1/insights');
      // Inside main: Next's route announcer is a role=alert outside it.
      await expect(page.getByRole('main').getByRole('alert')).toHaveCount(0);
      await expect(page.getByRole('heading', { level: 2 })).toHaveCount(0);
      expect(mock.errors).toEqual([]);
    });
  });
}
