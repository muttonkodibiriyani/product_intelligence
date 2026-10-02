import type { ReactNode } from 'react';
import { AsOf } from './as-of';

/**
 * The page's top bar: its title, the one line saying what it answers, the dataset's as-of date
 * with the link to the data, and the page-level tools (tabs, a reset) at the end. The title keeps
 * a floor width, so on a phone the date and tools wrap under it instead of squeezing it.
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
    <div className="mb-5 flex flex-wrap items-end gap-x-6 gap-y-3 border-b border-line pb-4">
      <div className="min-w-0 flex-1 basis-72">
        <h1 id={id} className="text-[17px] leading-6 font-semibold tracking-tight">
          {title}
        </h1>
        {intro && <div className="mt-0.5 max-w-prose text-sm text-ink-2">{intro}</div>}
      </div>
      <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
        <AsOf />
        {tools}
      </div>
    </div>
  );
}
