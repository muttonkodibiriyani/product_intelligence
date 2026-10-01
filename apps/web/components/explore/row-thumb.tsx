'use client';

import Image from 'next/image';
import { useState } from 'react';
import { imageSrc } from '../widgets/model';

/**
 * A product thumbnail: 48px floated in a list row, or larger on the product page. Only an https
 * image on a listed retailer image host is shown, hotlinked (decision B): the static export has no
 * image proxy, so `unoptimized` makes the browser load the URL itself. Lazy, without a referrer; a
 * placeholder only when there is no allowed URL or it fails. The product's name sits next to it,
 * so the image itself is not announced again.
 */
export function RowThumb({
  url,
  label,
  px = 48,
  cls = 'float-start me-3 size-12 rounded-ctl bg-surface-2',
}: {
  url: string | null | undefined;
  label: string;
  px?: number;
  cls?: string;
}) {
  const src = imageSrc(url);
  const [failed, setFailed] = useState<string | null>(null);
  if (!src || failed === src)
    return (
      <span role="img" aria-label={label} className={`${cls} grid place-items-center text-line-3`}>
        <svg
          width="18"
          height="18"
          viewBox="0 0 24 24"
          aria-hidden
          fill="none"
          stroke="currentColor"
          strokeWidth="1.6"
        >
          <rect x="3" y="4" width="18" height="16" rx="3" />
          <path d="m3 16 5-5 4 4 3-3 6 6" />
        </svg>
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
