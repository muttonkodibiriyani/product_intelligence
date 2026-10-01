'use client';

import Link from 'next/link';
import { useTranslations } from 'next-intl';
import { useState } from 'react';
import type { Summary } from '@/lib/api/summary';
import { productHref } from '../explore/product-table';
import { Money } from '../ui/money';
import { IMAGE_OWNERS, imageHost, imageSrc, pct, type ImageHost } from './model';

const TH = 'th whitespace-nowrap';
const TD = 'px-3 py-2.5 align-middle';

/** The deepest markdowns: a thumbnail, the product, its category, now and was, and the depth. */
export function TopDiscountsWidget({
  data,
  locale,
  retailer,
}: {
  data: NonNullable<Summary['topDiscounts']>;
  locale: string;
  /** The snapshot's retailer: only its own image host is shown. */
  retailer: string;
}) {
  const t = useTranslations('widgets.top');
  // Only the retailer's own image host is shown; once one of its images has loaded, credit the
  // host's owner with a link. A row without an allowed image gets the placeholder and no credit.
  const [loaded, setLoaded] = useState<ReadonlySet<ImageHost>>(new Set());
  const credit = (h: ImageHost | null) => () => h && setLoaded((s) => (s.has(h) ? s : new Set(s).add(h)));
  return (
    <div className="relative overflow-x-auto px-2">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-line">
            <th scope="col" className={`${TH} w-14`}>
              <span className="sr-only">{t('noImage')}</span>
            </th>
            <th scope="col" className={TH}>
              {t('product')}
            </th>
            <th scope="col" className={`${TH} max-sm:hidden`}>
              {t('category')}
            </th>
            <th scope="col" className={`${TH} text-end`}>
              {t('price')}
            </th>
            <th scope="col" className={`${TH} text-end max-sm:hidden`}>
              {t('was')}
            </th>
            <th scope="col" className={`${TH} text-end`}>
              {t('off')}
            </th>
          </tr>
        </thead>
        <tbody>
          {data.map((d) => (
            <tr key={d.id} className="border-t border-line-2 hover:bg-surface-2">
              <td className={`${TD} w-14`}>
                <Thumb
                  src={imageSrc(d.image, retailer)}
                  alt={t('noImage')}
                  onLoad={credit(imageHost(d.image, retailer))}
                />
              </td>
              <th scope="row" className={`${TD} text-start font-normal`}>
                <span className="block text-xs text-ink-2" dir="auto">
                  {d.brand}
                </span>
                <Link
                  href={productHref(locale, d.id)}
                  className="line-clamp-2 font-medium text-ink hover:underline focus-visible:outline-2"
                  dir="auto"
                >
                  {d.name}
                </Link>
              </th>
              <td className={`${TD} text-ink-2 max-sm:hidden`} dir="auto">
                {d.category[d.category.length - 1] ?? ''}
              </td>
              <td className={`${TD} text-end font-semibold whitespace-nowrap`}>
                <Money m={d.price} locale={locale} />
              </td>
              <td className={`${TD} text-end whitespace-nowrap text-ink-2 line-through max-sm:hidden`}>
                <Money m={d.regular} locale={locale} />
              </td>
              <td className={`${TD} text-end`}>
                <span className="pill bg-blush font-semibold text-blush-ink tabular-nums">
                  −{pct(d.depthPct, locale)}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {[...loaded].map((h) => (
        <p key={h} className="px-3 pt-2 pb-3 text-xs text-ink-2">
          {t.rich('credit', {
            retailer: IMAGE_OWNERS[h].name,
            host: h,
            link: (chunks) => (
              <a
                href={IMAGE_OWNERS[h].home}
                target="_blank"
                rel="noopener noreferrer"
                className="underline hover:text-ink focus-visible:outline-2"
              >
                {chunks}
              </a>
            ),
          })}
        </p>
      ))}
    </div>
  );
}

/** A lazy thumbnail from the retailer's image host; a quiet placeholder when there is none or it fails. */
function Thumb({ src, alt, onLoad }: { src: string | null; alt: string; onLoad: () => void }) {
  const [failed, setFailed] = useState(false);
  if (!src || failed)
    return (
      <span
        role="img"
        aria-label={alt}
        className="grid size-11 place-items-center rounded-ctl bg-surface-2 text-line-3"
      >
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
    // Hotlinked by decision B; next/image needs a loader the static export doesn't have.
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={src}
      alt=""
      loading="lazy"
      decoding="async"
      referrerPolicy="no-referrer"
      width={44}
      height={44}
      onLoad={onLoad}
      onError={() => setFailed(true)}
      className="size-11 rounded-ctl bg-surface-2 object-contain"
    />
  );
}
