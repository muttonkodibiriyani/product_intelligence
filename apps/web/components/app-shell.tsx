'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useLocale, useTranslations } from 'next-intl';
import { useEffect, useState, type ReactNode } from 'react';
import { AppSidebar, NavFoot, NavList } from './app-sidebar';
import { AppTabbar } from './app-tabbar';
import { useAuth } from './auth-provider';
import { LangSwitch } from './lang-switch';
import { BrandMark } from './nav-icon';
import { useNav } from './use-nav';

const MAIN = 'min-w-0 flex-1 px-4 pt-5 pb-24 sm:px-7 lg:pb-10';

/**
 * The page frame. Signed in with a role: a sidebar at the start edge on wide screens; on phones a
 * compact top bar with the full menu, and a five-item tab bar at the bottom. Otherwise (sign-in,
 * no access, auth unavailable) a one-line header with the brand and the language switch.
 */
export function AppShell({ children }: { children: ReactNode }) {
  const { state } = useAuth();
  if (state.kind === 'signed_in' && state.session.role) return <Shell>{children}</Shell>;
  return <Plain>{children}</Plain>;
}

function Brand({ compact = false }: { compact?: boolean }) {
  const t = useTranslations('app');
  const locale = useLocale();
  return (
    <Link
      href={`/${locale}/`}
      className="flex items-center gap-2.5 rounded-ctl whitespace-nowrap text-ink focus-visible:outline-2"
    >
      <BrandMark />
      <span className="leading-tight">
        <b className="block text-[14px] font-bold">{t('name')}</b>
        {!compact && <span className="block text-[11px] text-ink-2">{t('tagline')}</span>}
      </span>
    </Link>
  );
}

function Plain({ children }: { children: ReactNode }) {
  const t = useTranslations('app');
  const { state, auth } = useAuth();
  return (
    <>
      <header className="border-b border-line bg-surface">
        <div className="mx-auto flex min-h-14 max-w-screen-2xl items-center gap-3 px-4 sm:px-7">
          <Brand />
          <div className="ms-auto flex items-center gap-1">
            <LangSwitch />
            {state.kind === 'signed_in' && (
              <button
                type="button"
                onClick={() => void auth?.signOut()}
                className="rounded-ctl px-2.5 py-1.5 text-sm text-ink-2 hover:bg-surface-2 hover:text-ink focus-visible:outline-2"
              >
                {t('signOut')}
              </button>
            )}
          </div>
        </div>
      </header>
      <main id="main" className="mx-auto max-w-screen-2xl px-4 py-6 sm:px-7 sm:py-8">
        {children}
      </main>
    </>
  );
}

function Shell({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-screen lg:grid lg:grid-cols-[216px_minmax(0,1fr)]">
      <AppSidebar />
      <div className="flex min-w-0 flex-col">
        <PhoneBar />
        <main id="main" className={MAIN}>
          {children}
        </main>
      </div>
      <AppTabbar />
    </div>
  );
}

/** The phone's top bar: brand, language, and a menu listing every page with the foot. */
function PhoneBar() {
  const t = useTranslations('app');
  const pathname = usePathname();
  const items = useNav();
  // The menu remembers the page it was opened on, so moving to another page closes it.
  const [openAt, setOpenAt] = useState<string | null>(null);
  const open = openAt === pathname;
  const setOpen = (v: boolean) => setOpenAt(v ? pathname : null);
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpenAt(null);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open]);
  return (
    <header className="sticky top-0 z-20 border-b border-line bg-surface lg:hidden">
      <div className="flex min-h-13 items-center gap-2 px-4 sm:px-7">
        <Brand compact />
        <div className="ms-auto flex items-center gap-1">
          <LangSwitch />
          <button
            type="button"
            aria-expanded={open}
            aria-controls="app-menu"
            onClick={() => setOpen(!open)}
            className="rounded-ctl px-2.5 py-1.5 text-sm text-ink-2 hover:bg-surface-2 hover:text-ink focus-visible:outline-2"
          >
            {open ? t('closeMenu') : t('menu')}
          </button>
        </div>
      </div>
      <div id="app-menu" hidden={!open} className="border-t border-line-2 px-3 pt-3 pb-3">
        <nav aria-label={t('nav.all')} className="mb-3">
          <NavList items={items} onNavigate={() => setOpen(false)} />
        </nav>
        <NavFoot />
      </div>
    </header>
  );
}
