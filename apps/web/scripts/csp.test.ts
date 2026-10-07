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

// A git repo standing in for apps/web, so the --write guard never reads the real working tree.
const git = (cwd: string, ...a: string[]) => execFileSync('git', a, { cwd, stdio: 'pipe' });
function repo() {
  const dir = mkdtempSync(join(root, 'tree-'));
  git(dir, 'init', '-q');
  mkdirSync(join(dir, 'components'));
  writeFileSync(join(dir, 'next.config.ts'), 'export default {};\n');
  writeFileSync(join(dir, 'components', 'a.tsx'), 'export const a = 1;\n');
  git(dir, 'add', '.');
  git(dir, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-qm', 'base');
  return dir;
}
const clean = repo();

function run(mode: '--check' | '--write', scriptSrc: string, tree = clean) {
  const config = join(root, `firebase-${Math.random().toString(36).slice(2)}.json`);
  const value = `default-src 'self'; script-src ${scriptSrc}; base-uri 'none'`;
  writeFileSync(
    config,
    JSON.stringify({ hosting: { headers: [{ headers: [{ key: 'Content-Security-Policy', value }] }] } }),
  );
  let status = 0;
  let stderr = '';
  try {
    execFileSync(process.execPath, [join(import.meta.dirname, 'csp.mjs'), mode, out], {
      env: { ...process.env, CSP_CONFIG: config, CSP_TREE: tree },
      stdio: 'pipe',
    });
  } catch (e) {
    ({ status } = e as { status: number });
    stderr = String((e as { stderr: Buffer }).stderr);
  }
  const written = JSON.parse(readFileSync(config, 'utf8')) as {
    hosting: { headers: { headers: { value: string }[] }[] };
  };
  return { status, stderr, value: written.hosting.headers[0]?.headers[0]?.value ?? '' };
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

  // #282: the hashes were written while three new inputs were untracked, so the local build id
  // hashed 151 files where the commit has 154, and the list matched a build no commit gives.
  it('--write refuses while a build-id input is untracked, edited or staged, and names it', () => {
    const stale = `'self' ${HOSTS}`;
    const untracked = repo();
    writeFileSync(join(untracked, 'components', 'new.tsx'), 'export const n = 1;\n');
    const edited = repo();
    writeFileSync(join(edited, 'next.config.ts'), 'export default { x: 1 };\n');
    const staged = repo();
    writeFileSync(join(staged, 'components', 'b.tsx'), 'export const b = 1;\n');
    git(staged, 'add', '.');
    for (const [tree, file] of [
      [untracked, 'components/new.tsx'],
      [edited, 'next.config.ts'],
      [staged, 'components/b.tsx'],
    ]) {
      const { status, stderr, value } = run('--write', stale, tree);
      expect(status).toBe(1);
      expect(stderr).toContain(file);
      expect(value).toBe(`default-src 'self'; script-src ${stale}; base-uri 'none'`);
    }
  });

  it('--write ignores what is not a build-id input: tests, e2e, other folders', () => {
    const tree = repo();
    writeFileSync(join(tree, 'components', 'a.test.tsx'), '\n');
    mkdirSync(join(tree, 'e2e'));
    writeFileSync(join(tree, 'e2e', 'x.spec.ts'), '\n');
    expect(run('--write', `'self' ${HOSTS}`, tree).status).toBe(0);
  });

  it('guards the same inputs next.config.ts hashes into the build id', () => {
    const list = (f: string, re: RegExp) =>
      [
        ...(readFileSync(join(import.meta.dirname, f), 'utf8').match(re)?.[1] ?? '').matchAll(/'([^']+)'/g),
      ].map((m) => m[1]);
    const config = list('../next.config.ts', /const INPUTS = \[([^\]]*)\]/);
    expect(config).toContain('next.config.ts');
    expect(list('csp.mjs', /const INPUTS = \[([^\]]*)\]/)).toEqual(config);
  });
});
