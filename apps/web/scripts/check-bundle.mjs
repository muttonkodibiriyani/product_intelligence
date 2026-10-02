// Fails when the static export carries anything that looks like a secret. The Firebase web config is
// not in the build at all (it is fetched from /__/firebase/init.json at runtime), so even a Google
// API key pattern is an error here, as is any search-service key.
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { extname, join } from 'node:path';

const root = process.argv[2] ?? 'out';
// Only text the browser reads as code or markup; images and fonts can't carry a usable key.
const TEXT = new Set(['.html', '.js', '.mjs', '.css', '.json', '.txt', '.map', '.xml', '.webmanifest']);
const patterns = [
    [/AIza[0-9A-Za-z_-]{20,}/, 'Google API key'],
    [/algolia/i, 'Algolia reference'],
    [/-----BEGIN [A-Z ]*PRIVATE KEY-----/, 'private key'],
    [/"private_key_id"/, 'service-account key'],
    [/NEXT_PUBLIC_[A-Z0-9_]*(KEY|SECRET|TOKEN)/, 'secret-like public env var'],
];

const bad = [];
const walk = (dir) => {
    for (const name of readdirSync(dir)) {
        const p = join(dir, name);
        if (statSync(p).isDirectory()) walk(p);
        else if (TEXT.has(extname(name).toLowerCase())) {
            const text = readFileSync(p, 'utf8');
            for (const [re, what] of patterns) if (re.test(text)) bad.push(`${p}: ${what}`);
        }
    }
};
walk(root);
if (bad.length) {
    console.error(bad.join('\n'));
    process.exit(1);
}
console.log(`${root}: no secret-like strings`);
