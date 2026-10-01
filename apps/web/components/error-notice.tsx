'use client';

import { useTranslations } from 'next-intl';
import { ApiError } from '@/lib/api/client';
import type { ApiErrorCode } from '@/lib/api/types';

/** Text for a failed call, chosen from its code alone; nothing from the server is shown. */
export function errorText(t: (key: string, values?: Record<string, number>) => string, e: unknown): string {
  const code: ApiErrorCode = e instanceof ApiError ? e.code : 'unexpected';
  const seconds = e instanceof ApiError && e.retryAfter ? e.retryAfter : code === 'data_unavailable' ? 30 : 5;
  return t(code, { seconds });
}

export function ErrorNotice({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const t = useTranslations('errors');
  return (
    <div
      role="alert"
      className="flex flex-wrap items-center gap-3 rounded border border-line bg-surface-2 px-4 py-3 text-sm"
    >
      <span className="text-ink">{errorText(t, error)}</span>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="rounded border border-line px-2 py-1 hover:bg-surface focus-visible:outline-2"
        >
          {t('retry')}
        </button>
      )}
    </div>
  );
}
