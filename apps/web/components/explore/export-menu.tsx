'use client';

import { useTranslations } from 'next-intl';
import { useEffect, useId, useRef, useState } from 'react';
import { ApiError, type ExportPath } from '@/lib/api/client';
import type { QueryOf } from '@/lib/api/types';
import { EXPORT_MAX_ROWS } from '@/lib/explore';
import { saveFile } from '@/lib/save-file';
import { useAuth } from '../auth-provider';
import { errorText } from '../error-notice';

type Format = 'csv' | 'jsonl';
type Status =
  | { kind: 'idle' }
  | { kind: 'working'; format: Format }
  | { kind: 'saved'; filename: string }
  | { kind: 'busy'; seconds: number }
  | { kind: 'failed'; error: unknown };

/**
 * Downloads every row that matches a list's filters, in the list's order, as CSV or JSONL: the
 * products (`/api/v1/export/products`) or the promotions. The file is fetched with the Bearer
 * token (an export link can't carry it), then saved. The API caps exports at 50 000 rows and
 * runs two at a time per instance; both refusals say what to do.
 */
export function ExportMenu<P extends ExportPath>({
  path,
  query,
  fallback,
  total,
  n,
}: {
  path: P;
  /** The list's filters as the export endpoint takes them, in the format asked for. */
  query: (format: Format) => QueryOf<P> & { format: Format };
  /** The file name's stem when the response names none: "pi-products". */
  fallback: string;
  total: number;
  n: string;
}) {
  const t = useTranslations('explore.export');
  const te = useTranslations('errors');
  const { api } = useAuth();
  const [status, setStatus] = useState<Status>({ kind: 'idle' });
  const abort = useRef<AbortController | null>(null);
  const statusId = useId();

  useEffect(() => () => abort.current?.abort(), []);

  // While the API is busy, count down and then offer the buttons again.
  useEffect(() => {
    if (status.kind !== 'busy') return;
    const id = setTimeout(
      () => setStatus(status.seconds <= 1 ? { kind: 'idle' } : { kind: 'busy', seconds: status.seconds - 1 }),
      1000,
    );
    return () => clearTimeout(id);
  }, [status]);

  const overCap = total > EXPORT_MAX_ROWS;
  const disabled = !api || total === 0 || overCap || status.kind === 'working' || status.kind === 'busy';

  async function run(format: Format) {
    if (!api) return;
    abort.current?.abort();
    const ctl = new AbortController();
    abort.current = ctl;
    setStatus({ kind: 'working', format });
    try {
      const { blob, filename } = await api.download(path, {
        query: query(format),
        signal: ctl.signal,
        fallback: `${fallback}.${format}`,
      });
      if (ctl.signal.aborted) return;
      saveFile(blob, filename);
      setStatus({ kind: 'saved', filename });
    } catch (e) {
      if (ctl.signal.aborted) return;
      if (e instanceof ApiError && e.code === 'rate_limited') {
        setStatus({ kind: 'busy', seconds: Math.min(e.retryAfter ?? 5, 60) });
      } else setStatus({ kind: 'failed', error: e });
    }
  }

  const button =
    'rounded-lg px-2.5 py-1 text-sm hover:bg-surface focus-visible:outline-2 disabled:cursor-not-allowed disabled:text-ink-2 disabled:hover:bg-transparent';
  const message =
    total === 0
      ? null
      : overCap
        ? t('overCap')
        : status.kind === 'working'
          ? t('preparing')
          : status.kind === 'saved'
            ? t('saved', { filename: status.filename })
            : status.kind === 'busy'
              ? t('busy', { seconds: status.seconds })
              : status.kind === 'failed'
                ? errorText(te, status.error)
                : null;

  return (
    <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
      <div
        role="group"
        aria-label={t('label')}
        className="flex items-center gap-1 rounded-ctl bg-surface-2 p-0.5 ps-2.5"
      >
        <span className="text-xs text-ink-2" aria-hidden>
          {t('label')}
        </span>
        {(['csv', 'jsonl'] as const).map((f) => (
          <button
            key={f}
            type="button"
            disabled={disabled}
            aria-label={t(f === 'csv' ? 'csvTitle' : 'jsonlTitle', { n })}
            aria-describedby={overCap ? statusId : undefined}
            onClick={() => void run(f)}
            className={button}
          >
            {t(f)}
          </button>
        ))}
      </div>
      <p
        id={statusId}
        role="status"
        className={`text-xs ${status.kind === 'failed' || overCap ? 'text-danger' : 'text-ink-2'}`}
      >
        {message}
      </p>
    </div>
  );
}
