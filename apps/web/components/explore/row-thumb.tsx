'use client';

import Image from 'next/image';
import { useState } from 'react';
import { imageSrc } from '../widgets/model';

/**
 * The letters a product shows when there is no picture: the brand's initials ("Estée Lauder" →
 * EL, "Yves Saint Laurent" → YSL), the first two letters of a one-word brand ("Clinique" → CL),
 * or a short all-caps brand as it is ("NARS").
 */
export function monogram(brand: string): string {
  const words = brand.trim().split(/\s+/).filter(Boolean);
  if (words.length === 0) return '';
  if (words.length === 1) {
    const w = words[0]!;
    return w.length <= 4 && w === w.toUpperCase() ? w : w.slice(0, 2).toUpperCase();
  }
  return words
    .slice(0, 3)
    .map((w) => w[0]!.toUpperCase())
    .join('');
}

/**
 * A product thumbnail: 48px floated in a list row, or larger on the product page. Only an https
 * image on a listed retailer image host is shown, hotlinked (decision B): the static export has no
 * image proxy, so `unoptimized` makes the browser load the URL itself. Lazy, without a referrer; a
 * placeholder only when there is no allowed URL or it fails: the brand's monogram when given, else
 * a picture icon. The product's name sits next to it, so the image itself is not announced again.
 */
export function RowThumb({
  url,
  label,
  monogram: letters,
  px = 48,
  cls = 'float-start me-3 size-12 rounded-ctl bg-surface-2',
}: {
  url: string | null | undefined;
  label: string;
  /** Letters to show instead of the icon when there is no image (see `monogram`). */
  monogram?: string;
  px?: number;
  cls?: string;
}) {
  const src = imageSrc(url);
  const [failed, setFailed] = useState<string | null>(null);
  if (!src || failed === src)
    return (
      <span
        role="img"
        aria-label={label}
        className={`${cls} grid place-items-center ${letters ? 'text-ink-3' : 'text-line-3'}`}
      >
        {letters ? (
          <span
            aria-hidden
            dir="auto"
            className={`font-semibold tracking-wide ${px > 64 ? 'text-2xl' : 'text-xs'}`}
          >
            {letters}
          </span>
        ) : (
          <svg
            width={px > 64 ? 40 : 18}
            height={px > 64 ? 40 : 18}
            viewBox="0 0 24 24"
            aria-hidden
            fill="none"
            stroke="currentColor"
            strokeWidth="1.6"
          >
            <rect x="3" y="4" width="18" height="16" rx="3" />
            <path d="m3 16 5-5 4 4 3-3 6 6" />
          </svg>
        )}
      </span>
    );
  return (
    <Image
      src={src}
      alt=""
      width={px}
      height={px}
      unoptimized
      loading="lazy"
      referrerPolicy="no-referrer"
      onError={() => setFailed(src)}
      className={`${cls} object-contain`}
    />
  );
}
