import type { ReactNode } from 'react';

// Ragged line lengths read as text; classes, not inline styles, so the static HTML stays CSP-clean.
const WIDTHS = ['w-[90%]', 'w-[70%]', 'w-[82%]', 'w-[55%]'] as const;

/**
 * The shape of what is loading, so the page does not jump when it arrives. Decorative only: the
 * caller says "loading" in words (Card does, with role=status). The shimmer runs only when the
 * reader has not asked for reduced motion, and follows the reading direction.
 */
export function Skeleton({
  kind = 'lines',
  rows = 3,
}: {
  kind?: 'lines' | 'chart' | 'table' | 'kpi';
  rows?: number;
}) {
  const bar = 'skeleton block rounded-[5px]';
  if (kind === 'kpi')
    return (
      <span aria-hidden className="grid gap-2">
        <span className={`${bar} h-3 w-2/5`} />
        <span className={`${bar} h-6 w-3/5`} />
      </span>
    );
  if (kind === 'chart')
    return (
      <span aria-hidden className="grid gap-3">
        <span className={`${bar} h-3 w-1/3`} />
        <span className={`${bar} h-48 w-full`} />
      </span>
    );
  if (kind === 'table')
    return (
      <span aria-hidden className="grid gap-2.5">
        {Array.from({ length: rows }, (_, i) => (
          <span key={i} className="flex items-center gap-3">
            <span className={`${bar} size-10 shrink-0`} />
            <span className={`${bar} h-3 flex-1`} />
            <span className={`${bar} h-3 w-16`} />
          </span>
        ))}
      </span>
    );
  return (
    <span aria-hidden className="grid gap-2.5">
      {Array.from({ length: rows }, (_, i) => (
        <span key={i} className={`${bar} h-3 ${WIDTHS[i % WIDTHS.length]}`} />
      ))}
    </span>
  );
}

/** A page-level loading state: the shape of what is coming, and the words saying so. */
export function Loading({
  kind = 'lines',
  rows,
  children,
}: {
  kind?: 'lines' | 'chart' | 'table';
  rows?: number;
  children: ReactNode;
}) {
  return (
    <div aria-busy className="panel px-5 py-4">
      <Skeleton kind={kind} rows={rows} />
      <p role="status" className="mt-3 text-sm text-ink-2">
        {children}
      </p>
    </div>
  );
}
