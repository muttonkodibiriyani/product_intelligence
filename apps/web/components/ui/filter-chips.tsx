'use client';

import { useTranslations } from 'next-intl';

type Key = 'brand' | 'category';

/**
 * Brand and category filters that came in with the URL (or a group click), each removable; with
 * `retailer` and `removeRetailer`, the shop filter too, shown by `name`.
 */
export function FilterChips({
  retailer = [],
  brand,
  category,
  name = (id) => id,
  remove,
  removeRetailer,
}: {
  retailer?: readonly string[];
  brand: readonly string[];
  category: readonly string[];
  name?: (id: string) => string;
  remove: (k: Key, v: string) => void;
  removeRetailer?: (v: string) => void;
}) {
  const t = useTranslations('chips');
  const chips = [
    ...(removeRetailer
      ? retailer.map((v) => ({
          k: 'retailer',
          v,
          label: t('shop', { value: name(v) }),
          off: () => removeRetailer(v),
        }))
      : []),
    ...brand.map((v) => ({ k: 'brand', v, label: t('brand', { value: v }), off: () => remove('brand', v) })),
    ...category.map((v) => ({
      k: 'category',
      v,
      label: t('category', { value: v }),
      off: () => remove('category', v),
    })),
  ];
  if (chips.length === 0) return null;
  return (
    <ul aria-label={t('label')} className="flex flex-wrap gap-2">
      {chips.map((f) => (
        <li key={`${f.k}:${f.v}`}>
          <button
            type="button"
            onClick={f.off}
            className="inline-flex items-center gap-1.5 rounded-full bg-lav px-3 py-1 text-[13px] font-medium text-lav-ink hover:bg-[#e4def8] focus-visible:outline-2"
          >
            <span dir="auto">{f.label}</span>
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
