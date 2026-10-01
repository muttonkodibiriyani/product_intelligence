'use client';

import { useTranslations } from 'next-intl';
import { useId, useState, type FormEvent } from 'react';
import { hasPair, SORTS, type ExploreState, type ProductSort } from '@/lib/explore';

/** Search, sort and the retailer pair the gap is measured between. */
export function Toolbar({
  state,
  update,
  name,
}: {
  state: ExploreState;
  update: (next: Partial<ExploreState>) => void;
  name: (id: string) => string;
}) {
  const t = useTranslations('explore');
  const ids = { q: useId(), sort: useId(), sortHint: useId() };
  // The parent keys this by the URL value, so Back or "clear" resets the box.
  const [q, setQ] = useState(state.q);
  const pair = hasPair(state) ? (state.retailer as [string, string]) : null;
  const names = pair ? { base: name(pair[0]), other: name(pair[1]) } : null;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    update({ q: q.trim().slice(0, 120) });
  };

  return (
    <div className="flex flex-wrap items-end gap-3">
      <form role="search" onSubmit={submit} className="flex min-w-0 flex-1 basis-64 gap-2">
        <label htmlFor={ids.q} className="sr-only">
          {t('searchLabel')}
        </label>
        <input
          id={ids.q}
          type="search"
          name="q"
          value={q}
          maxLength={120}
          onChange={(e) => setQ(e.target.value)}
          placeholder={t('searchPlaceholder')}
          className="min-w-0 flex-1 rounded border border-line bg-surface px-3 py-1.5 text-sm focus-visible:outline-2"
        />
        <button
          type="submit"
          className="rounded border border-line bg-surface px-3 py-1.5 text-sm hover:bg-surface-2 focus-visible:outline-2"
        >
          {t('search')}
        </button>
      </form>

      <div className="flex flex-col gap-1">
        <label htmlFor={ids.sort} className="text-xs text-ink-2">
          {t('sort')}
        </label>
        <select
          id={ids.sort}
          value={state.sort}
          aria-describedby={pair ? undefined : ids.sortHint}
          onChange={(e) => update({ sort: e.target.value as ProductSort })}
          className="rounded border border-line bg-surface px-2 py-1.5 text-sm focus-visible:outline-2"
        >
          {SORTS.map((s) => (
            <option key={s} value={s} disabled={(s === 'gap' || s === 'gap_asc') && !pair}>
              {t(`sorts.${s}`, { other: names?.other ?? '–' })}
            </option>
          ))}
        </select>
        {!pair && (
          <span id={ids.sortHint} className="sr-only">
            {t('gapNeedsPair')}
          </span>
        )}
      </div>

      {pair && names && (
        <div className="flex items-center gap-2 rounded border border-line bg-surface px-3 py-1.5 text-sm">
          <span>{t('pair', names)}</span>
          <button
            type="button"
            onClick={() => update({ retailer: [pair[1], pair[0]] })}
            className="rounded px-1.5 text-accent hover:bg-surface-2 focus-visible:outline-2"
          >
            {t('swap')}
          </button>
        </div>
      )}
    </div>
  );
}
