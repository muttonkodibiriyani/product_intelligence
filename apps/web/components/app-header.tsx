'use client';

import Link from 'next/link';
import { useLocale, useTranslations } from 'next-intl';
import { useAuth } from './auth-provider';
import { LangSwitch } from './lang-switch';

export function AppHeader() {
  const t = useTranslations('app');
  const locale = useLocale();
  const { state, auth } = useAuth();
  return (
    <header className="border-b border-line bg-surface">
      <div className="mx-auto flex h-12 max-w-screen-2xl items-center gap-4 px-4">
        <Link href={`/${locale}/`} className="font-semibold tracking-tight text-ink">
          {t('name')}
        </Link>
        <div className="ms-auto flex items-center gap-3">
          {state.kind === 'signed_in' && (
            <>
              <span className="hidden text-sm text-ink-2 sm:inline" dir="ltr">
                {state.session.email}
              </span>
              <button
                type="button"
                onClick={() => void auth?.signOut()}
                className="rounded px-2 py-1 text-sm text-ink-2 hover:bg-surface-2 focus-visible:outline-2"
              >
                {t('signOut')}
              </button>
            </>
          )}
          <LangSwitch />
        </div>
      </div>
    </header>
  );
}
