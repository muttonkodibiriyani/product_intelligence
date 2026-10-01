/**
 * Ryzan AI Assistant page state (design doc docs/design/ai-assistant.md §11).
 *
 * The chat callable is not deployed and the model is not enabled, so the page shows the
 * "Connect to enable" state and never sends a question. This flips only when the callable client
 * (with App Check) is wired in; nothing here calls a model or shows a generated answer.
 */
export const ASSISTANT_CONNECTED = false;

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
