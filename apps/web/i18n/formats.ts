import type { Formats } from 'next-intl';

/**
 * Named formats for messages. `latn` keeps Latin digits in Arabic counts ("{n, number, latn}"), as
 * every other number in the app does: WebKit's ICU defaults `ar` to Arabic-Indic digits, so a bare
 * plural `#` there read "٦" next to "6" in the tables.
 */
export const formats = {
  number: { latn: { numberingSystem: 'latn' } },
} satisfies Formats;
