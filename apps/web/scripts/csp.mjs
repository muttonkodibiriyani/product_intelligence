// The Next export inlines a few bootstrap scripts in every page (the flight data). CSP
// `script-src 'self'` blocks them unless their hashes are listed, so the Hosting CSP in
// infra/firebase.json carries one 'sha256-…' per distinct inline script of these builds.
//
//   node scripts/csp.mjs --check out out-assistant   fails unless firebase.json lists exactly
//                                                   the union of the builds' hashes
//   node scripts/csp.mjs --write out out-assistant   rewrites the script-src hashes to that union
//
// `npm run build` checks both exports: out/ (as built, flags off in CI) and out-assistant/ (the
// assistant switched on), so one committed CSP is valid for today's deploy and for switch-on.
// The only host sources script-src may carry are SCRIPT_HOSTS (reCAPTCHA Enterprise for App
// Check). Anything else in the committed directive ('unsafe-inline', another host) fails --check.
//
// The build id is a hash of the sources (next.config.ts), so the same source gives the same
// hashes on any machine, and CI's check after `next build` catches a stale list. That id counts
// only what git tracks, as it is in the working tree, so --write refuses while any build-id input
// is untracked or uncommitted: the list it wrote would match that local build and no commit.
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { readdirSync, readFileSync, statSync, writeFileSync } from 'node:fs';
import { join, relative } from 'node:path';

const SCRIPT_HOSTS = ['https://www.google.com/recaptcha/', 'https://www.gstatic.com/recaptcha/'];

const args = process.argv.slice(2);
const mode = args.find((a) => a.startsWith('--')) ?? '--check';
const dirs = args.filter((a) => !a.startsWith('--'));
if (dirs.length === 0) dirs.push('out');
// CSP_CONFIG lets scripts/csp.test.ts point the check at a fixture; builds use the real file.
const CONFIG =
    process.env.CSP_CONFIG ?? join(import.meta.dirname, '..', '..', '..', 'infra', 'firebase.json');

// The build-id inputs of next.config.ts (csp.test.ts keeps the two lists equal). infra/firebase.json
// is not one, so the file --write changes never trips its own guard.
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
if (mode === '--write') {
    // CSP_TREE lets csp.test.ts point the guard at a fixture repo; builds use apps/web.
    const tree = process.env.CSP_TREE ?? join(import.meta.dirname, '..');
    const dirty = execFileSync('git', ['status', '--porcelain', '--untracked-files=all', '--', ...INPUTS], {
        cwd: tree,
        encoding: 'utf8',
    })
        .split('\n')
        .filter((l) => l && !/\.test\.tsx?$/.test(l));
    if (dirty.length > 0) {
        console.error(
            `csp: not writing: these build-id inputs are not committed, so this build's id is one no commit gives.\n` +
                `Commit (or remove) them, rebuild, then run csp:write again.\n${dirty.join('\n')}`,
        );
        process.exit(1);
    }
}

const hashes = new Set();
let inline = 0;
const walk = (dir, p) => {
    if (statSync(p).isDirectory()) return readdirSync(p).forEach((n) => walk(dir, join(p, n)));
    if (!p.endsWith('.html')) return;
    for (const m of readFileSync(p, 'utf8').matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/gi)) {
        if (/\ssrc=/i.test(m[1])) continue;
        if (/\son[a-z]+=/i.test(m[1])) throw new Error(`inline event handler in ${relative(dir, p)}`);
        inline++;
        hashes.add(`'sha256-${createHash('sha256').update(m[2], 'utf8').digest('base64')}'`);
    }
};
for (const dir of dirs) walk(dir, dir);

const config = JSON.parse(readFileSync(CONFIG, 'utf8'));
const csp = config.hosting.headers.flatMap((h) => h.headers).find((h) => h.key === 'Content-Security-Policy');
if (!csp) throw new Error('no Content-Security-Policy header in infra/firebase.json');
const have = csp.value.split(/;\s*/).find((d) => d.startsWith('script-src ')) ?? '';
const want = ['script-src', "'self'", ...SCRIPT_HOSTS, ...[...hashes].sort()].join(' ');

if (have === want) {
    console.log(
        `csp: ${hashes.size} inline script hashes (${inline} inline scripts in ${dirs.join(', ')}) match infra/firebase.json`,
    );
} else if (mode === '--write') {
    csp.value = csp.value
        .split(/;\s*/)
        .map((d) => (d.startsWith('script-src ') ? want : d))
        .join('; ');
    writeFileSync(CONFIG, `${JSON.stringify(config, null, 2)}\n`);
    console.log(`csp: wrote ${hashes.size} inline script hashes to infra/firebase.json`);
} else {
    console.error(
        'csp: infra/firebase.json script-src does not match these builds. Run `npm run csp:write`.',
    );
    process.exit(1);
}
