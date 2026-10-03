'use client';

import Link from 'next/link';
import { useLocale, useTranslations } from 'next-intl';
import type { Envelope } from '@/lib/api/types';
import { navHref } from '@/lib/nav';
import { Known } from '../ui/known';

/**
 * What stands in for the list when it has nothing: "no products match" only when the API answered
 * `ok`; any other status is the data not being available, with the API's reason, never "no
 * products". Under "sold at both shops" the empty list means no pair is published for these
 * products, so it says that and points to the by-category prices, which need no matching.
 */
export function EmptyResults({
  env,
  matchedOnly = false,
}: {
  env: Pick<Envelope<unknown>, 'status' | 'reason'>;
  /** The "sold at both shops" filter is on. */
  matchedOnly?: boolean;
}) {
  const t = useTranslations('explore');
  const ts = useTranslations('state');
  const tr = useTranslations('reasons');
  const locale = useLocale();
  if (env.status === 'ok' && matchedOnly)
    return (
      <div className="panel px-5 py-6">
        <p className="font-medium">{t('emptyMatched')}</p>
        <p className="mt-1 text-sm text-ink-2">{t('emptyMatchedHint')}</p>
        <Link href={navHref('prices', locale)} className="btn mt-4 text-sm focus-visible:outline-2">
          {t('emptyMatchedLink')}
        </Link>
      </div>
    );
  if (env.status === 'ok')
    return (
      <div className="panel px-5 py-6">
        <p className="font-medium">{t('empty')}</p>
        <p className="mt-1 text-sm text-ink-2">{t('emptyHint')}</p>
      </div>
    );
  return (
    <div role="status" className="panel px-5 py-6">
      <p className="font-medium">{ts('notAvailable')}</p>
      {env.reason && (
        <p className="mt-1 text-sm text-ink-2">
          <Known t={tr} v={env.reason} />
        </p>
      )}
    </div>
  );
}
