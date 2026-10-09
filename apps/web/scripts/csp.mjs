// The Next export inlines a few bootstrap scripts in every page (the flight data). CSP
// `script-src 'self'` blocks them unless their hashes are listed, so the Hosting CSP in
// infra/firebase.json carries one 'sha256-…' per distinct inline script of these builds.
//
//   node scripts/csp.mjs --check out out-assistant   fails unless firebase.json lists exactly
//                                                   the union of the builds' hashes
//   node scripts/csp.mjs --write out out-assistant   rewrites the script-src hashes to that union
//   node scripts/csp.mjs --id                        prints the build id this tree gets
//
// `npm run build` checks both exports: out/ (as built, flags off in CI) and out-assistant/ (the
// assistant switched on), so one committed CSP is valid for today's deploy and for switch-on.
// The only host sources script-src may carry are SCRIPT_HOSTS (reCAPTCHA Enterprise for App
// Check). Anything else in the committed directive ('unsafe-inline', another host) fails --check.
//
// The build id is a hash of the sources (next.config.ts), so the same source gives the same
// hashes on any machine, and CI's check after `next build` catches a stale list. That id counts
// only what git tracks, as it is in the working tree, so --write refuses while any build-id input
// is untracked or uncommitted (the list would match that local build and no commit), or the
// exports' build id is not this tree's (a build from before a commit).
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

// The build-id inputs of next.config.ts (csp.test.ts keeps the list and the id below equal to its
// own). infra/firebase.json is not one, so the file --write changes never trips the guards.
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
// CSP_TREE lets csp.test.ts point the guards at a fixture repo; builds use apps/web.
const TREE = process.env.CSP_TREE ?? join(import.meta.dirname, '..');
const git = (...a) => execFileSync('git', a, { cwd: TREE, encoding: 'utf8' });

/** contentBuildId() of next.config.ts: the id a build of this tree, as it is now, gets. */
function treeBuildId() {
    const files = git('ls-files', '-z', '--', ...INPUTS)
        .split('\0')
        .filter((f) => f && !/\.test\.tsx?$/.test(f))
        .sort();
    const h = createHash('sha256');
    for (const f of files)
        h.update(f)
            .update('\0')
            .update(readFileSync(join(TREE, f)))
            .update('\0');
    return h.digest('hex').slice(0, 20);
}

if (mode === '--id') {
    console.log(treeBuildId());
    process.exit(0);
}

if (mode === '--write') {
    // Both checks are needed: the id check below catches untracked inputs (contentBuildId ignores
    // them); this dirty guard catches uncommitted edits to tracked inputs (both ids read the working
    // tree and agree). Removing either reopens one hole. -z keeps non-ASCII paths unquoted.
    const dirty = git('status', '--porcelain', '-z', '--untracked-files=all', '--', ...INPUTS)
        .split('\0')
        .filter((l) => /^.. /.test(l) && !/\.test\.tsx?$/.test(l));
    if (dirty.length > 0) {
        console.error(
            `csp: not writing: these build-id inputs are not committed, so this build's id is one no commit gives.\n` +
                `Commit (or remove) them, rebuild, then run csp:write again.\n${dirty.join('\n')}`,
        );
        process.exit(1);
    }
}

// The hashes belong to one build id (the inline scripts carry it), read from each export's
// _next/static/<id>/. Every mode needs the exports to agree on it, which needs no git, so --check
// still runs on a deploy checkout with no git (docs/runbooks/assistant-enablement.md). --write must
// also match this tree's id: an export built before a commit, or elsewhere, has hashes CI's build
// will not reproduce.
const builtAs = (dir) => {
    const st = join(dir, '_next', 'static');
    try {
        return readdirSync(st).filter((n) => {
            try {
                return statSync(join(st, n, '_buildManifest.js')).isFile();
            } catch {
                return false;
            }
        });
    } catch {
        return [];
    }
};
const built = dirs.map((dir) => ({ dir, ids: builtAs(dir) }));
const bad = built.find((b) => b.ids.length !== 1);
const fail = (msg) => {
    console.error(`csp: ${msg} Rebuild (npm run build) first.`);
    process.exit(1);
};
if (bad) fail(`${bad.dir} has ${bad.ids.length === 0 ? 'no build id' : `build ids ${bad.ids.join(', ')}`}.`);
const buildId = built[0].ids[0];
const other = built.find((b) => b.ids[0] !== buildId);
if (other) fail(`${built[0].dir} was built as ${buildId} but ${other.dir} as ${other.ids[0]}.`);
if (mode === '--write') {
    // Not redundant with the dirty guard above; see the note there.
    const treeId = treeBuildId();
    if (treeId !== buildId)
        fail(`${dirs.join(', ')} were built as ${buildId}, but this tree builds as ${treeId}.`);
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
