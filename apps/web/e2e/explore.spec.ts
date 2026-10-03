import type { Page, Route } from '@playwright/test';
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
const clone = <T>(v: T): T => structuredClone(v);

const meta = golden('meta') as Json;
const products = golden('products') as Json; // page 1 of 3, sort=price_asc golden, nextCursor set
const gapPage = golden('products-gap') as Json; // shop_a vs shop_b, with gaps
const emptyPage = golden('products-filtered') as Json; // total 0
const product = golden('product') as Json;
const history = golden('history') as Json;
const stale = golden('error-stale-cursor') as Json;

const PNG = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=',
  'base64',
);
const IMG = 'https://img-product.sephora.me/v1/p07.jpg';
const IMG_BROKEN = 'https://img-product.sephora.me/v1/p08.jpg';
/** Ulta UAE's own image host, allowlisted for its view (owner decision). */
const IMG_ULTA =
  'https://media.alshaya.com/adobe/assets/urn:aaid:aem:127339d4-dd12-4a65-bc02-9685026f9ab2/as/SK-345530811_1.png?width=533&height=800&preferwebp=true';
/** The same asset after its file was renamed: the host answers 404. */
const IMG_ULTA_GONE = IMG_ULTA.replace('SK-345530811_1', 'SK-345530811_2');
/** A look-alike host: only the exact hostname is allowed. */
const IMG_LOOKALIKE = 'https://img-product.sephora.me.evil.example/v1/p09.jpg';

/** The products golden with the given images, row by row, for a list of `retailer`'s products. */
function withImages(retailer: string, images: (string | null)[]): Json {
  const page = clone(products);
  page.data.items = page.data.items.map((c: Json, i: number) => ({
    ...c,
    image: images[i] ?? null,
    prices: { [retailer]: c.prices.shop_a },
  }));
  return page;
}

/** The explorer's API: answers by path and by query, and records what was asked. */
function api(over: { products?: (u: URL) => Json; product?: Json; history?: Json; meta?: Json } = {}) {
  return async (route: Route) => {
    const u = new URL(route.request().url());
    const p = u.pathname;
    if (p === '/api/v1/meta') return route.fulfill({ json: over.meta ?? meta });
    if (p === '/api/v1/products') return route.fulfill({ json: over.products?.(u) ?? products });
    if (/^\/api\/v1\/products\/[^/]+\/history$/.test(p))
      return route.fulfill({ json: over.history ?? history });
    if (/^\/api\/v1\/products\/[^/]+$/.test(p)) return route.fulfill({ json: over.product ?? product });
    return route.fulfill({ status: 404, json: { error: { code: 'not_found', message: 'no route' } } });
  };
}

/** Signs in and waits until the session is live, so a following goto doesn't race it. */
async function signedIn(page: Page, locale: 'en' | 'ar') {
  await signIn(page, locale);
  await expect(page.getByRole('navigation')).toBeVisible();
}

const productCalls = (mock: Mock) =>
  mock.api.map((r) => new URL(r.url)).filter((u) => u.pathname === '/api/v1/products');

