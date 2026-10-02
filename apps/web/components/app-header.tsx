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
    { href: `/${locale}/prices/`, label: t('nav.prices'), match: /^\/(en|ar)\/prices\// },
    { href: `/${locale}/compare/`, label: t('nav.compare'), match: /^\/(en|ar)\/compare\// },
    { href: `/${locale}/promotions/`, label: t('nav.promotions'), match: /^\/(en|ar)\/promotions\// },
    { href: `/${locale}/launches/`, label: t('nav.launches'), match: /^\/(en|ar)\/launches\// },
    { href: `/${locale}/dataset/`, label: t('nav.status'), match: /^\/(en|ar)\/dataset\// },
    { href: `/${locale}/assistant/`, label: t('nav.assistant'), match: /^\/(en|ar)\/assistant\// },
  ];
  return (
    <header className="border-b border-line bg-surface">
      <div className="mx-auto flex min-h-15 max-w-screen-2xl flex-wrap items-center gap-x-5 px-4 py-2 sm:flex-nowrap sm:px-6">
        <Link
          href={`/${locale}/`}
          className="flex items-center gap-2.5 rounded-ctl whitespace-nowrap text-ink focus-visible:outline-2"
        >
          <span aria-hidden="true" className="grid size-8 place-items-center rounded-[9px] bg-lav">
            <svg width="18" height="18" viewBox="0 0 18 18">
              <rect x="2" y="9" width="3" height="7" rx="1" fill="#5A47A3" />
              <rect x="7.5" y="5" width="3" height="11" rx="1" fill="#5A47A3" />
              <rect x="13" y="2" width="3" height="14" rx="1" fill="#D9668C" />
            </svg>
          </span>
          <span className="leading-tight">
            <b className="block text-[15px] font-bold">{t('name')}</b>
            <span className="block text-xs text-ink-2">{t('tagline')}</span>
          </span>
        </Link>
        {state.kind === 'signed_in' && state.session.role && (
          <nav aria-label={t('mainNav')} className="order-last -ms-2 w-full sm:order-none sm:ms-0 sm:w-auto">
            <ul className="flex flex-wrap gap-1">
              {nav.map((n) => {
                const current = n.match.test(pathname);
                return (
                  <li key={n.href}>
                    <Link
                      href={n.href}
                      aria-current={current ? 'page' : undefined}
                      className={`block rounded-ctl px-3 py-1.5 text-sm focus-visible:outline-2 ${
                        current
                          ? 'bg-lav font-semibold text-lav-ink'
                          : 'text-ink-2 hover:bg-surface-2 hover:text-ink'
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
                className="rounded-ctl px-2.5 py-1.5 text-sm text-ink-2 hover:bg-surface-2 hover:text-ink focus-visible:outline-2"
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
