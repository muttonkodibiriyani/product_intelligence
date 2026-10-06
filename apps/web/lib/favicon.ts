import type { Metadata } from 'next';

/**
 * The favicon, as plain files in public/ under the basePath. Not the app/icon.* convention: that
 * route puts a build-made hash in every page's inline script, which moved the CSP hashes on CI.
 */
export const icons: Metadata['icons'] = [
  { rel: 'icon', url: '/app/icon.svg', type: 'image/svg+xml' },
  { rel: 'icon', url: '/app/icon.png', type: 'image/png', sizes: '32x32' },
];
