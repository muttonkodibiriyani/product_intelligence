'use client';

import { useTranslations } from 'next-intl';
import { useEffect, useId, useRef, useState } from 'react';
import { ApiError } from '@/lib/api/client';
import type { CompareState } from '@/lib/compare';
import { saveFile } from '@/lib/save-file';
import { useAuth } from '../auth-provider';
import { errorText } from '../error-notice';

type Status =
  | { kind: 'idle' }
  | { kind: 'working' }
  | { kind: 'saved'; filename: string }
  | { kind: 'busy'; seconds: number }
  | { kind: 'failed'; error: unknown };

/**
 * Downloads the comparison for the current pair and filters as CSV through /export/compare, with
 * the Bearer token (a link can't carry it). The API runs two exports at a time; a refusal says
 * when to try again.
 */
export function ExportMatched({ state, n }: { state: CompareState; n: string }) {
  const t = useTranslations('compare.export');
  const te = useTranslations('errors');
  const { api } = useAuth();
  const [status, setStatus] = useState<Status>({ kind: 'idle' });
  const abort = useRef<AbortController | null>(null);
  const statusId = useId();

  useEffect(() => () => abort.current?.abort(), []);

  useEffect(() => {
    if (status.kind !== 'busy') return;
    const id = setTimeout(
      () => setStatus(status.seconds <= 1 ? { kind: 'idle' } : { kind: 'busy', seconds: status.seconds - 1 }),
      1000,
    );
    return () => clearTimeout(id);
  }, [status]);

  async function run() {
    if (!api) return;
    abort.current?.abort();
    const ctl = new AbortController();
    abort.current = ctl;
    setStatus({ kind: 'working' });
    try {
      const { blob, filename } = await api.download('/api/v1/export/compare', {
        query: {
          format: 'csv',
          retailers: `${state.base},${state.other}`,
          ...(state.brand.length ? { brand: state.brand } : {}),
          ...(state.category.length ? { category: state.category } : {}),
        },
        signal: ctl.signal,
        fallback: `pi-compare-${state.base}-${state.other}.csv`,
      });
      if (ctl.signal.aborted) return;
      saveFile(blob, filename);
      setStatus({ kind: 'saved', filename });
    } catch (e) {
      if (ctl.signal.aborted) return;
      if (e instanceof ApiError && e.code === 'rate_limited')
        setStatus({ kind: 'busy', seconds: Math.min(e.retryAfter ?? 5, 60) });
      else setStatus({ kind: 'failed', error: e });
    }
  }

  const message =
    status.kind === 'working'
      ? t('preparing')
      : status.kind === 'saved'
        ? t('saved', { filename: status.filename })
        : status.kind === 'busy'
          ? t('busy', { seconds: status.seconds })
          : status.kind === 'failed'
            ? errorText(te, status.error)
            : null;

  return (
    <span className="inline-flex flex-wrap items-center gap-x-2 gap-y-1">
      <button
        type="button"
        disabled={!api || status.kind === 'working' || status.kind === 'busy'}
        title={t('title', { n })}
        aria-describedby={message ? statusId : undefined}
        onClick={() => void run()}
        className="btn py-1.5 text-sm focus-visible:outline-2"
      >
        {t('label')}
      </button>
      <span
        id={statusId}
        role="status"
        className={`text-xs ${status.kind === 'failed' ? 'text-danger' : 'text-ink-2'}`}
      >
        {message}
      </span>
    </span>
  );
}
