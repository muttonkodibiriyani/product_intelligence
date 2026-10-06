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
const base = golden('insights') as Json;
// The golden with stock-out counts at Shop B, so the stock card has something to show.
const insights = {
  ...base,
  data: {
    ...base.data,
    stockouts: base.data.stockouts.map((s: Json) =>
      s.retailer === 'shop_b'
        ? { ...s, qualifying: 1, brands: [{ brand: 'Balmain', observed: 113, outOfStock: 113 }] }
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
          cards: ['نفاد مخزون العلامات', 'فرق السعر حسب الحجم', 'استراتيجية العروض', 'فجوات التشكيلة'],
          readiness: '4 إشارات قرار جاهزة',
          deferred: 'تحليلان غير جاهزين',
          stock: 'Balmain في Shop B: 113 قائمة مرصودة نافدة من المخزون من بين 113 قائمة مرصودة في آخر رصد.',
          promoHeadline: 'أعمق تخفيض مُدرج هو Product p05 لدى Shop A: −33.3%.',
          promo: 'افتح العروض',
          unavailable: /الرؤى غير متاحة بعد/,
          noRoute: 'الرؤى غير متاحة بعد: خدمة البيانات لا تقدّمها. لن يُعرض شيء حتى تُحدَّث الخدمة.',
        }
      : {
          nav: 'Insights',
          title: 'Insights',
          cards: ['Brand stock-outs', 'Price gap by size', 'Promotion strategy', 'Assortment white space'],
          readiness: '4 decision signals are ready',
          deferred: '2 analyses are not ready',
          stock:
            'Balmain at Shop B: 113 observed out-of-stock listings among 113 observed listings in the latest crawl.',
          promoHeadline: 'Product p05 at Shop A has the deepest listed cut: −33.3%.',
          promo: 'Open Promotions',
          unavailable: /^Insights is not available yet/,
          noRoute:
            'Insights is not available yet: the data service does not serve it. Nothing is shown until the service is updated.',
        };

  test.describe(`${locale} insights`, () => {
    test('from the nav: ready evidence leads and unavailable analyses do not become dead cards', async ({
      page,
    }) => {
      const mock = await mockBackend(page, { onApi: api });
      await signIn(page, locale);
      await openNav(page, T.nav);
      await expect(page).toHaveURL(new RegExp(`/${locale}/insights/`));
      await expect(page.getByRole('heading', { name: T.title, level: 1 })).toBeVisible();
      await expect(page.getByRole('heading', { name: T.readiness, level: 2 })).toBeVisible();
      const cardTitles = page.locator('main .grid.grid-cols-12 > section > header h2');
      await expect(cardTitles).toHaveText(T.cards);
      await expect(page.getByText(T.deferred)).toBeVisible();
      await expect(page.getByText(T.stock)).toBeVisible();
      // The page asks for the first two collected shops when the URL names none.
      const asked = mock.api.map((r) => new URL(r.url)).find((u) => u.pathname === '/api/v1/insights');
      expect(asked?.searchParams.get('retailers')).toBe('shop_a,shop_b');
      await noHorizontalScroll(page);
      await page.getByRole('link', { name: 'Balmain' }).click();
      await expect(page).toHaveURL(new RegExp(`/${locale}/explore/\\?brand=Balmain&retailer=shop_b$`));
      expect(mock.errors).toEqual([]);
    });

    test('the promotions card shows ranked measured evidence and links to its full view', async ({
      page,
    }) => {
      await mockBackend(page, { onApi: api });
      await signedIn(page, locale);
      await page.goto(`/app/${locale}/insights/`);
      // The card: the one section whose own heading is this card's (the page section holds all six).
      const card = page
        .locator('main section section')
        .filter({ has: page.getByRole('heading', { level: 2, name: T.cards[2] }) });
      await expect(card).toHaveCount(1);
      await expect(page.getByText(T.promoHeadline)).toBeVisible();
      await expect(card.getByRole('listitem')).toHaveCount(3);
      await expect(card.getByRole('link', { name: T.promo })).toHaveAttribute(
        'href',
        new RegExp(`/${locale}/promotions/$`),
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

    test('/insights answers 404: the honest "not available yet", no error card, no card', async ({
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
      await expect(page.getByRole('combobox')).toHaveCount(0);
      expect(mock.errors).toEqual([]);
    });
  });
}
