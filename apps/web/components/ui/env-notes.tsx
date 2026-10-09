'use client';

import { useLocale } from 'next-intl';
import type { CaveatView, Envelope } from '@/lib/api/types';
import { loc } from '@/lib/format';
import { withRetailerNames } from '@/lib/retailers';
import { useRetailerName } from '../use-meta';
import { Reason } from './known';

/**
 * Why the data is thin, and the caveats the API attached, in the user's language and with shop
 * names in place of retailer ids. Rendered in one place only: "About the data" on the Dataset
 * page; no other page draws a note box.
 */
export function EnvNotes({ env, className = '' }: { env: Envelope<unknown>; className?: string }) {
  const locale = useLocale();
  const name = useRetailerName();
  if (env.status !== 'not_enough_data' && env.caveats.length === 0) return null;
  const detail = loc(env.detail, locale);
  return (
    <div role="note" className={`space-y-1 panel px-4 py-3 text-sm ${className}`}>
      {env.status === 'not_enough_data' && env.reason && (
        <p>{detail ? withRetailerNames(detail, name) : <Reason v={env.reason} />}</p>
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
  const name = useRetailerName();
  // A code can repeat (retailer_partial once per side), so the index is part of the key.
  return caveats.map((c, i) => (
    <p key={`${c.code}:${i}`} className="text-ink-2">
      {withRetailerNames(locale === 'ar' ? c.ar || c.en : c.en, name)}
    </p>
  ));
}
