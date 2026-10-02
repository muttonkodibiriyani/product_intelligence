'use client';

import { useEffect, useState } from 'react';

/** Delay between revealed sections of a verified answer. */
export const REVEAL_STEP_MS = 140;

const reducedMotion = (): boolean =>
  typeof window !== 'undefined' &&
  typeof window.matchMedia === 'function' &&
  window.matchMedia('(prefers-reduced-motion: reduce)').matches;

/**
 * Progressive reveal of an already verified answer, one section at a time (never mid-number).
 * Shows everything at once under prefers-reduced-motion, and `skip()` does the same.
 */
export function useReveal(total: number, key: string): { shown: number; skip: () => void } {
  const [state, setState] = useState({ key, shown: reducedMotion() ? total : 0 });
  const shown = state.key === key ? state.shown : reducedMotion() ? total : 0;

  useEffect(() => {
    if (shown >= total) return;
    const timer = setTimeout(() => setState({ key, shown: shown + 1 }), REVEAL_STEP_MS);
    return () => clearTimeout(timer);
  }, [key, shown, total]);

  return { shown: Math.min(shown, total), skip: () => setState({ key, shown: total }) };
}
