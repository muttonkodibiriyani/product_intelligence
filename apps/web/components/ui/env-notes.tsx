'use client';

import { useLocale, useTranslations } from 'next-intl';
import type { CaveatView, Envelope } from '@/lib/api/types';
import { loc } from '@/lib/format';
import { Known } from './known';

/** Why the data is thin, and the caveats the API attached, in the user's language. */
export function EnvNotes({ env, className = '' }: { env: Envelope<unknown>; className?: string }) {
  const tr = useTranslations('reasons');
  const locale = useLocale();
  if (env.status !== 'not_enough_data' && env.caveats.length === 0) return null;
  return (
    <div role="note" className={`space-y-1 panel px-4 py-3 text-sm ${className}`}>
      {env.status === 'not_enough_data' && env.reason && (
        <p>{loc(env.detail, locale) || <Known t={tr} v={env.reason} />}</p>
      )}
      <CaveatLines caveats={env.caveats} />
    </div>
  );
}

/** The caveats alone (already scoped to the retailers shown), as the API worded them. */
export function CaveatNotes({
  caveats,
  className = '',
}: {
  caveats: readonly CaveatView[];
  className?: string;
}) {
  if (caveats.length === 0) return null;
  return (
    <div role="note" className={`space-y-1 panel px-4 py-3 text-sm ${className}`}>
      <CaveatLines caveats={caveats} />
    </div>
  );
}

function CaveatLines({ caveats }: { caveats: readonly CaveatView[] }) {
  const locale = useLocale();
  // A code can repeat (retailer_partial once per side), so the index is part of the key.
  return caveats.map((c, i) => (
    <p key={`${c.code}:${i}`} className="text-ink-2">
      {locale === 'ar' ? c.ar || c.en : c.en}
    </p>
  ));
}
