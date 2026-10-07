'use client';

import Link from 'next/link';
import { useLocale, useTranslations } from 'next-intl';
import { useRouter } from 'next/navigation';
import { useEffect } from 'react';

/**
 * The old three-shop report now lives on Insights, whose selector shows every shop by default:
 * an old link lands there with all shops. The router adds the base path (/app).
 */
export function ThreeRedirect() {
  const locale = useLocale();
  const t = useTranslations('insights');
  const router = useRouter();
  const href = `/${locale}/insights/`;
  useEffect(() => {
    router.replace(href);
  }, [router, href]);
  return (
    <p className="p-4 text-sm">
      <Link href={href} className="text-accent underline-offset-2 hover:underline">
        {t('title')}
      </Link>
    </p>
  );
}
