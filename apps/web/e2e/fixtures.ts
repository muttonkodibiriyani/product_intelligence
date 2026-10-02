import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { summaryBody } from './summary-fixture';
import { test as base, expect, type Locator, type Page, type Route } from '@playwright/test';

export const golden = (name: string): unknown =>
  JSON.parse(readFileSync(join(__dirname, '../../../docs/contracts/golden/pi-api', `${name}.json`), 'utf8'));

const b64 = (o: object) => Buffer.from(JSON.stringify(o)).toString('base64url');

/** An unsigned ID token: the client only decodes it; the (mocked) API is what would verify it. */
export function idToken(claims: Record<string, unknown>): string {
  const now = Math.floor(Date.now() / 1000);
  const payload = {
    iss: 'https://securetoken.google.com/demo-pi',
    aud: 'demo-pi',
    auth_time: now,
    user_id: 'u1',
    sub: 'u1',
    iat: now,
    exp: now + 3600,
    email: 'analyst@example.com',
    firebase: { identities: {}, sign_in_provider: 'password' },
    ...claims,
  };
  return `${b64({ alg: 'RS256', typ: 'JWT' })}.${b64(payload)}.c2ln`;
}

export interface Mock {
  /** Every /api/v1 request seen, with its headers. */
  api: { url: string; headers: Record<string, string> }[];
  /** Requests that tried to leave localhost and were blocked. */
  external: string[];
  errors: string[];
}

export const EMAIL = 'analyst@example.com';
export const PASSWORD = 'correct horse';

/**
 * A browser with no network beyond the local server: Firebase config and Identity Toolkit are
 * mocked, and each test answers /api/v1 itself through `onApi`.
 */
export async function mockBackend(
  page: Page,
  opts: { role?: string | null; onApi: (route: Route) => Promise<void> | void },
): Promise<Mock> {
  const mock: Mock = { api: [], external: [], errors: [] };
  page.on('pageerror', (e) => {
    if (!/due to access control checks/.test(String(e))) mock.errors.push(String(e));
  });
  // The local server sends the production CSP; any block it makes fails the test.
  await page.addInitScript(() =>
    document.addEventListener('securitypolicyviolation', (e) =>
      console.error(`CSP blocked ${e.violatedDirective}: ${e.blockedURI || 'inline'}`),
    ),
  );
  page.on('console', (m) => {
    if (m.type() !== 'error') return;
    const text = m.text();
    // WebKit logs these for requests the app itself cancelled (a superseded query, a prefetch
    // dropped on navigation) and for every non-2xx answer the test chose to send. External
    // requests are caught by `external`, and statuses are asserted by each test.
    if (
      /due to access control checks|^Failed to load resource: the server responded with a status of/.test(
        text,
      )
    )
      return;
    mock.errors.push(text);
  });

  await page.route(/^https?:\/\/(?!127\.0\.0\.1[:/])/, async (route) => {
    const url = route.request().url();
    if (url.includes('/v1/accounts:signInWithPassword')) {
      const body = route.request().postDataJSON() as { email: string; password: string };
      if (body.password !== PASSWORD)
        return route.fulfill({
          status: 400,
          json: { error: { code: 400, message: 'INVALID_LOGIN_CREDENTIALS' } },
        });
      const claims = opts.role === null ? {} : { role: opts.role ?? 'viewer' };
      return route.fulfill({
        json: {
          kind: 'identitytoolkit#VerifyPasswordResponse',
          localId: 'u1',
          email: EMAIL,
          idToken: idToken(claims),
          refreshToken: 'r1',
          expiresIn: '3600',
          registered: true,
        },
      });
    }
    if (url.includes('/v1/accounts:lookup'))
      return route.fulfill({
        json: {
          users: [
            {
              localId: 'u1',
              email: EMAIL,
              emailVerified: true,
              providerUserInfo: [{ providerId: 'password', email: EMAIL, federatedId: EMAIL, rawId: EMAIL }],
              lastLoginAt: '1',
              createdAt: '1',
            },
          ],
        },
      });
    if (url.includes('/v1/accounts:sendOobCode')) return route.fulfill({ json: { email: EMAIL } });
    mock.external.push(url);
    return route.abort();
  });

  await page.route('**/__/firebase/init.json', (route) =>
    route.fulfill({
      json: {
        apiKey: 'demo-key',
        authDomain: 'demo-pi.firebaseapp.com',
        projectId: 'demo-pi',
        appId: '1:1:web:1',
      },
    }),
  );
  await page.route('**/api/v1/**', async (route) => {
    mock.api.push({ url: route.request().url(), headers: await route.request().allHeaders() });
    await opts.onApi(route);
  });
  return mock;
}

export async function signIn(page: Page, locale: 'en' | 'ar', password = PASSWORD) {
  await page.goto(`/app/${locale}/sign-in/`);
  await page.locator('input[name=email]').fill(EMAIL);
  await page.locator('input[name=password]').fill(password);
  await page.locator('button[type=submit]').click();
}

/** The main navigation: the sidebar on wide screens, the bottom tab bar on phones. */
export const mainNav = (page: Page) => page.getByRole('navigation', { name: /^(Main|الرئيسية)$/ });

/** The phone menu's navigation, listing every page; opened by `openMenu`. */
export const allPagesNav = (page: Page) => page.getByRole('navigation', { name: /^(All pages|كل الصفحات)$/ });

export async function openMenu(page: Page) {
  await page.getByRole('button', { name: /^(Menu|القائمة)$/ }).click();
  await expect(allPagesNav(page)).toBeVisible();
}

/**
 * A nav link by name, wherever it lives: in the sidebar or tab bar when it is there, otherwise
 * (a page off the phone's five tabs) in the phone menu, which this opens.
 */
export async function navLink(page: Page, name: string | RegExp): Promise<Locator> {
  const nav = mainNav(page);
  await expect(nav).toBeVisible();
  const direct = nav.getByRole('link', { name });
  if ((await direct.count()) > 0) return direct;
  await openMenu(page);
  return allPagesNav(page).getByRole('link', { name });
}

/** Follows a nav link by name (see `navLink`). */
export async function openNav(page: Page, name: string | RegExp) {
  await (await navLink(page, name)).click();
}

/** Signs out from the sidebar foot, or from the phone menu where the foot lives on small screens. */
export async function signOut(page: Page) {
  const button = page.getByRole('button', { name: /^(Sign out|تسجيل الخروج)$/ });
  if ((await button.count()) === 0) await openMenu(page);
  await button.click();
}

export async function noHorizontalScroll(page: Page) {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);
}

/** Answers /summary with the landing fixture and everything else with `onApi`. */
export function withSummary(onApi: (r: Route) => Promise<void> | void, body: unknown = summaryBody) {
  return (r: Route) =>
    new URL(r.request().url()).pathname === '/api/v1/summary' ? r.fulfill({ json: body }) : onApi(r);
}

export const test = base;
export { expect };
