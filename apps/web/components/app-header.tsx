'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useLocale, useTranslations } from 'next-intl';
import { useAuth } from './auth-provider';
import { LangSwitch } from './lang-switch';

export function AppHeader() {
  const t = useTranslations('app');
  const locale = useLocale();
  const { state, auth } = useAuth();
  const pathname = usePathname();
  const nav = [
    { href: `/${locale}/explore/`, label: t('nav.explore'), match: /^\/(en|ar)\/(explore|product)\// },
    { href: `/${locale}/compare/`, label: t('nav.compare'), match: /^\/(en|ar)\/compare\// },
    { href: `/${locale}/`, label: t('nav.status'), match: /^\/(en|ar)\/?$/ },
  ];
  return (
    <header className="border-b border-line bg-surface">
      <div className="mx-auto flex min-h-12 max-w-screen-2xl flex-wrap items-center gap-x-4 px-4 py-1.5 sm:flex-nowrap">
        <Link href={`/${locale}/`} className="font-semibold tracking-tight whitespace-nowrap text-ink">
          {t('name')}
        </Link>
        {state.kind === 'signed_in' && state.session.role && (
          <nav aria-label={t('mainNav')} className="order-last -ms-2 w-full sm:order-none sm:ms-0 sm:w-auto">
            <ul className="flex gap-1">
              {nav.map((n) => {
                const current = n.match.test(pathname);
                return (
                  <li key={n.href}>
                    <Link
                      href={n.href}
                      aria-current={current ? 'page' : undefined}
                      className={`rounded px-2 py-1 text-sm hover:bg-surface-2 focus-visible:outline-2 ${
                        current ? 'font-medium text-ink' : 'text-ink-2'
                      }`}
                    >
                      {n.label}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </nav>
        )}
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
