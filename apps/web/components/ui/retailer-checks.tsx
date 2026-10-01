'use client';

import { useTranslations } from 'next-intl';
import { toggle } from '@/lib/explore';
import { useMeta } from '../use-meta';

/** Retailers from /meta as checkboxes. None ticked means all of them. */
export function RetailerChecks({
  value,
  onChange,
}: {
  value: readonly string[];
  onChange: (next: string[]) => void;
}) {
  const t = useTranslations('retailerChecks');
  const th = useTranslations('home');
  const retailers = useMeta().data?.data?.retailers ?? [];
  return (
    <fieldset className="min-w-0">
      <legend className="text-xs font-medium text-ink-2">{t('legend')}</legend>
      <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1">
        {retailers.map((r) => (
          <label key={r.id} className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={value.includes(r.id)}
              onChange={() => onChange(toggle(value, r.id))}
              className="focus-visible:outline-2"
            />
            {r.name}
            {r.status !== 'supported' && th.has(`status.${r.status}`) && (
              <span className="text-xs text-ink-2">{th(`status.${r.status}`)}</span>
            )}
          </label>
        ))}
      </div>
      <p className="mt-1 text-xs text-ink-2">{t('hint')}</p>
    </fieldset>
  );
}
