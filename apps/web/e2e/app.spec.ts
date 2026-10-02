import {
  EMAIL,
  expect,
  golden,
  mockBackend,
  noHorizontalScroll,
  signIn,
  test,
  withSummary,
} from './fixtures';

const meta = golden('meta');
const ok = { onApi: withSummary((r) => r.fulfill({ json: meta })) };

for (const locale of ['en', 'ar'] as const) {
  const rtl = locale === 'ar';
  const T = rtl
    ? {
        title: 'مجموعة البيانات الحالية',
        retailers: 'المتاجر',
        signIn: 'تسجيل الدخول',
        signOut: 'تسجيل الخروج',
        bad: 'البريد الإلكتروني أو كلمة المرور غير صحيحة.',
        noRole: 'لا توجد صلاحية بعد',
        generic: 'حدث خطأ من جهتنا. حاول مجددًا.',
        authDown: 'تعذّر تأكيد صلاحيتك الآن',
      }
    : {
        title: 'Current dataset',
        retailers: 'Retailers',
        signIn: 'Sign in',
        signOut: 'Sign out',
        bad: 'Email or password is incorrect.',
        noRole: 'No access yet',
        generic: 'Something failed on our side. Try again.',
        authDown: "Couldn't confirm your access just now",
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
      await expect(page.getByRole('heading', { name: T.title })).toBeVisible();
      await expect(page.getByRole('heading', { name: T.retailers })).toBeVisible();
      await expect(page.getByRole('rowheader', { name: 'Shop C' })).toBeVisible();
      await noHorizontalScroll(page);

      expect(mock.api.length).toBeGreaterThan(0);
      for (const r of mock.api) {
        expect(r.headers.authorization).toMatch(/^Bearer [\w-]+\.[\w-]+\.[\w-]+$/);
        expect(r.headers.cookie).toBeUndefined();
      }
      expect(await context.cookies()).toEqual([]);

      await page.getByRole('button', { name: T.signOut }).click();
      await expect(page).toHaveURL(new RegExp(`/app/${locale}/sign-in/$`));
      expect(mock.external).toEqual([]);
      expect(mock.errors).toEqual([]);
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
        // Counts /meta only: the landing also asks /compare and /index once signed in.
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
      await expect(page.getByRole('heading', { name: T.title })).toBeVisible();
      expect(n).toBe(2);
      await expect(page.getByRole('button', { name: T.signOut })).toBeVisible();
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
      await expect(page.getByRole('button', { name: T.signOut })).toBeVisible();
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
