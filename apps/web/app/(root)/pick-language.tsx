'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useEffect } from 'react';
import { defaultLocale, isLocale, LANG_KEY } from '@/i18n/routing';

export function PickLanguage() {
  const router = useRouter();
  useEffect(() => {
    const saved = localStorage.getItem(LANG_KEY);
    // The router adds the base path (/app) the site is served under.
    router.replace(`/${isLocale(saved) ? saved : defaultLocale}/`);
  }, [router]);
  return (
    <p className="p-4">
      <Link href="/en/">English</Link> ·{' '}
      <Link href="/ar/" lang="ar">
        العربية
      </Link>
    </p>
  );
}