for (const locale of ['en', 'ar'] as const) {
  const rtl = locale === 'ar';
  const T = rtl
    ? {
        nav: 'المنتجات',
        title: 'المنتجات',
        count16: '16 منتجًا',
        more: /اعرض \d+ أخرى/,
        restarted: 'تحدّثت البيانات أثناء التصفح',
        empty: 'لا منتجات تطابق عوامل التصفية هذه.',
        emptyMatched: 'لم يُؤكَّد بعد أن أيّ منتج هنا هو المنتج نفسه في متجر آخر.',
        emptyMatchedLink: 'قارن حسب الفئة',
        gap: 'الفرق',
        swap: 'بدّل الأساس',
        sort: 'الترتيب',
        notCounted: 'غير محسوب',
        back: 'العودة إلى المنتجات',
        offers: 'العروض بتاريخ',
        pairs: 'فروق الأسعار',
        history: 'سجل الأسعار',
        table: 'اعرض كجدول',
        source: 'افتح الصفحة',
        noSource: 'لا رابط للصفحة',
        filters: 'عوامل التصفية',
        done: 'تم',
        activeFilters: 'عوامل التصفية النشطة',
        shopChip: 'المتجر: Shop A',
        verdict: 'Shop B أغلى بنسبة 25.0%',
        noImage: 'لا صورة',
        underReview: 'السعر قيد المراجعة',
        results: 'النتائج',
        grid: 'شبكة',
        list: 'قائمة',
      }
    : {
        nav: 'Products',
        title: 'Products',
        count16: '16 products',
        more: /Show \d+ more/,
        restarted: 'The data was updated while you browsed',
        empty: 'No products match these filters.',
        emptyMatched: 'No product here is confirmed as the same item at another shop yet.',
        emptyMatchedLink: 'Compare by category',
        gap: 'Gap',
        swap: 'Swap base',
        sort: 'Sort',
        notCounted: 'Not counted',
        back: 'Back to products',
        offers: 'Offers on',
        pairs: 'Price gaps',
        history: 'Price history',
        table: 'Show as table',
        source: 'Open page',
        noSource: 'No page link',
        filters: 'Filters',
        done: 'Done',
        activeFilters: 'Active filters',
        shopChip: 'Shop: Shop A',
        verdict: 'Shop B 25.0% dearer',
        noImage: 'No image',
        underReview: 'Price under review',
        results: 'Results',
        grid: 'Grid',
        list: 'List',
      };

  /** The product cards: the explorer's default view. */
  const cards = (page: Page) => page.getByRole('list', { name: T.results }).getByRole('listitem');
  /** Switches to the dense list (a table), the view the column tests are about. */
  async function asList(page: Page) {
    // Exact: the phone menu button ("القائمة") would otherwise match the Arabic "قائمة".
    await page.getByRole('button', { name: T.list, exact: true }).click();
    await expect(page.getByRole('table')).toBeVisible();
  }

  /** Opens the filters on a narrow screen, where they live in a bottom sheet. */
  async function filters(page: Page) {
    const toggle = page.getByRole('button', { name: new RegExp(`^${T.filters}`) });
    if (await toggle.isVisible()) {
      await toggle.click();
      await expect(page.getByRole('dialog')).toBeVisible();
    }
  }
  /** Closes that sheet again (a no-op on a wide screen), so the list behind it can be used. */
  async function doneWithFilters(page: Page) {
    const done = page.getByRole('dialog').getByRole('button', { name: T.done });
    if (await done.isVisible()) {
      await done.click();
      await expect(page.getByRole('dialog')).toBeHidden();
    }
  }

  test.describe(`${locale} explorer`, () => {
    test('lists products with a Bearer token; columns, counts and facets come from the API', async ({
      page,
      context,
    }) => {
      const mock = await mockBackend(page, { onApi: api() });
      await signIn(page, locale);
      await page.getByRole('navigation').getByRole('link', { name: T.nav }).click();
      await expect(page).toHaveURL(new RegExp(`/app/${locale}/explore/$`));
      await expect(page.getByRole('heading', { level: 1, name: T.title })).toBeVisible();
      await expect(page.getByText(T.count16)).toBeVisible();
      // Cards first: one per product, the grid button pressed.
      await expect(cards(page)).toHaveCount(products.data.items.length);
      await expect(page.getByRole('button', { name: T.grid, exact: true })).toHaveAttribute(
        'aria-pressed',
        'true',
      );
      await expect(page.getByRole('link', { name: products.data.items[0].name })).toBeVisible();
      await noHorizontalScroll(page);
      // The list is one click away, and stays the choice after a reload.
      await asList(page);
      const rows = page.getByRole('table').getByRole('row');
      await expect(rows).toHaveCount(1 + products.data.items.length);
      await expect(page.getByRole('columnheader', { name: 'Shop A' })).toBeVisible();
      await noHorizontalScroll(page);
      await page.reload();
      await expect(page.getByRole('button', { name: T.list, exact: true })).toHaveAttribute(
        'aria-pressed',
        'true',
      );
      await expect(rows).toHaveCount(1 + products.data.items.length);
      await page.getByRole('button', { name: T.grid, exact: true }).click();
      await expect(cards(page)).toHaveCount(products.data.items.length);

      const first = productCalls(mock)[0]!;
      expect(first.searchParams.get('sort')).toBe('name');
      expect(first.searchParams.get('limit')).toBe('50');
      expect(first.searchParams.has('cursor')).toBe(false);
      for (const r of mock.api) {
        expect(r.headers.authorization).toMatch(/^Bearer /);
        expect(r.headers.cookie).toBeUndefined();
      }
      expect(await context.cookies()).toEqual([]);
      expect(mock.external).toEqual([]);
      expect(mock.errors).toEqual([]);
    });

    test('two retailers make a pair: gap column, gap sort, swap keeps the order in the request', async ({
      page,
    }) => {
      const mock = await mockBackend(page, {
        onApi: api({
          products: (u) => (u.searchParams.getAll('retailer').length === 2 ? gapPage : products),
        }),
      });
      await signedIn(page, locale);
      await page.goto(`/app/${locale}/explore/`);
      const sort = page.getByLabel(T.sort);
      await expect(sort.locator('option[value=gap]')).toBeDisabled();
      await expect(page.getByRole('list', { name: T.activeFilters })).toHaveCount(0);

      await filters(page);
      await page.getByRole('checkbox', { name: /Shop A/ }).check();
      await page.getByRole('checkbox', { name: /Shop B/ }).check();
      await expect(page).toHaveURL(/retailer=shop_a&retailer=shop_b/);
      await doneWithFilters(page);
      // The picked shops are chips above the list; the card says how the other shop compares, from
      // the API's gap: p05 is base 80 vs other 100, so Shop B is 25% dearer.
      const chips = page.getByRole('list', { name: T.activeFilters });
      await expect(chips.getByRole('button', { name: new RegExp(`^${T.shopChip}`) })).toBeVisible();
      await expect(cards(page).filter({ hasText: 'Product p05' }).getByText(T.verdict)).toBeVisible();
      await noHorizontalScroll(page);

      await asList(page);
      await expect(page.getByRole('columnheader', { name: new RegExp(T.gap) })).toBeVisible();
      // p05: base 80, other 100 → +20.00, +25.0%
      await expect(page.getByRole('row', { name: /Product p05/ })).toContainText('+25.0%');

      await sort.selectOption('gap');
      await expect(page).toHaveURL(/sort=gap/);
      await page.getByRole('button', { name: T.swap }).click();
      await expect(page).toHaveURL(/retailer=shop_b&retailer=shop_a/);
      const last = productCalls(mock).at(-1)!;
      expect(last.searchParams.getAll('retailer')).toEqual(['shop_b', 'shop_a']);
      expect(last.searchParams.get('sort')).toBe('gap');
      await noHorizontalScroll(page);
      expect(mock.errors).toEqual([]);
    });

    test('next page with the cursor; a stale cursor restarts the list and says so', async ({ page }) => {
      let stalePage = true;
      const mock = await mockBackend(page, {
        onApi: async (route) => {
          const u = new URL(route.request().url());
          if (u.pathname === '/api/v1/products' && u.searchParams.has('cursor') && stalePage) {
            stalePage = false;
            return route.fulfill({ status: 409, json: stale });
          }
          return api()(route);
        },
      });
      await signedIn(page, locale);
      await page.goto(`/app/${locale}/explore/`);
      await page.getByRole('button', { name: T.more }).click();
      await expect(page.getByText(T.restarted)).toBeVisible();
      // Restarted from page 1: the list is not doubled.
      await expect(cards(page)).toHaveCount(products.data.items.length);
      const calls = productCalls(mock);
      expect(calls.at(-2)!.searchParams.get('cursor')).toBe(products.data.nextCursor);
      expect(calls.at(-1)!.searchParams.has('cursor')).toBe(false);

      await page.getByRole('button', { name: T.more }).click();
      await expect(cards(page)).toHaveCount(2 * products.data.items.length);
      expect(mock.errors).toEqual([]);
    });

    test('Sephora UAE thumbnails: hotlinked lazily without a referrer; a failing one is a placeholder', async ({
      page,
    }) => {
      const mock = await mockBackend(page, {
        onApi: withSummary(api({ products: () => withImages('sephora_ae', [IMG, IMG_BROKEN, null]) })),
      });
      const images: { url: string; referer?: string }[] = [];
      await page.route('https://img-product.sephora.me/**', (r) => {
        images.push({ url: r.request().url(), referer: r.request().headers()['referer'] });
        return r.request().url() === IMG
          ? r.fulfill({ contentType: 'image/png', body: PNG })
          : r.fulfill({ status: 404, body: '' });
      });
      await signedIn(page, locale);
      await page.goto(`/app/${locale}/explore/`);
      const rows = cards(page);
      await expect(rows).toHaveCount(3);

      const img = rows.nth(0).locator('img');
      await expect(img).toHaveAttribute('src', IMG);
      await expect(img).toHaveAttribute('loading', 'lazy');
      await expect(img).toHaveAttribute('referrerpolicy', 'no-referrer');
      await expect(img).toHaveAttribute('width', '320');
      await expect.poll(() => img.evaluate((e: HTMLImageElement) => e.complete && e.naturalWidth)).toBe(1);
      // Never through an image proxy or loader: the browser asks the image host itself.
      expect(await img.getAttribute('srcset')).toBeNull();

      for (const i of [1, 2]) {
        await expect(rows.nth(i).locator('img')).toHaveCount(0);
        await expect(rows.nth(i).getByRole('img', { name: T.noImage })).toBeVisible();
      }
      // The product name stays the card's link, under the picture.
      await expect(rows.nth(0).getByRole('link', { name: products.data.items[0].name })).toBeVisible();
      await noHorizontalScroll(page);
      expect(images.map((r) => r.url).sort()).toEqual([IMG, IMG_BROKEN]);
      for (const r of images) expect(r.referer).toBeUndefined();
      expect(mock.external).toEqual([]);
      expect(mock.errors.filter((e) => !/404/.test(e))).toEqual([]);
    });

    test('Ulta UAE thumbnails: its own host renders lazily without a referrer; a look-alike host never', async ({
      page,
    }) => {
      const mock = await mockBackend(page, {
        onApi: withSummary(
          api({ products: () => withImages('ulta_ae', [IMG_ULTA, IMG_ULTA_GONE, IMG_LOOKALIKE]) }),
        ),
      });
      const images: { url: string; referer?: string }[] = [];
      await page.route('https://media.alshaya.com/**', (r) => {
        images.push({ url: r.request().url(), referer: r.request().headers()['referer'] });
        return r.request().url() === IMG_ULTA
          ? r.fulfill({ contentType: 'image/png', body: PNG })
          : r.fulfill({ status: 404, body: '' });
      });
      await signedIn(page, locale);
      await page.goto(`/app/${locale}/explore/`);
      const rows = cards(page);
      await expect(rows).toHaveCount(3);
      const img = rows.nth(0).locator('img');
      await expect(img).toHaveAttribute('src', IMG_ULTA);
      await expect(img).toHaveAttribute('loading', 'lazy');
      await expect(img).toHaveAttribute('referrerpolicy', 'no-referrer');
      await expect.poll(() => img.evaluate((e: HTMLImageElement) => e.complete && e.naturalWidth)).toBe(1);
      // The renamed file (404) and the look-alike host: each the placeholder.
      for (const i of [1, 2]) {
        await expect(rows.nth(i).locator('img')).toHaveCount(0);
        await expect(rows.nth(i).getByRole('img', { name: T.noImage })).toBeVisible();
      }
      await noHorizontalScroll(page);
      expect(images.map((r) => r.url).sort()).toEqual([IMG_ULTA, IMG_ULTA_GONE].sort());
      for (const r of images) expect(r.referer).toBeUndefined();
      expect(mock.external).toEqual([]);
      expect(mock.errors.filter((e) => !/404/.test(e))).toEqual([]);
    });

    for (const [host, url] of [
      ['img-product.sephora.me', IMG],
      ['media.alshaya.com', IMG_ULTA],
    ] as const)
      test(`product page: the ${host} image beside the name; a failing one is a placeholder`, async ({
        page,
      }) => {
        const p = clone(product);
        p.data.card.image = url;
        const mock = await mockBackend(page, { onApi: api({ product: p }) });
        let ok = true;
        await page.route(`https://${host}/**`, (r) =>
          ok ? r.fulfill({ contentType: 'image/png', body: PNG }) : r.fulfill({ status: 404, body: '' }),
        );
        await signedIn(page, locale);
        await page.goto(`/app/${locale}/product/?id=${p.data.card.id}`);
        await expect(page.getByRole('heading', { level: 1, name: p.data.card.name })).toBeVisible();
        const header = page.locator('article header');
        const img = header.locator('img');
        await expect(img).toHaveAttribute('src', url);
        await expect(img).toHaveAttribute('loading', 'lazy');
        await expect(img).toHaveAttribute('referrerpolicy', 'no-referrer');
        await expect(img).toHaveAttribute('width', '96');
        await expect.poll(() => img.evaluate((e: HTMLImageElement) => e.complete && e.naturalWidth)).toBe(1);
        await noHorizontalScroll(page);

        ok = false;
        await page.reload();
        await expect(page.getByRole('heading', { level: 1, name: p.data.card.name })).toBeVisible();
        await expect(header.getByRole('img', { name: T.noImage })).toBeVisible();
        await expect(header.locator('img')).toHaveCount(0);
        expect(mock.external).toEqual([]);
        expect(mock.errors.filter((e) => !/404/.test(e))).toEqual([]);
      });

    test('product page: a price of 0.01 or less reads "Price under review" in offers and history, never the number', async ({
      page,
    }) => {
      const p = clone(product);
      const low = (amount: string) => ({ amount, currency: 'AED', minor: Math.round(Number(amount) * 100) });
      p.data.offers[0].price = low('0.01');
      p.data.offers[0].regular = low('0.00');
      const h = clone(history);
      h.data.series.shop_a[1].price = low('0.01');
      await mockBackend(page, { onApi: api({ product: p, history: h }) });
      await signedIn(page, locale);
      await page.goto(`/app/${locale}/product/?id=${p.data.card.id}`);
      await expect(page.getByRole('heading', { level: 1, name: p.data.card.name })).toBeVisible();
      const row = page
        .getByRole('row')
        .filter({ has: page.getByRole('rowheader', { name: 'Shop A', exact: true }) });
      await expect(row.first().getByText(T.underReview)).toHaveCount(2);
      await expect(page.getByText(T.underReview)).toHaveCount(3);
      await expect(page.locator('main')).not.toContainText(/(^|[^\d])0\.0[01]([^\d]|$)/);
    });

    test('no results: says so plainly', async ({ page }) => {
      await mockBackend(page, { onApi: api({ products: () => emptyPage }) });
      await signedIn(page, locale);
      await page.goto(`/app/${locale}/explore/?brand=Sample+Labs&retailer=shop_c`);
      await expect(page.getByText(T.empty)).toBeVisible();
      await expect(page.getByRole('table')).toHaveCount(0);
      await expect(page.getByRole('list', { name: T.results })).toHaveCount(0);
    });

    test('sold at both shops with no published pair: says why and links to the category prices', async ({
      page,
    }) => {
      await mockBackend(page, { onApi: api({ products: () => emptyPage }) });
      await signedIn(page, locale);
      await page.goto(`/app/${locale}/explore/?matched=true`);
      await expect(page.getByText(T.emptyMatched)).toBeVisible();
      await expect(page.getByText(T.empty)).toHaveCount(0);
      const link = page.getByRole('link', { name: T.emptyMatchedLink });
      await expect(link).toHaveAttribute('href', new RegExp(`/app/${locale}/prices/?$`));
      await link.click();
      await expect(page).toHaveURL(new RegExp(`/app/${locale}/prices/`));
    });

    test('sold at both shops plus a brand, nothing listed: the generic "no products match"', async ({
      page,
    }) => {
      await mockBackend(page, { onApi: api({ products: () => emptyPage }) });
      await signedIn(page, locale);
      await page.goto(`/app/${locale}/explore/?matched=true&brand=Sample+Labs`);
      await expect(page.getByText(T.empty)).toBeVisible();
      await expect(page.getByText(T.emptyMatched)).toHaveCount(0);
    });

    test('product page: offers with evidence, gaps, history; back keeps the filters', async ({ page }) => {
      const p = clone(product);
      p.data.offers[0].evidence.url = 'https://shop-a.example/p01';
      p.data.offers[1].evidence.url = 'javascript:alert(1)';
      const mock = await mockBackend(page, { onApi: api({ product: p }) });
      await signedIn(page, locale);
      await page.goto(`/app/${locale}/explore/?brand=Fixture+Beauty`);
      await page.getByRole('link', { name: products.data.items[0].name }).click();
      await expect(page).toHaveURL(
        new RegExp(`/app/${locale}/product/\\?id=${products.data.items[0].id}&from=`),
      );

      await expect(page.getByRole('heading', { level: 1, name: p.data.card.name })).toBeVisible();
      await expect(page.getByRole('heading', { name: new RegExp(T.offers) })).toBeVisible();
      const source = page.getByRole('link', { name: new RegExp(T.source) });
      await expect(source).toHaveCount(1);
      await expect(source).toHaveAttribute('href', 'https://shop-a.example/p01');
      await expect(source).toHaveAttribute('rel', /noopener/);
      await expect(page.getByText(T.noSource)).toBeVisible();
      await expect(page.locator('a[href^="javascript"]')).toHaveCount(0);

      await expect(page.getByRole('heading', { name: T.pairs })).toBeVisible();
      await expect(page.getByRole('heading', { name: T.history })).toBeVisible();
      await expect(page.getByRole('img', { name: /Shop A/ })).toBeVisible();
      await page.getByText(T.table).click();
      await expect(page.getByRole('rowheader', { name: /2026/ })).toHaveCount(3);
      await noHorizontalScroll(page);

      const paths = mock.api.map((r) => new URL(r.url).pathname);
      expect(paths).toContain(`/api/v1/products/${products.data.items[0].id}`);
      expect(paths).toContain(`/api/v1/products/${products.data.items[0].id}/history`);

      await page.getByRole('link', { name: T.back }).click();
      await expect(page).toHaveURL(new RegExp(`/app/${locale}/explore/\\?brand=Fixture\\+Beauty$`));
      expect(mock.external).toEqual([]);
      expect(mock.errors).toEqual([]);
    });

    test('product page: an uncounted pair says why; unknown values show as sent', async ({ page }) => {
      const p = clone(product);
      p.data.pairs[0].gap = null;
      p.data.pairs[0].excludedReason = 'match_unreviewed';
      p.data.offers[0].availability = 'teleported';
      await mockBackend(page, { onApi: api({ product: p }) });
      await signedIn(page, locale);
      await page.goto(`/app/${locale}/product/?id=p01`);
      await expect(page.getByText(T.notCounted)).toBeVisible();
      await expect(page.getByText('teleported', { exact: true })).toHaveAttribute('dir', 'ltr');
      await expect(page.getByText('availability.teleported')).toHaveCount(0);
    });

    test('product page: unknown product and a malformed id', async ({ page }) => {
      const mock = await mockBackend(page, {
        onApi: (route) =>
          new URL(route.request().url()).pathname === '/api/v1/meta'
            ? route.fulfill({ json: meta })
            : route.fulfill({ status: 404, json: { error: { code: 'not_found', message: '<b>p999</b>' } } }),
      });
      await signedIn(page, locale);
      await page.goto(`/app/${locale}/product/?id=p999`);
      await expect(page.locator('main').getByRole('alert')).toBeVisible();
      await expect(page.locator('main')).not.toContainText('<b>');

      const before = mock.api.length;
      await page.goto(`/app/${locale}/product/?id=${encodeURIComponent('../admin')}`);
      await expect(page.getByRole('link', { name: T.back })).toBeVisible();
      await expect(page.getByRole('heading', { level: 1 })).toHaveCount(0);
      expect(mock.api.slice(before).some((r) => new URL(r.url).pathname.includes('admin'))).toBe(false);
    });
  });
}

