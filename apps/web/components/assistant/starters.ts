/** The three starter questions on the opening screen; the text lives in `assistant.q.*`. */
export const STARTERS = ['exclusive', 'unit', 'coverage'] as const;
export type Starter = (typeof STARTERS)[number];
