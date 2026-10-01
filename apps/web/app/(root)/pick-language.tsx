'use client';

import Link from 'next/link';
import { useEffect } from 'react';
import { defaultLocale, isLocale, LANG_KEY } from '@/i18n/routing';

export function PickLanguage() {
  useEffect(() => {
    const saved = localStorage.getItem(LANG_KEY);
    window.location.replace(`/${isLocale(saved) ? saved : defaultLocale}/`);
  }, []);
  return (
    <p className="p-4">
      <Link href="/en/">English</Link> ·{' '}
      <Link href="/ar/" lang="ar">
        العربية
      </Link>
    </p>
  );
}
