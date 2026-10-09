import type { Page, Route } from '@playwright/test';
import { categoryCompareBody } from './category-compare-fixture';
import fixture from './findings-fixture.json';
import { expect, golden, mockBackend, servingMeta, signedIn, test } from './fixtures';

type Json = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any

/**
 * The goldens with shop_a and shop_b renamed to the pilot pair, so the pages pick Ulta and Sephora
 * as they do on the served data. The cutoff is 22:07Z on 29 Sep, which is 30 Sep in Dubai.
 */
const asPilot = (body: unknown): Json =>
  JSON.parse(
    JSON.stringify(body)
      .replaceAll('shop_a', 'ulta_ae')
      .replaceAll('shop_b', 'sephora_me')
      .replaceAll('Shop A', 'Ulta')
      .replaceAll('Shop B', 'Sephora'),
  );

const NOTE = {
  en: 'ulta.ae blocks our collection since 2026-09-29; prices last collected 2026-09-28',
  ar: 'يحجب ulta.ae التجميع منذ 2026-09-29؛ آخر تجميع للأسعار 2026-09-28',
};

const meta = servingMeta(asPilot(golden('meta')));
meta.data.cutoff = '2026-09-29T22:07:33Z';

/** /coverage with Ulta last seen on `ulta`; Sephora is always current (its day equals the cutoff's). */
function coverage(ulta: string): Json {
  const c = asPilot(golden('coverage'));
  for (const r of c.data.retailers) {
    if (r.id === 'ulta_ae') Object.assign(r, { freshness: ulta, note: ulta < '2026-09-30' ? NOTE : null });
    if (r.id === 'sephora_me') r.freshness = '2026-09-30';
  }
  return c;
}

function api(cov: Json) {
  const bodies: Record<string, Json> = {
    '/api/v1/meta': meta,
    '/api/v1/coverage': cov,
    '/api/v1/findings': asPilot(fixture),
    '/api/v1/insights': asPilot(golden('insights')),
    '/api/v1/assortment-gaps': asPilot(golden('assortment-gaps')),
    '/api/v1/promotions': asPilot(golden('promotions')),
    '/api/v1/category-compare': categoryCompareBody('ulta_ae', 'sephora_me'),
  };
  return async (route: Route) => {
    const u = new URL(route.request().url());
    if (u.pathname === '/api/v1/compare')
      return route.fulfill({
        json: asPilot(golden(u.searchParams.get('rows') === 'overlap' ? 'compare-overlap' : 'compare')),
      });
    const json = bodies[u.pathname];
    if (json) return route.fulfill({ json });
    return route.fulfill({ status: 404, json: { error: { code: 'not_found', message: 'no route' } } });
  };
}

const PAGES = [
  ['insights', 'insights/'],
  ['compare', 'compare/?retailers=ulta_ae%2Csephora_me'],
  ['overlap', 'compare/overlap/?retailers=ulta_ae%2Csephora_me'],
] as const;

/**
 * Opens a page and returns once /coverage has answered and the page has painted twice since, so a
 * missing notice is a decision the page made, not one it has yet to make.
 */
async function open(page: Page, url: string) {
  const covered = page.waitForResponse((r) => new URL(r.url()).pathname === '/api/v1/coverage');
  await page.goto(url);
  await covered;
  await expect(page.locator('main h1')).toBeVisible();
  await page.evaluate(() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))));
}

for (const locale of ['en', 'ar'] as const) {
  for (const [name, path] of PAGES) {
    test(`${locale} ${name}: Ulta, last seen before the cutoff day, is named with its date and note`, async ({
      page,
    }, info) => {
      const mock = await mockBackend(page, { onApi: api(coverage('2026-09-28')) });
      await signedIn(page, locale);
      await open(page, `/app/${locale}/${path}`);
      const notice = page.getByTestId('dated-shop-notice');
      await expect(notice).toBeVisible();
      await expect(notice.locator('p')).toHaveCount(1);
      await expect(notice).toContainText(locale === 'en' ? 'Ulta prices as of' : 'أسعار Ulta حتى');
      await expect(notice).toContainText(NOTE[locale]);
      await expect(notice).toContainText('2026');
      // Sephora is current: it gets no line.
      await expect(notice).not.toContainText('Sephora');
      await info.attach(`notice-ulta-${name}-${locale}`, {
        body: await page.screenshot({ fullPage: true }),
        contentType: 'image/png',
      });
      expect(mock.errors).toEqual([]);
    });

    test(`${locale} ${name}: control, both shops current on the cutoff day, shows no notice`, async ({
      page,
    }, info) => {
      const mock = await mockBackend(page, { onApi: api(coverage('2026-09-30')) });
      await signedIn(page, locale);
      await open(page, `/app/${locale}/${path}`);
      await expect(page.getByTestId('dated-shop-notice')).toHaveCount(0);
      await info.attach(`notice-control-${name}-${locale}`, {
        body: await page.screenshot({ fullPage: true }),
        contentType: 'image/png',
      });
      expect(mock.errors).toEqual([]);
    });
  }
}
