import type { ReactNode } from 'react';
import { useTranslations } from 'next-intl';
import { Skeleton } from './skeleton';

export type CardState = 'ready' | 'loading' | 'empty' | 'preview' | 'error';

const SPAN = {
  3: 'lg:col-span-3',
  4: 'lg:col-span-4',
  6: 'lg:col-span-6',
  8: 'lg:col-span-8',
  12: 'lg:col-span-12',
} as const;

/**
 * A titled panel: the v3 card every table, chart and widget sits in. It draws the title, the one
 * line saying what the card answers, and every state but `ready`, so a widget only renders its
 * body; a preview never shows numbers. `span` places it on a 12-column grid (`CardGrid`); on small screens every card is full width.
 */
export function Card({
  title,
  question,
  meta,
  tools,
  span = 12,
  state = 'ready',
  reason,
  flush = false,
  skeleton = 'lines',
  id,
  children,
}: {
  title: ReactNode;
  question?: ReactNode;
  /** One short line of facts under the question, e.g. the pair count a head-to-head card is on. */
  meta?: ReactNode;
  tools?: ReactNode;
  span?: keyof typeof SPAN;
  state?: CardState;
  /** Why the card is empty, a preview or failed; shown in place of the body. */
  reason?: ReactNode;
  /** Tables run to the card's edges; the header keeps its padding. */
  flush?: boolean;
  /** The shape shown while loading, so the card keeps its size when the data arrives. */
  skeleton?: 'lines' | 'chart' | 'table';
  id?: string;
  children?: ReactNode;
}) {
  const t = useTranslations('card');
  const headingId = id ? `${id}-title` : undefined;
  return (
    <section
      id={id}
      aria-labelledby={headingId}
      aria-busy={state === 'loading' || undefined}
      className={`panel min-w-0 col-span-12 ${SPAN[span]}`}
    >
      <header className="flex flex-wrap items-start gap-x-3 gap-y-2 px-5 pt-4">
        <div className="min-w-0 flex-1">
          <h2 id={headingId} className="text-base font-semibold">
            {title}
          </h2>
          {question && <p className="mt-0.5 text-sm text-ink-2">{question}</p>}
          {meta && <p className="mt-1 text-xs font-medium text-ink-2 tabular-nums">{meta}</p>}
        </div>
        {tools && <div className="flex flex-wrap items-center gap-2">{tools}</div>}
      </header>
      <div className={flush ? 'mt-3 pb-2' : 'px-5 pt-3 pb-5'}>
        {state === 'ready' ? (
          children
        ) : state === 'loading' ? (
          <div className={flush ? 'px-5 pb-3' : ''}>
            <Skeleton kind={skeleton} />
            <p role="status" className="mt-3 text-sm text-ink-2">
              {reason ?? t('loading')}
            </p>
          </div>
        ) : (
          <div className={flush ? 'px-5 pb-3' : ''}>
            <div
              role={state === 'error' ? 'alert' : 'note'}
              className={`rounded-ctl px-4 py-3 text-sm ${
                state === 'preview'
                  ? 'bg-butter text-butter-ink'
                  : state === 'error'
                    ? 'bg-rose'
                    : 'bg-surface-2'
              }`}
            >
              {state === 'preview' && <b className="me-1.5 font-semibold">{t('preview')}</b>}
              {reason ?? (state === 'empty' ? t('empty') : null)}
            </div>
          </div>
        )}
      </div>
    </section>
  );
}

/** The 12-column grid cards sit on. */
export function CardGrid({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <div className={`grid grid-cols-12 gap-5 ${className}`}>{children}</div>;
}
