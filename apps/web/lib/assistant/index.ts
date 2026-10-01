/**
 * Ryzan AI Assistant page state (design doc docs/design/ai-assistant.md §11).
 *
 * Until the owner switches the assistant on, the page shows the "Connect to enable" state and
 * never sends a question. It turns on only when the build sets both
 * NEXT_PUBLIC_ASSISTANT_ENABLED=true and the reCAPTCHA Enterprise site id for App Check (the
 * callable refuses calls without an App Check token). Even then the server's config decides:
 * while it is off, every question gets the "switched off" note and no answer.
 */
export const RECAPTCHA_SITE = process.env.NEXT_PUBLIC_RECAPTCHA_SITE ?? '';
export const ASSISTANT_CONNECTED =
  process.env.NEXT_PUBLIC_ASSISTANT_ENABLED === 'true' && RECAPTCHA_SITE !== '';

/**
 * Suggested questions, each answerable by one of the read-only tools (the tool in the comment).
 * They are examples only: the page labels them "Sample — not live data".
 */
export const SUGGESTED = [
  'gaps', // compare
  'promo', // promotions
  'exclusive', // assortment_gaps
  'index', // index_trend
  'unit', // search_products
  'launches', // launches
  'coverage', // coverage_status
] as const;

export type Suggested = (typeof SUGGESTED)[number];
