import {
  allPagesNav,
  EMAIL,
  expect,
  golden,
  mainNav,
  mockBackend,
  noHorizontalScroll,
  openMenu,
  servingMeta,
  signIn,
  signOut,
  test,
  withSummary,
} from './fixtures';
import { summaryNoPromo } from './summary-fixture';
import type { Page } from '@playwright/test';

// From an API that serves every page, so the full nav (Insights included) is listed.
const meta = servingMeta(golden('meta') as { data: { dates: string[] } });
const ok = { onApi: withSummary((r) => r.fulfill({ json: meta })) };
// One collection day: not enough for Launches.
const oneDay = { ...meta, data: { ...meta.data, dates: meta.data.dates.slice(0, 1) } };

/** Wide screens carry the sidebar; phones the tab bar and the menu. */
const wide = (page: Page) => (page.viewportSize()?.width ?? 0) >= 1024;

/** The full list of pages: the sidebar, or the phone menu once opened. */
async function allPages(page: Page) {
  if (wide(page)) return mainNav(page);
  await openMenu(page);
  return allPagesNav(page);
}

const linkTexts = async (nav: ReturnType<typeof mainNav>) =>
  (await nav.getByRole('link').allTextContents()).map((t) => t.trim());

for (const locale of ['en', 'ar'] as const) {
  const rtl = locale === 'ar';
  const T = rtl
    ? {
        title: 'نظرة عامة',
        signIn: 'تسجيل الدخول',
        signOut: 'تسجيل الخروج',
        bad: 'البريد الإلكتروني أو كلمة المرور غير صحيحة.',
        noRole: 'لا توجد صلاحية بعد',
        generic: 'حدث خطأ من جهتنا. حاول مجددًا.',
        authDown: 'تعذّر تأكيد صلاحيتك الآن',
        pages: [
          'نظرة عامة',
          'لوحة المتابعة',
          'المنتجات',
          'المقارنة',
          'الرؤى',
          'العروض',
          'الجديد',
          'الأسعار',
          'البيانات',
          'مساعد ريزان',
        ],
        tabs: ['نظرة عامة', 'المنتجات', 'المقارنة', 'العروض', 'ريزان'],
        launches: 'الجديد',
        promotions: 'العروض',
        soon: 'قريبًا',
        asOf: 'البيانات حتى ',
        aboutData: 'عن البيانات',
      }
    : {
        title: 'Overview',
        signIn: 'Sign in',
        signOut: 'Sign out',
        bad: 'Email or password is incorrect.',
        noRole: 'No access yet',
        generic: 'Something failed on our side. Try again.',
        authDown: "Couldn't confirm your access just now",
        pages: [
          'Overview',
          'Dashboard',
          'Products',
          'Compare',
          'Insights',
          'Promotions',
          'Launches',
          'Prices',
          'Dataset',
          'Ryzan AI',
        ],
        tabs: ['Overview', 'Products', 'Compare', 'Promotions', 'Ryzan'],
        launches: 'Launches',
        promotions: 'Promotions',
        soon: 'soon',
        asOf: 'Data as of ',
        aboutData: 'About the data',
      };

  test.describe(locale, () => {
    test('signed out: home sends you to sign-in', async ({ page }) => {
      const mock = await mockBackend(page, ok);
      await page.goto(`/app/${locale}/`);
      await expect(page).toHaveURL(new RegExp(`/app/${locale}/sign-in/$`));
      await expect(page.locator('html')).toHaveAttribute('dir', rtl ? 'rtl' : 'ltr');
      await expect(page.locator('html')).toHaveAttribute('lang', locale);
      await expect(page.getByRole('heading', { name: T.signIn })).toBeVisible();
      await noHorizontalScroll(page);
      expect(mock.api).toHaveLength(0);
      expect(mock.external).toEqual([]);
      expect(mock.errors).toEqual([]);
    });

    test('sign in, read the dataset with a Bearer token, sign out', async ({ page, context }) => {
      const mock = await mockBackend(page, ok);
      await signIn(page, locale);
      await expect(page).toHaveURL(new RegExp(`/app/${locale}/$`));
      // The Overview's own heading: the page is in (the dataset block now lives on /dataset/ only).
      await expect(page.getByRole('heading', { name: T.title, level: 1 })).toBeVisible();
      // The Overview's band, from /summary: the shop's tile with its product count.
      await expect(page.locator('#kpi-band [data-tile="shop:sephora_ae"]')).toContainText('4,812');
      await noHorizontalScroll(page);

      expect(mock.api.length).toBeGreaterThan(0);
      for (const r of mock.api) {
        expect(r.headers.authorization).toMatch(/^Bearer [\w-]+\.[\w-]+\.[\w-]+$/);
        expect(r.headers.cookie).toBeUndefined();
      }
      expect(await context.cookies()).toEqual([]);

      await signOut(page);
      await expect(page).toHaveURL(new RegExp(`/app/${locale}/sign-in/$`));
      expect(mock.external).toEqual([]);
      expect(mock.errors).toEqual([]);
    });

    test('navigation: every page in order, the sidebar at the start edge or the tab bar below', async ({
      page,
    }) => {
      const mock = await mockBackend(page, ok);
      await signIn(page, locale);
      await expect(page.getByRole('heading', { name: T.title, level: 1 })).toBeVisible();
      const nav = mainNav(page);
      await expect(nav).toBeVisible();
      await expect(nav.getByRole('link', { name: T.pages[0], exact: true })).toHaveAttribute(
        'aria-current',
        'page',
      );
      if (wide(page)) {
        expect(await linkTexts(nav)).toEqual(T.pages);
        // The sidebar sits before the content in reading order: left in English, right in Arabic.
        const aside = (await page.locator('aside').boundingBox())!;
        const main = (await page.locator('main').boundingBox())!;
        expect(aside.width).toBe(216);
        if (rtl) expect(aside.x).toBeGreaterThan(main.x + main.width - 1);
        else expect(aside.x + aside.width).toBeLessThanOrEqual(main.x + 1);
        expect(await page.getByRole('button', { name: /^(Menu|القائمة)$/ }).count()).toBe(0);
      } else {
        expect(await linkTexts(nav)).toEqual(T.tabs);
        await openMenu(page);
        expect(await linkTexts(allPagesNav(page))).toEqual(T.pages);
        await page.keyboard.press('Escape');
        await expect(allPagesNav(page)).toBeHidden();
      }
      await noHorizontalScroll(page);
      expect(mock.errors).toEqual([]);
    });

    test('page top bar: the dataset cutoff; the link to the data in the footer', async ({ page }) => {
      await mockBackend(page, ok);
      await signIn(page, locale);
      const main = page.locator('main');
      await expect(main.getByText(new RegExp(`^${T.asOf}.*2026`))).toBeVisible();
      await expect(page.locator('footer').getByRole('link', { name: T.aboutData })).toHaveAttribute(
        'href',
        new RegExp(`/app/${locale}/dataset/#about-data$`),
      );
    });

    test('Launches says "soon" until the dataset has two collection days', async ({ page }) => {
      await mockBackend(page, { onApi: withSummary((r) => r.fulfill({ json: oneDay })) });
      await signIn(page, locale);
      await expect(page.getByRole('heading', { name: T.title, level: 1 })).toBeVisible();
      const nav = await allPages(page);
      await expect(nav.getByRole('link', { name: T.launches })).toContainText(T.soon);
    });

    test('Promotions leaves the navigation when no retailer measures discounts', async ({ page }) => {
      await mockBackend(page, { onApi: withSummary((r) => r.fulfill({ json: meta }), summaryNoPromo) });
      await signIn(page, locale);
      await expect(page.getByRole('heading', { name: T.title, level: 1 })).toBeVisible();
      const nav = await allPages(page);
      await expect(nav.getByRole('link', { name: T.pages[1], exact: true })).toBeVisible();
      await expect(nav.getByRole('link', { name: T.promotions, exact: true })).toHaveCount(0);
    });

    test('wrong password: one message that names neither field', async ({ page }) => {
      await mockBackend(page, ok);
      await signIn(page, locale, 'wrong');
      await expect(page.locator('main').getByRole('alert')).toHaveText(T.bad);
    });

    test('signed in without a role: says so', async ({ page }) => {
      const mock = await mockBackend(page, { role: null, ...ok });
      await signIn(page, locale);
      await expect(page.getByRole('heading', { name: T.noRole })).toBeVisible();
      expect(mock.api).toHaveLength(0);
    });

    test('503 auth_unavailable: waits, retries, stays signed in', async ({ page }) => {
      let n = 0;
      const mock = await mockBackend(page, {
        // Counts /meta only: the landing also asks /compare and /category-compare once signed in.
        onApi: withSummary((r) =>
          new URL(r.request().url()).pathname === '/api/v1/meta' && ++n <= 1
            ? r.fulfill({
                status: 503,
                headers: { 'Retry-After': '1' },
                json: { error: { code: 'auth_unavailable', message: 'x' } },
              })
            : r.fulfill({ json: meta }),
        ),
      });
      await signIn(page, locale);
      await expect(page.getByRole('heading', { name: T.title, level: 1 })).toBeVisible();
      // The Overview's heading draws before /meta answers; the retry lands a second later.
      await expect.poll(() => n).toBe(2);
      await expect(mainNav(page)).toBeVisible();
      expect(mock.errors.filter((e) => !e.includes('503'))).toEqual([]);
    });

    test('503 auth_unavailable that persists: explains, keeps the session', async ({ page }) => {
      await mockBackend(page, {
        onApi: (r) =>
          r.fulfill({
            status: 503,
            headers: { 'Retry-After': '1' },
            json: { error: { code: 'auth_unavailable', message: 'x' } },
          }),
      });
      await signIn(page, locale);
      await expect(page.locator('main').getByRole('alert')).toContainText(T.authDown, { timeout: 15_000 });
      await expect(mainNav(page)).toBeVisible();
      await expect(page).toHaveURL(new RegExp(`/app/${locale}/$`));
    });

    test('500: generic text, nothing from the server echoed', async ({ page }) => {
      await mockBackend(page, {
        onApi: (r) =>
          r.fulfill({
            status: 500,
            json: { error: { code: 'internal_error', message: 'Traceback <script>q=leak</script>' } },
          }),
      });
      await signIn(page, locale);
      await expect(page.locator('main').getByRole('alert')).toContainText(T.generic);
      await expect(page.locator('body')).not.toContainText('leak');
    });
  });
}

test('language switch keeps the page and remembers the choice', async ({ page }) => {
  await mockBackend(page, ok);
  await page.goto('/app/en/sign-in/');
  await page.getByRole('link', { name: 'Switch to Arabic' }).click();
  await expect(page).toHaveURL(/\/app\/ar\/sign-in\/$/);
  await expect(page.locator('html')).toHaveAttribute('dir', 'rtl');
  await page.goto('/app/');
  await expect(page).toHaveURL(/\/app\/ar\/sign-in\/$/);
});

test('keyboard: skip link then the sign-in fields in order', async ({ page }) => {
  await mockBackend(page, ok);
  await page.goto('/app/en/sign-in/');
  await page.keyboard.press('Tab');
  await expect(page.getByRole('link', { name: 'Skip to content' })).toBeFocused();
  for (let i = 0; i < 3; i++) await page.keyboard.press('Tab'); // app name, language, then the form
  await expect(page.locator('input[name=email]')).toBeFocused();
  await page.keyboard.type(EMAIL);
  await page.keyboard.press('Tab');
  await expect(page.locator('input[name=password]')).toBeFocused();
});
