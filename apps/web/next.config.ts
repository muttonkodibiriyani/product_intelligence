import { createHash } from 'node:crypto';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';
import type { NextConfig } from 'next';
import createNextIntlPlugin from 'next-intl/plugin';

/** Served under this path on Firebase Hosting; the legacy dashboard keeps `/`. */
export const BASE_PATH = '/app';

const INPUTS = [
  'app',
  'components',
  'i18n',
  'lib',
  'messages',
  'public',
  'next.config.ts',
  'package-lock.json',
];

/**
 * A build id from the inputs' content, not a random one: the inline scripts carry it, so the same
 * source always gives the same script hashes (the CSP in infra/firebase.json lists them), and a
 * changed source gives new ones.
 */
function contentBuildId(): string {
  const h = createHash('sha256');
  const walk = (p: string): void => {
    if (statSync(p).isDirectory()) {
      for (const name of readdirSync(p).sort()) if (!/\.test\.tsx?$/.test(name)) walk(join(p, name));
    } else h.update(p).update('\0').update(readFileSync(p)).update('\0');
  };
  for (const input of INPUTS) walk(input);
  return h.digest('hex').slice(0, 20);
}

// Static export for Firebase Hosting: no server, no middleware. Data comes from /api/v1 (Cloud Run
// behind the Hosting rewrite) and auth is client-side Firebase Auth with Bearer tokens.
const config: NextConfig = {
  output: 'export',
  basePath: BASE_PATH,
  generateBuildId: contentBuildId,
  trailingSlash: true,
  images: { unoptimized: true },
  poweredByHeader: false,
  reactStrictMode: true,
};

export default createNextIntlPlugin('./i18n/request.ts')(config);
