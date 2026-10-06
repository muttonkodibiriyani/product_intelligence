'use client';

import Link from 'next/link';
import { useTranslations } from 'next-intl';
import { TABBAR_KEYS } from '@/lib/nav';
import { NavIcon } from './nav-icon';
import { useNav } from './use-nav';

/**
 * The phone's bottom tab bar: up to five pages, the same visibility rules as the sidebar. The
 * other pages are in the phone menu (the "All pages" navigation).
 */
export function AppTabbar() {
  const t = useTranslations('app');
  const items = useNav().filter((i) => (TABBAR_KEYS as readonly string[]).includes(i.key));
  return (
    <nav
      aria-label={t('mainNav')}
      className="fixed inset-x-0 bottom-0 z-20 border-t border-line bg-surface pb-[env(safe-area-inset-bottom)] lg:hidden"
    >
      <ul className="flex">
        {items.map((item) => (
          <li key={item.key} className="min-w-0 flex-1">
            <Link
              href={item.href}
              aria-current={item.current ? 'page' : undefined}
              className={`flex flex-col items-center gap-0.5 px-1 pt-2 pb-1.5 text-[11px] leading-4 focus-visible:outline-2 ${
                item.current ? 'font-semibold text-ink' : 'text-ink-2'
              }`}
            >
              <span
                className={`grid h-6 w-10 place-items-center rounded-full ${item.current ? 'bg-ink text-white' : ''}`}
              >
                <NavIcon name={item.key} size={18} />
              </span>
              <span className="max-w-full truncate">
                {item.key === 'assistant' ? t('nav.assistantShort') : item.label}
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  );
}
