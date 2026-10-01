import type { ReactNode } from 'react';

/**
 * A page's title, the one line saying what it answers, and its page-level tools (tabs, a reset).
 * `id` labels the page's section, so the heading names the landmark.
 */
export function PageHeader({
  id,
  title,
  intro,
  tools,
}: {
  id?: string;
  title: ReactNode;
  intro?: ReactNode;
  tools?: ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-end gap-x-6 gap-y-3">
      <div className="min-w-0 flex-1">
        <h1 id={id} className="text-2xl font-bold tracking-tight">
          {title}
        </h1>
        {intro && <div className="mt-1 max-w-prose text-sm text-ink-2">{intro}</div>}
      </div>
      {tools}
    </div>
  );
}
