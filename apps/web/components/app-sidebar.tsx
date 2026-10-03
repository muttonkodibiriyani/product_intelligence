'use client';

import Link from 'next/link';
import { useTranslations } from 'next-intl';
import { NAV_SECTION_BREAK } from '@/lib/nav';
import { useAuth } from './auth-provider';
import { LangSwitch } from './lang-switch';
import { Logo } from './logo';
import { NavIcon } from './nav-icon';
import { useNav, type NavItem } from './use-nav';

/** One nav link: icon, label, and a "soon" badge for a page the data cannot fill yet. */
export function NavLink({ item, onNavigate }: { item: NavItem; onNavigate?: () => void }) {
  const t = useTranslations('app');
  return (
    <Link
      href={item.href}
      aria-current={item.current ? 'page' : undefined}
      onClick={onNavigate}
      className={`flex items-center gap-2.5 rounded-ctl px-2.5 py-1.5 text-sm focus-visible:outline-2 ${
        item.current ? 'bg-ink font-medium text-white' : 'text-ink-2 hover:bg-surface-2 hover:text-ink'
      }`}
    >
      <NavIcon name={item.key} />
      <span className="min-w-0 flex-1 truncate">{item.label}</span>
      {item.state === 'soon' && (
        <span
          className={`ms-auto rounded-full px-1.5 text-[10px] leading-4 font-semibold uppercase ${
            item.current ? 'bg-white/20 text-white' : 'bg-surface-2 text-ink-2'
          }`}
        >
          {t('nav.soon')}
        </span>
      )}
    </Link>
  );
}

/** The nav's two groups: the pages, then a rule and the data section (About the data, the assistant). */
export function NavList({ items, onNavigate }: { items: NavItem[]; onNavigate?: () => void }) {
  const t = useTranslations('app');
  const at = items.findIndex((i) => i.key === NAV_SECTION_BREAK);
  const pages = at < 0 ? items : items.slice(0, at);
  const data = at < 0 ? [] : items.slice(at);
  return (
    <>
      <ul className="flex flex-col gap-0.5">
        {pages.map((item) => (
          <li key={item.key}>
            <NavLink item={item} onNavigate={onNavigate} />
          </li>
        ))}
      </ul>
      {data.length > 0 && (
        <>
          <div className="mt-4 mb-1 border-t border-line-2 px-2.5 pt-3 text-[11px] font-semibold tracking-wide text-ink-3 uppercase">
            {t('nav.data')}
          </div>
          <ul className="flex flex-col gap-0.5">
            {data.map((item) => (
              <li key={item.key}>
                <NavLink item={item} onNavigate={onNavigate} />
              </li>
            ))}
          </ul>
        </>
      )}
    </>
  );
}

/** Who is signed in, the language switch and sign out; the sidebar's foot and the phone menu's. */
export function NavFoot() {
  const t = useTranslations('app');
  const { state, auth } = useAuth();
  return (
    <div className="flex flex-col gap-2 border-t border-line-2 px-2.5 pt-3 text-xs text-ink-2">
      {state.kind === 'signed_in' && state.session.email && (
        <div className="truncate" title={state.session.email}>
          {t('signedInAs', { email: state.session.email })}
        </div>
      )}
      <div className="-ms-2.5 flex flex-wrap items-center">
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
  );
}

/** The desktop sidebar: brand, the main navigation, and the foot. Sits at the start edge, so on the right in Arabic. */
export function AppSidebar() {
  const t = useTranslations('app');
  const items = useNav();
  return (
    <aside className="sticky top-0 hidden h-screen flex-col gap-4 border-e border-line bg-surface px-3 pt-4 pb-3 lg:flex">
      <Logo className="px-1.5" />
      <nav aria-label={t('mainNav')} className="min-h-0 flex-1 overflow-y-auto">
        <NavList items={items} />
      </nav>
      <NavFoot />
    </aside>
  );
}
