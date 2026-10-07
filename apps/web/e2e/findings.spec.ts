import type { Route } from '@playwright/test';
import fixture from './findings-fixture.json';
import { expect, golden, mockBackend, noHorizontalScroll, servingMeta, signedIn, test } from './fixtures';

type Json = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any

const meta = servingMeta(golden('meta') as Json);

// The Insights cards' own data, so the page below the Findings settles as it does live.
async function api(route: Route) {
  const p = new URL(route.request().url()).pathname;
  const json = {
    '/api/v1/meta': meta,
    '/api/v1/findings': fixture,
    '/api/v1/insights': golden('insights'),
    '/api/v1/compare': golden('compare'),
    '/api/v1/assortment-gaps': golden('assortment-gaps'),
    '/api/v1/promotions': golden('promotions'),
  }[p];
  if (json) return route.fulfill({ json });
  return route.fulfill({ status: 404, json: { error: { code: 'not_found', message: 'no route' } } });
}

for (const locale of ['en', 'ar'] as const) {
  const T =
    locale === 'ar'
      ? {
          title: 'النتائج',
          glance: /لمحة سريعة/,
          themes: ['التشكيلة', 'السعر', 'العروض', 'المخزون', 'التقييمات', 'جودة البيانات'],
          why: 'لماذا نقول هذا',
        }
      : {
          title: 'Findings',
          glance: /At a glance/,
          themes: ['Assortment', 'Price', 'Promo', 'Stock', 'Reviews', 'Data quality'],
          why: 'Why we say this',
        };

  test.describe(`${locale} insights findings`, () => {
    test('twelve tiles lead to twelve cards grouped by theme, each keeping its rank', async ({ page }) => {
      const mock = await mockBackend(page, { onApi: api });
      await signedIn(page, locale);
      await page.goto(`/app/${locale}/insights/`);
      const findings = page.locator('section[aria-labelledby="findings-title"]');
      await expect(findings.getByRole('heading', { level: 2, name: T.title })).toBeVisible();
      const strip = findings.getByRole('navigation', { name: T.glance });
      await expect(strip.getByRole('link')).toHaveCount(12);
      await expect(findings.getByRole('heading', { level: 3 })).toHaveText(T.themes);
      await expect(findings.locator('article[data-finding]')).toHaveCount(12);
      // The pair asked for is the page's: the first two collected shops.
      const asked = mock.api.map((r) => new URL(r.url)).find((u) => u.pathname === '/api/v1/findings');
      expect(asked?.searchParams.get('focus')).toBe('shop_a');
      expect(asked?.searchParams.get('rival')).toBe('shop_b');

      // A tile jumps to its card; the card's "why" starts closed and opens on demand.
      await strip.getByRole('link').filter({ hasText: '#5' }).click();
      await expect(page).toHaveURL(/#finding-stock$/);
      const card = page.locator('#finding-stock');
      await expect(card).toBeInViewport();
      await expect(card.getByText(T.why)).toBeVisible();
      await expect(card.locator('details')).not.toHaveAttribute('open', '');
      await card.getByText(T.why).click();
      await expect(card.locator('details')).toHaveAttribute('open', '');
      await noHorizontalScroll(page);
      expect(mock.errors).toEqual([]);
      expect(mock.external).toEqual([]);
    });
  });
}
