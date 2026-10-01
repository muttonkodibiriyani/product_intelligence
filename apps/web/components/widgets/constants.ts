/** How many brands the brand charts draw; /summary sends the top 30. */
export const BRANDS_TOP = 15;
export const SHARE_TOP = 10;
/**
 * The fewest comparable pairs a head-to-head cell may be computed from: the API's own cohort
 * minimum (a /index point with n < 5 is null; a /compare group under it is `cohort_too_small`).
 */
export const MIN_PAIRS = 5;
/** The grid the category × brand heatmap keeps legible: the busiest rows and columns by pairs. */
export const CROSS_ROWS = 12;
export const CROSS_COLS = 8;
