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
// Host sources in script-src (the reCAPTCHA hosts) are kept as they are; only hashes change.
//
// The build id is a hash of the sources (next.config.ts), so the same source gives the same
// hashes on any machine, and CI's check after `next build` catches a stale list.
import { createHash } from 'node:crypto';
import { readdirSync, readFileSync, statSync, writeFileSync } from 'node:fs';
import { join, relative } from 'node:path';

const args = process.argv.slice(2);
const mode = args.find((a) => a.startsWith('--')) ?? '--check';
const dirs = args.filter((a) => !a.startsWith('--'));
if (dirs.length === 0) dirs.push('out');
const CONFIG = join(import.meta.dirname, '..', '..', '..', 'infra', 'firebase.json');

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
const hosts = have
    .split(' ')
    .slice(1)
    .filter((s) => s !== "'self'" && !s.startsWith("'sha256-"));
const want = ['script-src', "'self'", ...hosts, ...[...hashes].sort()].join(' ');

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
