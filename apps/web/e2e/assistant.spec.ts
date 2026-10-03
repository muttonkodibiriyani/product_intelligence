import { expect, golden, mockBackend, noHorizontalScroll, signIn, test, withSummary } from './fixtures';

// The Ryzan AI page as it ships (flags off): the greeting, three starters, the thread area and
// the composer with its one-line off-state. No question is ever sent, so no callable is mocked.
const meta = golden('meta');
const api = withSummary((r) => r.fulfill({ json: meta }));

for (const locale of ['en', 'ar'] as const) {
  const T =
    locale === 'ar'
      ? {
          title: 'مساعد ريزان الذكي',
          hello: 'ماذا تريد أن تعرف عن Ulta وSephora اليوم؟',
          starters: 'أسئلة للبدء',
          starter: 'أرخص كريمات أساس لكل مل',
          question: 'سؤالك',
          send: 'إرسال',
          off: 'مساعد ريزان غير مفعّل بعد. يفعّله المالك، مع حد للإنفاق، قبل إنشاء أي إجابات.',
          dir: 'rtl',
        }
      : {
          title: 'Ryzan AI Assistant',
          hello: 'What do you want to know about Ulta and Sephora today?',
          starters: 'Starter questions',
          starter: 'Cheapest foundations per ml',
          question: 'Your question',
          send: 'Send',
          off: 'Ryzan AI isn’t switched on yet. The owner enables it, with a spending cap, before answers are generated.',
          dir: 'ltr',
        };

  test(`assistant page ${locale}: greeting, three starters, composer off in one line`, async ({ page }) => {
    const mock = await mockBackend(page, { onApi: api });
    await signIn(page, locale);
    await expect(page.getByRole('navigation')).toBeVisible();
    await page.goto(`/app/${locale}/assistant/`);
    await expect(page.locator('html')).toHaveAttribute('dir', T.dir);
    await expect(page.getByRole('heading', { level: 1 })).toHaveText(T.title);
    await expect(page.getByRole('heading', { level: 2, name: T.hello })).toBeVisible();

    const starters = page.getByRole('list', { name: T.starters });
    await expect(starters.getByRole('button')).toHaveCount(3);

    // The off-state: one line under the input, the composer's only note; no panel, no samples.
    const off = page.getByText(T.off);
    await expect(off).toHaveCount(1);
    await expect(off).toBeVisible();
    await expect(page.getByRole('status')).toHaveCount(0);
    await expect(page.getByText(/Connect to enable|not live data|يلزم الربط|ليست بيانات حية/)).toHaveCount(0);

    // A starter fills the question; Send stays off and nothing is sent.
    await starters.getByRole('button', { name: T.starter }).click();
    const input = page.getByRole('textbox', { name: T.question });
    await expect(input).toHaveValue(T.starter);
    const send = page.getByRole('button', { name: T.send });
    await expect(send).toBeDisabled();
    await input.press('Enter');
    await expect(input).toHaveValue(T.starter);

    // The composer stays in view at the bottom.
    const box = await send.boundingBox();
    const viewport = page.viewportSize()!;
    expect(box).not.toBeNull();
    expect(box!.y + box!.height).toBeLessThanOrEqual(viewport.height);

    await noHorizontalScroll(page);
    // This page asks the API for nothing of its own; the shell's /meta and /summary (nav rules) are
    // allowed, and Overview, where sign-in lands, may still be loading its own data.
    const fromHere = mock.api.filter((r) => /\/assistant\/$/.test(r.headers.referer ?? ''));
    expect(fromHere.filter((r) => !/\/api\/v1\/(meta|summary)(\?|$)/.test(r.url))).toEqual([]);
    expect(mock.external).toEqual([]);
    expect(mock.errors).toEqual([]);
  });
}
