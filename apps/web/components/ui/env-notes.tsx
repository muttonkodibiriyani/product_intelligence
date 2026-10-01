'use client';

import { useLocale, useTranslations } from 'next-intl';
import type { Envelope } from '@/lib/api/types';
import { loc } from '@/lib/format';
import { Known } from './known';

/** Why the data is thin, and the caveats the API attached, in the user's language. */
export function EnvNotes({ env, className = '' }: { env: Envelope<unknown>; className?: string }) {
  const tr = useTranslations('reasons');
  const locale = useLocale();
  if (env.status !== 'not_enough_data' && env.caveats.length === 0) return null;
  return (
    <div
      role="note"
      className={`space-y-1 rounded border border-line bg-surface px-3 py-2 text-sm ${className}`}
    >
      {env.status === 'not_enough_data' && env.reason && (
        <p>{loc(env.detail, locale) || <Known t={tr} v={env.reason} />}</p>
      )}
      {env.caveats.map((c) => (
        <p key={c.code} className="text-ink-2">
          {locale === 'ar' ? c.ar || c.en : c.en}
        </p>
      ))}
    </div>
  );
}
