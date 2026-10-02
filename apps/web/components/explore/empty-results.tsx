'use client';

import { useTranslations } from 'next-intl';
import type { Envelope } from '@/lib/api/types';
import { Known } from '../ui/known';

/**
 * What stands in for the list when it has nothing: "no products match" only when the API answered
 * `ok`; any other status is the data not being available, with the API's reason, never "no
 * products".
 */
export function EmptyResults({ env }: { env: Pick<Envelope<unknown>, 'status' | 'reason'> }) {
  const t = useTranslations('explore');
  const ts = useTranslations('state');
  const tr = useTranslations('reasons');
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
