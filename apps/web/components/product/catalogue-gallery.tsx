'use client';

import { useQuery } from '@tanstack/react-query';
import { useLocale, useTranslations } from 'next-intl';
import { useState } from 'react';
import { ApiError } from '@/lib/api/client';
import type { Schemas } from '@/lib/api/types';
import { formatDate } from '@/lib/format';
import { useAuth } from '../auth-provider';
import { ErrorNotice } from '../error-notice';
import { RowThumb } from '../explore/row-thumb';
import { Card } from '../ui/card';
import { imageSrc } from '../widgets/model';

export function CatalogueGallery({ sku }: { sku: string }) {
  const t = useTranslations('catalogue');
  const { api } = useAuth();
  const [selected, setSelected] = useState(sku);
  const q = useQuery({
    queryKey: ['catalogue', 'ulta_ae', selected],
    queryFn: ({ signal }) =>
      api!.get('/api/v1/catalogues/{retailer}/skus/{sku}', {
        params: { retailer: 'ulta_ae', sku: selected },
        signal,
      }),
    enabled: !!api,
  });
  // The catalogue is optional; deployments without it still have valid product pages.
  if (q.isError && q.error instanceof ApiError && q.error.code === 'not_found') return null;
  return (
    <Card title={t('title')} question={t('hint')}>
      {q.isError ? (
        <ErrorNotice error={q.error} onRetry={() => void q.refetch()} />
      ) : q.data?.data ? (
        <GalleryDetails detail={q.data.data} onSelect={setSelected} />
      ) : (
        <p role="status" aria-busy>
          {t('loading')}
        </p>
      )}
      {selected !== sku && (
        <button type="button" onClick={() => setSelected(sku)} className="mt-4 text-sm text-accent underline">
          {t('returnSku', { sku })}
        </button>
      )}
    </Card>
  );
}

export function GalleryDetails({
  detail,
  onSelect,
}: {
  detail: Schemas['CatalogueDetail'];
  onSelect: (sku: string) => void;
}) {
  const t = useTranslations('catalogue');
  const locale = useLocale();
  const row = detail.record;
  return (
    <div className="space-y-4" data-testid="catalogue-gallery" data-sku={row.sku}>
      <p className="font-semibold">
        <bdi>{row.name}</bdi> · <bdi>{row.sku}</bdi>
      </p>
      <p className="text-xs text-ink-2">
        {t('capture', {
          captured: formatDate(row.capturedAt, locale),
          imported: formatDate(detail.importedAt, locale),
        })}
      </p>
      <Images key={row.sku} images={detail.images} retailer={detail.retailer} />
      <dl className="grid gap-2 text-sm sm:grid-cols-2">
        <div>
          <dt className="text-ink-2">{t('type')}</dt>
          <dd>{row.isVariant ? t('variant') : t('listing')}</dd>
        </div>
        <div>
          <dt className="text-ink-2">{t('stockId')}</dt>
          <dd>
            <bdi>{row.sourceIds.stockId ?? t('unknown')}</bdi>
          </dd>
        </div>
      </dl>
      <details className="text-sm">
        <summary className="cursor-pointer text-ink-2">{t('identifiers')}</summary>
        <dl className="mt-2 space-y-2 break-all">
          <div>
            <dt>{t('catalogueId')}</dt>
            <dd>
              <bdi>{row.sourceIds.catalogueId ?? t('unknown')}</bdi>
            </dd>
          </div>
          <div>
            <dt>{t('externalId')}</dt>
            <dd>
              <bdi>{row.sourceIds.externalId ?? t('unknown')}</bdi>
            </dd>
          </div>
        </dl>
      </details>
      {row.excludedParentSummary && <p className="text-sm text-ink-2">{t('parentSummary')}</p>}
      <Related title={t('parents')} rows={detail.parents} onSelect={onSelect} />
      <Related title={t('variants')} rows={detail.children} onSelect={onSelect} />
    </div>
  );
}

function Images({ images, retailer }: { images: Schemas['GalleryImage'][]; retailer: string }) {
  const t = useTranslations('catalogue');
  const [selected, setSelected] = useState<string | null>(null);
  const active = images.find((i) => i.assetId === selected) ?? images[0];
  if (!active) return <p className="text-sm text-ink-2">{t('noImages')}</p>;
  const url = imageSrc(active.url, retailer);
  return (
    <div className="space-y-3">
      <RowThumb
        url={url}
        label={t('noImages')}
        retailer={retailer}
        px={420}
        cls="mx-auto block h-80 max-w-full rounded-card bg-white"
      />
      <div className="flex flex-wrap gap-2" role="group" aria-label={t('images')}>
        {images.map((image, index) => (
          <button
            type="button"
            key={image.assetId}
            aria-label={t('imageNumber', { n: index + 1, count: images.length })}
            aria-pressed={active.assetId === image.assetId}
            onClick={() => setSelected(image.assetId)}
            className="rounded-ctl border border-line-2 p-1 aria-pressed:border-accent focus-visible:outline-2"
          >
            <RowThumb
              url={image.url}
              label={t('noImages')}
              retailer={retailer}
              px={72}
              cls="block size-18 rounded-ctl bg-white"
            />
          </button>
        ))}
      </div>
      {url && (
        <a
          href={url}
          target="_blank"
          rel="noopener noreferrer"
          referrerPolicy="no-referrer"
          className="text-sm text-accent underline"
        >
          {t('openImage')}
        </a>
      )}
    </div>
  );
}

function Related({
  title,
  rows,
  onSelect,
}: {
  title: string;
  rows: Schemas['RelatedSku'][];
  onSelect: (sku: string) => void;
}) {
  const t = useTranslations('catalogue');
  if (!rows.length) return null;
  return (
    <div className="space-y-2">
      <h3 className="text-sm font-semibold">{title}</h3>
      <div className="flex flex-wrap gap-2">
        {rows.map((row) => (
          <button
            type="button"
            key={row.sku}
            disabled={!row.resolved}
            onClick={() => onSelect(row.sku)}
            className="rounded-ctl border border-line-2 px-3 py-2 text-sm enabled:hover:border-accent disabled:opacity-60"
          >
            <bdi>{row.selectionLabels.join(' / ') || row.name || row.sku}</bdi>
            <span className="ms-2 text-xs text-ink-2">
              <bdi>{row.sku}</bdi>
              {!row.resolved && ` · ${t('notCaptured')}`}
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}
