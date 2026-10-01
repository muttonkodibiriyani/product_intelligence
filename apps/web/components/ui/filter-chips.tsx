'use client';

import { useTranslations } from 'next-intl';

type Key = 'brand' | 'category';

/** Brand and category filters that came in with the URL (or a group click), each removable. */
export function FilterChips({
  brand,
  category,
  remove,
}: {
  brand: readonly string[];
  category: readonly string[];
  remove: (k: Key, v: string) => void;
}) {
  const t = useTranslations('chips');
  const chips = [
    ...brand.map((v) => ({ k: 'brand' as const, v })),
    ...category.map((v) => ({ k: 'category' as const, v })),
  ];
  if (chips.length === 0) return null;
  return (
    <ul aria-label={t('label')} className="flex flex-wrap gap-2">
      {chips.map((f) => (
        <li key={`${f.k}:${f.v}`}>
          <button
            type="button"
            onClick={() => remove(f.k, f.v)}
            className="inline-flex items-center gap-1.5 rounded-full bg-lav px-3 py-1 text-[13px] font-medium text-lav-ink hover:bg-[#e4def8] focus-visible:outline-2"
          >
            {t(f.k, { value: f.v })}
            <span aria-hidden className="ms-2 text-ink-2">
              ×
            </span>
            <span className="sr-only">{t('remove')}</span>
          </button>
        </li>
      ))}
    </ul>
  );
}
