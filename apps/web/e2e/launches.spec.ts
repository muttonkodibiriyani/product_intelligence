import type { Route } from '@playwright/test';
import {
  expect,
  golden,
  mockBackend,
  navLink,
  noHorizontalScroll,
  signedIn,
  signIn,
  test,
  type Mock,
} from './fixtures';

type Json = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any

// Three collection days for every collected shop: launches can exist.
const meta = golden('meta') as Json;
// The same dataset after its first run only: nothing to compare against yet.
const firstDay = { ...meta, data: { ...meta.data, dates: ['2026-09-30'] } };
// Shop C restarted on the last day: still waiting while A and B are in.
const oneBehind = {
  ...meta,
  data: {
    ...meta.data,
    retailers: meta.data.retailers.map((r: Json) => (r.id === 'shop_c' ? { ...r, since: '2026-09-30' } : r)),
  },
};
// Shop B imported as a one-off snapshot rather than collected.
const imported = {
  ...firstDay,
  caveats: [
    {
      code: 'snapshot_import_date',
      en: 'Shop B: snapshot imported 1 Oct 2026.',
      ar: 'المتجر ب: لقطة مستوردة في 1 أكتوبر 2026.',
      params: { retailer: 'shop_b', date: '2026-10-01' },
    },
  ],
};
// ok, one item (p14 at shop_b) and a launches_withheld caveat.
const golden1 = golden('launches') as Json;
const items = [
  { firstSeen: '2026-09-29', id: 'p14', name: 'Product p14', retailer: 'shop_b' },
  { firstSeen: '2026-09-27', id: 'p12', name: 'Product p12', retailer: 'shop_a' },
  { firstSeen: '2026-09-20', id: 'p09', name: 'Product p09', retailer: 'shop_a' },
];
const launches = { ...golden1, data: { items, total: 3, truncated: false } };
const cut = { ...launches, data: { items, total: 40, truncated: true } };
const notApplicable = {
  ...golden1,
  status: 'not_enough_data',
  reason: 'not_applicable',
  caveats: [],
  data: { items: [], total: 0, truncated: false },
};
const product = golden('product') as Json;
const history = golden('history') as Json;

function api(metaBody: Json = meta, launchesFor: (u: URL) => Json = () => launches) {
  return async (route: Route) => {
    const u = new URL(route.request().url());
    const p = u.pathname;
    if (p === '/api/v1/meta') return route.fulfill({ json: metaBody });
    if (p === '/api/v1/launches') return route.fulfill({ json: launchesFor(u) });
    if (/^\/api\/v1\/products\/[^/]+\/history$/.test(p)) return route.fulfill({ json: history });
    if (/^\/api\/v1\/products\/[^/]+$/.test(p)) return route.fulfill({ json: product });
    return route.fulfill({ status: 404, json: { error: { code: 'not_found', message: 'no route' } } });
  };
}

const calls = (mock: Mock) =>
  mock.api.map((r) => new URL(r.url)).filter((u) => u.pathname === '/api/v1/launches');

