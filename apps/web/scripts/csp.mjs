// The Next export inlines a few bootstrap scripts in every page (the flight data). CSP
// `script-src 'self'` blocks them unless their hashes are listed, so the Hosting CSP in
// infra/firebase.json carries one 'sha256-…' per distinct inline script of this build.
//
//   node scripts/csp.mjs out --check   fails when firebase.json doesn't list exactly these hashes
//   node scripts/csp.mjs out --write   rewrites the script-src directive to list them
//
// The build id is a hash of the sources (next.config.ts), so the same source gives the same
// hashes on any machine, and CI's check after `next build` catches a stale list.
import { createHash } from 'node:crypto';
import { readdirSync, readFileSync, statSync, writeFileSync } from 'node:fs';
import { join, relative } from 'node:path';

const [dir = 'out', mode = '--check'] = process.argv.slice(2);
const CONFIG = join(import.meta.dirname, '..', '..', '..', 'infra', 'firebase.json');

const hashes = new Set();
let inline = 0;
const walk = (p) => {
    if (statSync(p).isDirectory()) return readdirSync(p).forEach((n) => walk(join(p, n)));
    if (!p.endsWith('.html')) return;
    for (const m of readFileSync(p, 'utf8').matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/gi)) {
        if (/\ssrc=/i.test(m[1])) continue;
        if (/\son[a-z]+=/i.test(m[1])) throw new Error(`inline event handler in ${relative(dir, p)}`);
        inline++;
        hashes.add(`'sha256-${createHash('sha256').update(m[2], 'utf8').digest('base64')}'`);
    }
};
walk(dir);
const want = `script-src 'self' ${[...hashes].sort().join(' ')}`;

const config = JSON.parse(readFileSync(CONFIG, 'utf8'));
const csp = config.hosting.headers.flatMap((h) => h.headers).find((h) => h.key === 'Content-Security-Policy');
if (!csp) throw new Error('no Content-Security-Policy header in infra/firebase.json');
const have = csp.value.split(/;\s*/).find((d) => d.startsWith('script-src ')) ?? '';

if (have === want) {
    console.log(
        `csp: ${hashes.size} inline script hashes (${inline} inline scripts) match infra/firebase.json`,
    );
} else if (mode === '--write') {
    csp.value = csp.value
        .split(/;\s*/)
        .map((d) => (d.startsWith('script-src ') ? want : d))
        .join('; ');
    writeFileSync(CONFIG, `${JSON.stringify(config, null, 2)}\n`);
    console.log(`csp: wrote ${hashes.size} inline script hashes to infra/firebase.json`);
} else {
    console.error('csp: infra/firebase.json script-src does not match this build. Run `npm run csp:write`.');
    process.exit(1);
}
