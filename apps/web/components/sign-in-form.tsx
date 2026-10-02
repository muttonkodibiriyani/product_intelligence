'use client';

import { useRouter } from 'next/navigation';
import { useLocale, useTranslations } from 'next-intl';
import { useEffect, useState, type FormEvent } from 'react';
import { authCode, resetOutcome, signInErrorKey } from '@/lib/auth/firebase';
import { useAuth } from './auth-provider';

const field = 'mt-1 block w-full field py-2 text-base focus-visible:outline-2';

export function SignInForm() {
  const t = useTranslations('signIn');
  const ta = useTranslations('auth');
  const { state, auth } = useAuth();
  const router = useRouter();
  const locale = useLocale();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  useEffect(() => {
    if (state.kind === 'signed_in') router.replace(`/${locale}/`);
  }, [state.kind, router, locale]);

  if (state.kind === 'unavailable') return <p className="text-ink-2">{ta('configUnavailable')}</p>;

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (!auth) return;
    setBusy(true);
    setError(null);
    setNote(null);
    try {
      await auth.signIn(email.trim(), password);
    } catch (err) {
      setError(t(`errors.${signInErrorKey(err)}`));
    } finally {
      setBusy(false);
    }
  }

  async function onReset() {
    setError(null);
    const addr = email.trim();
    setNote(null);
    if (!addr) return setNote(t('resetNeedsEmail'));
    try {
      if (!auth) throw new Error('auth not ready');
      await auth.sendReset(addr);
      setNote(t('resetSent', { email: addr }));
    } catch (err) {
      const outcome = resetOutcome(err);
      // Same answer whether or not the account exists.
      if (outcome === 'sent') return setNote(t('resetSent', { email: addr }));
      if (outcome === 'invalidEmail') return setError(t('errors.invalidEmail'));
      console.warn('password reset failed:', authCode(err));
      setError(t('errors.resetLater'));
    }
  }

  return (
    <form onSubmit={onSubmit} className="w-full max-w-sm" noValidate>
      <h1 className="text-2xl font-bold tracking-tight">{t('title')}</h1>
      <p className="mt-1 text-sm text-ink-2">{t('intro')}</p>
      <label className="mt-6 block text-sm font-medium">
        {t('email')}
        <input
          type="email"
          name="email"
          autoComplete="username"
          dir="ltr"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className={field}
        />
      </label>
      <label className="mt-4 block text-sm font-medium">
        {t('password')}
        <input
          type="password"
          name="password"
          autoComplete="current-password"
          dir="ltr"
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className={field}
        />
      </label>
      {error && (
        <p role="alert" className="mt-4 text-sm text-danger">
          {error}
        </p>
      )}
      {note && (
        <p role="status" className="mt-4 text-sm text-ink-2">
          {note}
        </p>
      )}
      <button
        type="submit"
        disabled={busy || !auth}
        className="btn btn-primary mt-6 w-full py-2.5 text-base font-medium focus-visible:outline-2"
      >
        {busy ? t('submitting') : t('submit')}
      </button>
      <button
        type="button"
        onClick={() => void onReset()}
        className="mt-3 text-sm text-ink-2 underline underline-offset-2"
      >
        {t('forgot')}
      </button>
    </form>
  );
}