test('S2: an unknown retailer status renders as sent, not as a key path', async ({ page }) => {
  const m = clone(meta);
  m.data.retailers[0].status = 'paused';
  // The Dataset page's table lists the retailers (the Overview no longer does); /summary gets its own fixture.
  await mockBackend(page, { onApi: withSummary((r) => r.fulfill({ json: m })) });
  await signIn(page, 'ar');
  await expect(page).not.toHaveURL(/\/sign-in\/?$/);
  await page.goto('/app/ar/dataset/');
  await expect(page.getByRole('cell', { name: 'paused', exact: true })).toBeVisible();
  await expect(page.getByText('status.paused')).toHaveCount(0);
});

test('language switch on a product keeps the product and the filters', async ({ page }) => {
  await mockBackend(page, { onApi: api() });
  await signedIn(page, 'en');
  await page.goto('/app/en/product/?id=p01&from=brand%3DFixture%2BBeauty');
  await expect(page.getByRole('heading', { level: 1, name: product.data.card.name })).toBeVisible();
  await page.getByRole('link', { name: 'Switch to Arabic' }).click();
  await expect(page).toHaveURL(/\/app\/ar\/product\/\?id=p01&from=brand%3DFixture%2BBeauty$/);
  await expect(page.locator('html')).toHaveAttribute('dir', 'rtl');
  await expect(page.getByRole('heading', { level: 1, name: product.data.card.name })).toBeVisible();
});

test('keyboard: the product list is reachable and opens a product with Enter', async ({ page }) => {
  await mockBackend(page, { onApi: api() });
  await signedIn(page, 'en');
  await page.goto('/app/en/explore/');
  const link = page.getByRole('link', { name: products.data.items[0].name });
  await expect(link).toBeVisible();
  await link.focus();
  await expect(link).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(page).toHaveURL(/\/app\/en\/product\/\?id=/);
});
