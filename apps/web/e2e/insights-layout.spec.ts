import type { Page, Route } from '@playwright/test';
import fixture from './findings-fixture.json';
import { expect, golden, mockBackend, servingMeta, signIn, test } from './fixtures';

type Json = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any

const meta = servingMeta(golden('meta') as Json);

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

/** The page column's gap to its start and end edges: the sidebar on one side, the window on the other. */
async function gutters(page: Page) {
  return page.evaluate(() => {
    const main = document.querySelector('main')!;
    const box = main.getBoundingClientRect();
    const page = main.firstElementChild!.getBoundingClientRect();
    return { left: Math.round(page.left - box.left), right: Math.round(box.right - page.right) };
  });
}

/** Cards of a 12-column grid whose row has free columns left over. */
async function halfRows(page: Page) {
  return page.evaluate(() =>
    [...document.querySelectorAll('main .grid-cols-12')].flatMap((grid) => {
      const kids = [...grid.children].map((k) => k.getBoundingClientRect());
      const g = grid.getBoundingClientRect();
      const rows = new Map<number, number>();
      for (const k of kids) rows.set(Math.round(k.top), (rows.get(Math.round(k.top)) ?? 0) + k.width);
      // Gaps between cards are at most 20px each, so a full row is within a few gaps of the grid.
      return [...rows.values()].filter((w) => w < g.width - 3 * 20).map((w) => `${Math.round(w)}/${g.width}`);
    }),
  );
}

for (const locale of ['en', 'ar'] as const)
  for (const width of [1280, 1440, 1920])
    test(`${locale} ${width}: Insights gutters match Prices and every card row is full`, async ({
      page,
    }, info) => {
      test.skip(info.project.name.endsWith('-mobile'), 'desktop widths only');
      await page.setViewportSize({ width, height: 900 });
      const mock = await mockBackend(page, { onApi: api });
      await signIn(page, locale);
      await expect(page.getByRole('navigation').first()).toBeVisible();
      await page.goto(`/app/${locale}/prices/`);
      await expect(page.locator('main h1')).toBeVisible();
      const prices = await gutters(page);

      await page.goto(`/app/${locale}/insights/`);
      // The findings and the per-pair cards load after the page; under a busy runner that can exceed 5s.
      await expect(page.locator('article[data-finding]').first()).toBeVisible({ timeout: 15_000 });
      await expect(page.locator('[id^="finding-space-"]').first()).toBeVisible({ timeout: 15_000 });
      const insights = await gutters(page);
      expect(insights.left).toBe(insights.right);
      expect(insights).toEqual(prices);
      expect(await halfRows(page)).toEqual([]);
      await info.attach(`insights-${locale}-${width}`, {
        body: await page.screenshot({ fullPage: true }),
        contentType: 'image/png',
      });
      expect(mock.errors).toEqual([]);
    });
