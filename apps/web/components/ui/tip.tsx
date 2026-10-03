'use client';

import { useId, type KeyboardEvent, type ReactNode } from 'react';

/**
 * A tooltip for the exact value, the count behind a bar, or a method note: the one place the
 * Overview keeps its caveats, so the cards themselves carry numbers and not prose. The trigger is
 * in the tab order and the bubble is wired to it with aria-describedby; it shows on hover or
 * focus (app/globals.css `tipwrap`/`tip`) and Escape drops focus to hide it.
 */
export function Tip({
  text,
  at = 'start',
  className = '',
  children,
}: {
  text: ReactNode;
  /** Which edge the bubble hangs from, so one near the end of a card stays on screen. */
  at?: 'start' | 'end';
  className?: string;
  children: ReactNode;
}) {
  const id = useId();
  const onKey = (e: KeyboardEvent<HTMLSpanElement>) => {
    if (e.key === 'Escape') e.currentTarget.blur();
  };
  return (
    <span className={`tipwrap ${className}`}>
      <span
        tabIndex={0}
        aria-describedby={id}
        onKeyDown={onKey}
        // Grows to a full-width wrapper (a strip inside it gets its width), else hugs its content.
        className="min-w-0 grow rounded-[6px] focus-visible:outline-2"
      >
        {children}
      </span>
      <span role="tooltip" id={id} data-at={at} className="tip">
        {text}
      </span>
    </span>
  );
}
