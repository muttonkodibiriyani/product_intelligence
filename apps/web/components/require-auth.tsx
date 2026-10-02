'use client';

import { useRouter } from 'next/navigation';
import { useLocale, useTranslations } from 'next-intl';
import { useEffect, useState, type ReactNode } from 'react';
import { useAuth } from './auth-provider';

/** Renders children only for a signed-in user with a role; otherwise says why. */
export function RequireAuth({ children }: { children: ReactNode }) {
  const t = useTranslations('auth');
  const { state, auth } = useAuth();
  const [checking, setChecking] = useState(false);
  const router = useRouter();
  const locale = useLocale();

  useEffect(() => {
    if (state.kind === 'signed_out') router.replace(`/${locale}/sign-in/`);
  }, [state.kind, router, locale]);

  if (state.kind === 'unavailable') return <Notice>{t('configUnavailable')}</Notice>;
  if (state.kind !== 'signed_in') return <Notice busy>{t('loading')}</Notice>;
  // The claims could not be read (identity outage): the role is unknown, not missing.
  if (!state.session.verified)
    return (
      <section className="max-w-prose" role="status">
        <p className="text-ink">{t('verifying')}</p>
        <button
          type="button"
          disabled={checking}
          onClick={() => {
            setChecking(true);
            // A refreshed token re-runs the claims check through `watch`; a failure keeps this screen.
            void auth
              ?.recheck()
              .catch(() => {})
              .finally(() => setChecking(false));
          }}
          className="mt-3 btn focus-visible:outline-2"
        >
          {t('recheck')}
        </button>
      </section>
    );
  if (!state.session.role)
    return (
      <section className="max-w-prose">
        <h1 className="text-lg font-semibold">{t('noRoleTitle')}</h1>
        <p className="mt-2 text-ink-2">{t('noRole')}</p>
      </section>
    );
  return <>{children}</>;
}

function Notice({ children, busy }: { children: ReactNode; busy?: boolean }) {
  return (
    <p className="text-ink-2" role="status" aria-busy={busy}>
      {children}
    </p>
  );
}
