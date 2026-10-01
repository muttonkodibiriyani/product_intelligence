import type { Route } from '@playwright/test';
import { readFile } from 'node:fs/promises';
import { expect, golden, mockBackend, noHorizontalScroll, signIn, test, type Mock } from './fixtures';

type Json = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any

const meta = golden('meta') as Json;
const products = golden('products') as Json;
const gapPage = golden('products-gap') as Json;
const NAME = 'pi-products-20260930T0000Z.csv';
// A real export starts with a BOM and a one-cell manifest line; the client must keep it all.
const CSV = '﻿"# {""view"":""products"",""rows"":2}"\nid,name\np05,Product p05\np01,Product p01\n';

type Answer = (route: Route) => Promise<void> | void;

/** Explorer reads from the golden pages; the export answers whatever the test says. */
function api(exportAnswer: Answer, list: Json = products): (route: Route) => Promise<void> {
  return async (route) => {
    const p = new URL(route.request().url()).pathname;
    if (p === '/api/v1/meta') return route.fulfill({ json: meta });
    if (p === '/api/v1/products') return route.fulfill({ json: list });
    if (p === '/api/v1/export/products') return exportAnswer(route);
    return route.fulfill({ status: 404, json: { error: { code: 'not_found', message: 'no route' } } });
  };
}

const file: Answer = (route) =>
  route.fulfill({
    status: 200,
    body: CSV,
    headers: {
      'Content-Type': 'text/csv; charset=utf-8',
      'Content-Disposition': `attachment; filename="${NAME}"`,
    },
  });

const exportCalls = (mock: Mock) =>
  mock.api.filter((r) => new URL(r.url).pathname === '/api/v1/export/products');

async function openExplorer(page: import('@playwright/test').Page, locale: 'en' | 'ar', search = '') {
  await signIn(page, locale);
  await expect(page.getByRole('navigation')).toBeVisible();
  await page.goto(`/app/${locale}/explore/${search}`);
  await expect(page.getByRole('table')).toBeVisible();
}

for (const locale of ['en', 'ar'] as const) {
  const T =
    locale === 'ar'
      ? { csv: /بصيغة CSV$/, saved: `حُفظ الملف ${NAME}.` }
      : { csv: /as CSV$/, saved: `Saved ${NAME}.` };

  test(`${locale}: exports the filtered list as CSV with the Bearer token, byte for byte`, async ({
    page,
  }) => {
    const mock = await mockBackend(page, { onApi: api(file, gapPage) });
    await openExplorer(page, locale, '?brand=Fixture+Beauty&retailer=shop_b&retailer=shop_a&sort=gap');
    const csv = page.getByRole('button', { name: T.csv });
    await expect(csv).toBeEnabled();
    const [download] = await Promise.all([page.waitForEvent('download'), csv.click()]);
    expect(download.suggestedFilename()).toBe(NAME);
    expect(await readFile((await download.path())!, 'utf8')).toBe(CSV);
    await expect(page.getByRole('status').filter({ hasText: T.saved })).toBeVisible();
    await noHorizontalScroll(page);

    const [call] = exportCalls(mock);
    const u = new URL(call!.url);
    expect(u.searchParams.get('format')).toBe('csv');
    expect(u.searchParams.getAll('brand')).toEqual(['Fixture Beauty']);
    expect(u.searchParams.getAll('retailer')).toEqual(['shop_b', 'shop_a']);
    expect(u.searchParams.get('sort')).toBe('gap');
    expect(u.searchParams.has('limit')).toBe(false);
    expect(u.searchParams.has('cursor')).toBe(false);
    expect(call!.headers.authorization).toMatch(/^Bearer /);
    expect(call!.headers.cookie).toBeUndefined();
    expect(call!.headers.accept).toMatch(/^text\/csv/);
    expect(mock.external).toEqual([]);
    expect(mock.errors).toEqual([]);
  });
}

test('JSONL asks for JSONL', async ({ page }) => {
  const mock = await mockBackend(page, {
    onApi: api((r) =>
      r.fulfill({
        status: 200,
        body: '{"manifest":{}}\n',
        headers: { 'Content-Type': 'application/x-ndjson' },
      }),
    ),
  });
  await openExplorer(page, 'en');
  const [download] = await Promise.all([
    page.waitForEvent('download'),
    page.getByRole('button', { name: /as JSONL$/ }).click(),
  ]);
  // No usable Content-Disposition: the fallback name, still with the right extension.
  expect(download.suggestedFilename()).toBe('pi-products.jsonl');
  expect(new URL(exportCalls(mock)[0]!.url).searchParams.get('format')).toBe('jsonl');
});

test('429 rate_limited: says two exports are running, waits Retry-After, then offers it again', async ({
  page,
}) => {
  let n = 0;
  await mockBackend(page, {
    onApi: api((r) =>
      n++ === 0
        ? r.fulfill({
            status: 429,
            headers: { 'Retry-After': '2' },
            json: { error: { code: 'rate_limited', message: 'too many exports running; retry later' } },
          })
        : file(r),
    ),
  });
  await openExplorer(page, 'en');
  const csv = page.getByRole('button', { name: /as CSV$/ });
  await csv.click();
  await expect(page.getByText(/^Two exports are already running\. Try again in [12] s\.$/)).toBeVisible();
  await expect(csv).toBeDisabled();
  await expect(csv).toBeEnabled({ timeout: 5000 });
  const [download] = await Promise.all([page.waitForEvent('download'), csv.click()]);
  expect(download.suggestedFilename()).toBe(NAME);
});

test('422 export_too_large: says to narrow the filters; nothing from the server is shown', async ({
  page,
}) => {
  await mockBackend(page, {
    onApi: api((r) =>
      r.fulfill({ status: 422, json: { error: { code: 'export_too_large', message: '<b>60001 rows</b>' } } }),
    ),
  });
  await openExplorer(page, 'en');
  await page.getByRole('button', { name: /as CSV$/ }).click();
  await expect(page.getByText(/^Too many rows to export/)).toBeVisible();
  await expect(page.getByText('60001')).toHaveCount(0);
});

test('a 200 that is not the asked-for type (index.html from a mis-routed /api) is not saved', async ({
  page,
}) => {
  const mock = await mockBackend(page, {
    onApi: api((r) =>
      r.fulfill({ status: 200, contentType: 'text/html', body: '<!doctype html><title>PI</title>' }),
    ),
  });
  let downloads = 0;
  page.on('download', () => downloads++);
  await openExplorer(page, 'en');
  await page.getByRole('button', { name: /as CSV$/ }).click();
  await expect(page.getByText("The server sent a response this app can't read.")).toBeVisible();
  expect(exportCalls(mock)).toHaveLength(1);
  expect(downloads).toBe(0);
});

test('over the cap before asking: export is off and says why', async ({ page }) => {
  const big = structuredClone(products);
  big.data.total = 60_000;
  const mock = await mockBackend(page, { onApi: api(file, big) });
  await openExplorer(page, 'en');
  await expect(page.getByRole('button', { name: /as CSV$/ })).toBeDisabled();
  await expect(page.getByText('Exports stop at 50,000 rows. Narrow the filters to export.')).toBeVisible();
  expect(exportCalls(mock)).toEqual([]);
});
