import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
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
 * changed source gives new ones. Only files git tracks count, so a clean checkout (CI, the
 * deploy) hashes exactly what a local tree does; tests do not count.
 */
function contentBuildId(): string {
  const files = execFileSync('git', ['ls-files', '-z', '--', ...INPUTS], { encoding: 'utf8' })
    .split('\0')
    .filter((f) => f && !/\.test\.tsx?$/.test(f))
    .sort();
  if (!files.includes('next.config.ts')) throw new Error('build id: run the build inside the git checkout');
  const h = createHash('sha256');
  for (const f of files) h.update(f).update('\0').update(readFileSync(f)).update('\0');
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
