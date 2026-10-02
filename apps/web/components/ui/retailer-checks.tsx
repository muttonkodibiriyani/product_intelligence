'use client';

import { useTranslations } from 'next-intl';
import { toggle } from '@/lib/explore';
import { retailerName } from '@/lib/retailers';
import { useMeta } from '../use-meta';

/**
 * Retailers from /meta as checkboxes, each by its shop name only. None ticked means all of them.
 * How well a shop is collected is explained once, under "About the data" on the Dataset page.
 */
export function RetailerChecks({
  value,
  onChange,
}: {
  value: readonly string[];
  onChange: (next: string[]) => void;
}) {
  const t = useTranslations('retailerChecks');
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
            {retailerName(r.id, r.name)}
          </label>
        ))}
      </div>
      <p className="mt-1 text-xs text-ink-2">{t('hint')}</p>
    </fieldset>
  );
}