for (const locale of ['en', 'ar'] as const) {
  const T =
    locale === 'ar'
      ? {
          nav: 'الجديد',
          soon: 'قريبًا',
          title: 'المنتجات الجديدة',
          notYet: 'تظهر المنتجات الجديدة بعد جمع بيانات كل متجر في يومين منفصلين على الأقل',
          readiness: 'أيام الجمع لكل متجر',
          // Engines differ on the Arabic medium date (30 سبتمبر 2026 vs 30‏/09‏/2026).
          oneDay: /يوم جمع واحد، آخرها .*2026/,
          imported: /لقطة لمرة واحدة، حُمِّلت .*2026/,
          oneOfTwo: '1 من 2',
          promotions: 'اطّلع على العروض الحالية',
          browse: 'تصفّح كل المنتجات',
          newIn30: 'أول رصد في آخر 30 يومًا',
          newIn7: 'أول رصد في آخر 7 أيام',
          window: 'الفترة',
          days7: '7 أيام',
          days30: '30 يومًا',
          three: '3 منتجات',
          of40: '3 من 40 منتج',
          more: 'اعرض حتى 500',
          // The golden retailer names are English in both languages: the page never translates them.
          pending: 'Shop C غير مشمول بعد: 1 من يومي جمع.',
          notApplicable: 'المنتجات الجديدة غير متاحة لهذه البيانات بعد.',
          notApplicableWhy: 'هذا العرض لا ينطبق على هذا النوع من الكتالوجات.',
          asOf: /البيانات حتى .*2026/,
          back: 'العودة إلى المنتجات الجديدة',
        }
      : {
          nav: 'Launches',
          soon: 'soon',
          title: 'Launches',
          notYet: 'Launches appear once each shop has been collected on at least two separate days',
          readiness: 'Collection days per shop',
          oneDay: /1 collection day, latest 30 Sept? 2026/,
          imported: 'One-off snapshot, loaded 1 Oct 2026',
          oneOfTwo: '1 of 2',
          promotions: "See what's on promotion",
          browse: 'Browse all products',
          newIn30: 'First observed in the last 30 days',
          newIn7: 'First observed in the last 7 days',
          window: 'Window',
          days7: '7 days',
          days30: '30 days',
          three: '3 products',
          of40: '3 of 40 products',
          more: 'Show up to 500',
          pending: 'Shop C is not included yet: 1 of 2 collection days.',
          notApplicable: "Launches aren't available for this dataset yet.",
          notApplicableWhy: "This view doesn't apply to this kind of catalogue.",
          asOf: /Data as of 30 Sept? 2026/,
          back: 'Back to launches',
        };

  test.describe(`${locale} launches, empty: one collection day`, () => {
    test('says what it waits for, where each shop stands, and offers two ways on; no list, no filters', async ({
      page,
    }) => {
      const mock = await mockBackend(page, { onApi: api(firstDay) });
      await signIn(page, locale);
      // The nav keeps the page reachable and marks it "soon".
      const link = await navLink(page, T.nav);
      await expect(link).toContainText(T.soon);
      await link.click();
      await expect(page).toHaveURL(new RegExp(`/app/${locale}/launches/$`));
      await expect(page.getByRole('heading', { level: 1, name: T.title })).toBeVisible();
      await expect(page.getByRole('heading', { level: 2, name: T.notYet })).toBeVisible();
      // One row per collected shop (the blocked one is not a shop that could launch anything).
      const strip = page.getByRole('list', { name: T.readiness });
      const rows = strip.getByRole('listitem');
      await expect(rows).toHaveCount(3);
      await expect(rows.first()).toContainText('Shop A');
      await expect(rows.first()).toContainText(T.oneDay);
      await expect(rows.first()).toContainText(T.oneOfTwo);
      await expect(page.getByRole('link', { name: T.promotions })).toHaveAttribute(
        'href',
        `/app/${locale}/promotions/`,
      );
      await expect(page.getByRole('link', { name: T.browse })).toHaveAttribute(
        'href',
        `/app/${locale}/explore/`,
      );
      await expect(page.locator('main table')).toHaveCount(0);
      await expect(page.locator('main input')).toHaveCount(0);
      await expect(page.locator('main').getByRole('group')).toHaveCount(0);
      // Nothing is asked of /launches: there is nothing it could answer yet.
      expect(calls(mock)).toEqual([]);
      await noHorizontalScroll(page);
      expect(mock.external).toEqual([]);
      expect(mock.errors).toEqual([]);
    });

    test('an imported snapshot counts as one day, dated by its import', async ({ page }) => {
      const mock = await mockBackend(page, { onApi: api(imported) });
      await signedIn(page, locale);
      await page.goto(`/app/${locale}/launches/`);
      const b = page.getByRole('list', { name: T.readiness }).getByRole('listitem').nth(1);
      await expect(b).toContainText('Shop B');
      await expect(b).toContainText(T.imported);
      await expect(b).toContainText(T.oneOfTwo);
      expect(calls(mock)).toEqual([]);
      expect(mock.errors).toEqual([]);
    });
  });

  test.describe(`${locale} launches, populated: three collection days`, () => {
    test('lists the last 30 days newest first, dated by the data, with no caveat box and no "soon"', async ({
      page,
    }) => {
      const mock = await mockBackend(page, { onApi: api() });
      await signIn(page, locale);
      const link = await navLink(page, T.nav);
      await expect(link).not.toContainText(T.soon);
      // The Overview asks /launches per shop for its band; the page's own call comes after these.
      const before = calls(mock).length;
      await link.click();
      await expect(page).toHaveURL(new RegExp(`/app/${locale}/launches/$`));
      await expect(page.getByRole('heading', { level: 1, name: T.title })).toBeVisible();
      await expect(page.getByRole('heading', { level: 2, name: T.newIn30 })).toBeVisible();
      // The data is explained once, on Dataset: the served caveat draws no box here.
      await expect(page.locator('main')).toContainText(T.asOf);
      await expect(page.getByRole('note')).toHaveCount(0);
      await expect(page.locator('main')).not.toContainText(golden1.caveats[0][locale]);
      await expect(page.getByText(T.three)).toBeVisible();
      const rows = page.locator('#rows ul:visible > li, #rows table:visible tbody tr');
      await expect(rows).toHaveCount(3);
      await expect(rows.first()).toContainText('Product p14');
      await expect(rows.first()).toContainText('Shop B');
      await expect(rows.first().locator('time')).toHaveAttribute('datetime', '2026-09-29');
      await expect(rows.last()).toContainText('Product p09');
      // 30 days back from the cutoff day (30 Sep), that day included.
      const first = calls(mock)[before]!;
      expect([...first.searchParams.keys()].sort()).toEqual(['limit', 'since']);
      expect(first.searchParams.get('since')).toBe('2026-09-01');
      expect(first.searchParams.get('limit')).toBe('100');
      await noHorizontalScroll(page);
      expect(mock.external).toEqual([]);
      expect(mock.errors).toEqual([]);
    });

    test('the 7-day window goes into the URL and the request', async ({ page }) => {
      const mock = await mockBackend(page, { onApi: api() });
      await signedIn(page, locale);
      await page.goto(`/app/${locale}/launches/`);
      await expect(page.locator('#rows ul:visible > li, #rows table:visible tbody tr')).toHaveCount(3);
      const group = page.getByRole('group', { name: T.window });
      await expect(group.getByRole('button', { name: T.days30 })).toHaveAttribute('aria-pressed', 'true');
      await group.getByRole('button', { name: T.days7 }).click();
      await expect(page).toHaveURL(/\?days=7$/);
      await expect(page.getByRole('heading', { level: 2, name: T.newIn7 })).toBeVisible();
      await expect.poll(() => calls(mock).at(-1)!.searchParams.get('since')).toBe('2026-09-24');
      await group.getByRole('button', { name: T.days30 }).click();
      await expect(page).toHaveURL(new RegExp(`/app/${locale}/launches/$`));
      expect(mock.errors).toEqual([]);
    });

    test('a shop still short of two days is named under the list', async ({ page }) => {
      const mock = await mockBackend(page, { onApi: api(oneBehind) });
      await signedIn(page, locale);
      await page.goto(`/app/${locale}/launches/`);
      await expect(page.locator('#rows ul:visible > li, #rows table:visible tbody tr')).toHaveCount(3);
      await expect(page.locator('#launch-pending')).toHaveText(T.pending);
      await expect(page.getByRole('note')).toHaveCount(0);
      await expect(await navLink(page, T.nav)).toContainText(T.soon);
      expect(mock.errors).toEqual([]);
    });

    test('a cut list says N of total and can ask for up to 500', async ({ page }) => {
      const mock = await mockBackend(page, {
        onApi: api(meta, (u) => (u.searchParams.get('limit') === '500' ? launches : cut)),
      });
      await signedIn(page, locale);
      await page.goto(`/app/${locale}/launches/`);
      await expect(page.getByText(T.of40)).toBeVisible();
      await page.getByRole('button', { name: T.more }).click();
      await expect(page).toHaveURL(/limit=500/);
      await expect(page.getByText(T.three)).toBeVisible();
      expect(calls(mock).at(-1)!.searchParams.get('limit')).toBe('500');
      expect(mock.errors).toEqual([]);
    });

    test('a catalogue the view does not apply to says so, with no empty table', async ({ page }) => {
      const mock = await mockBackend(page, { onApi: api(meta, () => notApplicable) });
      await signedIn(page, locale);
      await page.goto(`/app/${locale}/launches/`);
      const line = page.getByRole('status').filter({ hasText: T.notApplicable });
      await expect(line).toBeVisible();
      // The API's reason, in the user's language, on the same line.
      await expect(line).toHaveText(`${T.notApplicable} ${T.notApplicableWhy}`);
      await expect(page.getByRole('note')).toHaveCount(0);
      await expect(page.locator('#rows')).toHaveCount(0);
      expect(mock.errors).toEqual([]);
    });

    test('a row opens its product, and Back returns to the same launches view', async ({ page }) => {
      const mock = await mockBackend(page, { onApi: api() });
      await signedIn(page, locale);
      await page.goto(`/app/${locale}/launches/?days=7`);
      await page.getByRole('link', { name: 'Product p12' }).click();
      await expect(page).toHaveURL(/\/product\/\?id=p12&back=launches&from=days%3D7$/);
      await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
      await page.getByRole('link', { name: T.back }).click();
      await expect(page).toHaveURL(new RegExp(`/app/${locale}/launches/\\?days=7$`));
      await expect(page.locator('#rows ul:visible > li, #rows table:visible tbody tr')).toHaveCount(3);
      expect(mock.errors).toEqual([]);
    });
  });
}
