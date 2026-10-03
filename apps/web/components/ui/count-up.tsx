'use client';

import { useEffect, useRef, useState } from 'react';

/** True when the reader asked the system for less motion; false on the server and in tests. */
export function reducedMotion(): boolean {
  return typeof window !== 'undefined' && !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
}

/**
 * A number that counts up from zero the first time it scrolls into view, 400 ms, easing out; the
 * last frame is `final`, the API's own string, so the figure that stays is never a rounded one.
 * Without an IntersectionObserver (tests), or with reduced motion, the final string renders at once.
 */
export function CountUp({
  to,
  final,
  format,
  duration = 400,
}: {
  /** The value to count to, as a number for the frames only. */
  to: number;
  /** What the figure reads once the count ends: already formatted. */
  final: string;
  /** How an in-between frame reads. */
  format: (v: number) => string;
  duration?: number;
}) {
  const ref = useRef<HTMLSpanElement>(null);
  const fmt = useRef(format);
  useEffect(() => {
    fmt.current = format;
  });
  const [text, setText] = useState<string | null>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof IntersectionObserver === 'undefined' || reducedMotion() || !(to > 0)) {
      setText(final);
      return;
    }
    const format = fmt.current;
    let raf = 0;
    setText(format(0));
    const io = new IntersectionObserver((entries) => {
      if (!entries.some((e) => e.isIntersecting)) return;
      io.disconnect();
      const start = performance.now();
      const frame = (now: number) => {
        const p = Math.min(1, (now - start) / duration);
        const eased = 1 - (1 - p) * (1 - p) * (1 - p);
        if (p < 1) {
          setText(format(to * eased));
          raf = requestAnimationFrame(frame);
        } else setText(final);
      };
      raf = requestAnimationFrame(frame);
    });
    io.observe(el);
    return () => {
      io.disconnect();
      cancelAnimationFrame(raf);
    };
  }, [to, final, duration]);
  // Until the effect runs, the final text is in the HTML: a reader without JS motion still has it.
  return (
    <span ref={ref} className="tabular-nums">
      {text ?? final}
    </span>
  );
}
