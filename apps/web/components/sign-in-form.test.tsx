import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { NextIntlClientProvider } from 'next-intl';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import ar from '@/messages/ar.json';
import en from '@/messages/en.json';
import { SignInForm } from './sign-in-form';

const ctx = vi.hoisted(() => ({ value: {} as { state: { kind: string }; auth: unknown } }));
vi.mock('./auth-provider', () => ({ useAuth: () => ctx.value }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ replace: vi.fn() }) }));

const ADDR = 'reader@example.com';
/** A Firebase-shaped rejection; the SDK's message can carry the address, the code never does. */
const fail = (code: string, status = 400) =>
  Object.assign(new Error(`Firebase: Error (${code}) HTTP ${status} for ${ADDR}`), { code });

let warn: ReturnType<typeof vi.spyOn>;
beforeEach(() => {
  warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
});
afterEach(() => {
  cleanup();
  warn.mockRestore();
});

function renderForm(sendReset: () => Promise<void>, locale: 'en' | 'ar' = 'en') {
  ctx.value = { state: { kind: 'signed_out' }, auth: { sendReset, signIn: vi.fn() } };
  render(
    <NextIntlClientProvider locale={locale} messages={locale === 'ar' ? ar : en}>
      <SignInForm />
    </NextIntlClientProvider>,
  );
  const m = locale === 'ar' ? ar : en;
  fireEvent.change(screen.getByLabelText(m.signIn.email), { target: { value: ADDR } });
  fireEvent.click(screen.getByRole('button', { name: m.signIn.forgot }));
}

const sent = (m: typeof en) => m.signIn.resetSent.replace('{email}', ADDR);

describe('password reset', () => {
  it('a sent link says so, with no warning', async () => {
    const sendReset = vi.fn(() => Promise.resolve());
    renderForm(sendReset);
    expect(await screen.findByRole('status')).toHaveProperty('textContent', sent(en));
    expect(sendReset).toHaveBeenCalledWith(ADDR);
    expect(screen.queryByRole('alert')).toBeNull();
    expect(warn).not.toHaveBeenCalled();
  });

  it('an unknown address reads exactly like a sent link, so no one learns who has an account', async () => {
    renderForm(() => Promise.reject(fail('auth/user-not-found')));
    expect(await screen.findByRole('status')).toHaveProperty('textContent', sent(en));
    expect(screen.queryByRole('alert')).toBeNull();
    expect(warn).not.toHaveBeenCalled();
  });

  it.each([
    ['too many requests', fail('auth/too-many-requests', 429)],
    ['quota', fail('auth/quota-exceeded', 429)],
    ['network', fail('auth/network-request-failed', 0)],
    ['a 403', fail('auth/unauthorized-domain', 403)],
  ])('%s: says it could not send, and logs the code only, never the address', async (_, err) => {
    renderForm(() => Promise.reject(err));
    expect(await screen.findByRole('alert')).toHaveProperty('textContent', en.signIn.errors.resetLater);
    expect(screen.queryByText(sent(en))).toBeNull();
    expect(warn).toHaveBeenCalledOnce();
    expect(warn.mock.calls[0]).toEqual(['password reset failed:', err.code]);
    expect(JSON.stringify(warn.mock.calls)).not.toContain(ADDR);
  });

  it('a malformed address asks for a valid one', async () => {
    renderForm(() => Promise.reject(fail('auth/invalid-email')));
    expect(await screen.findByRole('alert')).toHaveProperty('textContent', en.signIn.errors.invalidEmail);
    expect(warn).not.toHaveBeenCalled();
  });

  it('in Arabic: a failure and a sent link use the Arabic text', async () => {
    renderForm(() => Promise.reject(fail('auth/too-many-requests', 429)), 'ar');
    expect(await screen.findByRole('alert')).toHaveProperty('textContent', ar.signIn.errors.resetLater);
    cleanup();
    renderForm(() => Promise.reject(fail('auth/user-not-found')), 'ar');
    await waitFor(() => expect(screen.getByRole('status').textContent).toBe(sent(ar)));
  });
});
