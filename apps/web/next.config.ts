import type { NextConfig } from 'next';
import createNextIntlPlugin from 'next-intl/plugin';

// Static export for Firebase Hosting: no server, no middleware. Data comes from /api/v1 (Cloud Run
// behind the Hosting rewrite) and auth is client-side Firebase Auth with Bearer tokens.
const config: NextConfig = {
  output: 'export',
  trailingSlash: true,
  images: { unoptimized: true },
  poweredByHeader: false,
  reactStrictMode: true,
};

export default createNextIntlPlugin('./i18n/request.ts')(config);
