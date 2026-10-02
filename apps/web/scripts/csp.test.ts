// @vitest-environment node
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { afterAll, describe, expect, it } from 'vitest';

// Fixtures live under node_modules/.cache (git-ignored), not the shared system temp dir.
const cache = join(import.meta.dirname, '..', 'node_modules', '.cache');
mkdirSync(cache, { recursive: true });
const root = mkdtempSync(join(cache, 'csp-test-'));
afterAll(() => rmSync(root, { recursive: true, force: true }));

const SCRIPT = 'self.__next_f.push([1,"x"])';
const HASH = `'sha256-${createHash('sha256').update(SCRIPT, 'utf8').digest('base64')}'`;
const HOSTS = 'https://www.google.com/recaptcha/ https://www.gstatic.com/recaptcha/';
const out = join(root, 'out');
mkdirSync(out);
writeFileSync(
  join(out, 'index.html'),
  `<html><script>${SCRIPT}</script><script src="/a.js"></script></html>`,
);

function run(mode: '--check' | '--write', scriptSrc: string) {
  const config = join(root, `firebase-${Math.random().toString(36).slice(2)}.json`);
  const value = `default-src 'self'; script-src ${scriptSrc}; base-uri 'none'`;
  writeFileSync(
    config,
    JSON.stringify({ hosting: { headers: [{ headers: [{ key: 'Content-Security-Policy', value }] }] } }),
  );
  let status = 0;
  try {
    execFileSync(process.execPath, [join(import.meta.dirname, 'csp.mjs'), mode, out], {
      env: { ...process.env, CSP_CONFIG: config },
      stdio: 'pipe',
    });
  } catch (e) {
    status = (e as { status: number }).status;
  }
  const written = JSON.parse(readFileSync(config, 'utf8')) as {
    hosting: { headers: { headers: { value: string }[] }[] };
  };
  return { status, value: written.hosting.headers[0]?.headers[0]?.value ?? '' };
}

describe('csp.mjs', () => {
  it('passes only the exact directive: self, the pinned reCAPTCHA hosts, the build hashes', () => {
    expect(run('--check', `'self' ${HOSTS} ${HASH}`).status).toBe(0);
  });

  it('fails a weakened script-src (the review probe), even with the right hashes', () => {
    for (const extra of ["'unsafe-inline'", "'unsafe-eval'", 'https://evil.example/']) {
      expect(run('--check', `'self' ${HOSTS} ${extra} ${HASH}`).status).toBe(1);
    }
  });

  it('fails a stale hash list or a missing reCAPTCHA host', () => {
    expect(run('--check', `'self' ${HOSTS}`).status).toBe(1);
    expect(run('--check', `'self' https://www.google.com/recaptcha/ ${HASH}`).status).toBe(1);
  });

  it('--write replaces any extra source with the pinned directive', () => {
    const { status, value } = run('--write', `'self' 'unsafe-inline' https://evil.example/`);
    expect(status).toBe(0);
    expect(value).toBe(`default-src 'self'; script-src 'self' ${HOSTS} ${HASH}; base-uri 'none'`);
  });
});
