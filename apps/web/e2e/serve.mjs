// Serves the static export the way Firebase Hosting does (cleanUrls off, trailing slashes on),
// under /app as deployed, with no Firebase config: each test supplies /__/firebase/init.json and
// the API itself. Anything outside /app (the legacy dashboard's space) is a 404 here.
import { createReadStream, existsSync, readFileSync, statSync } from 'node:fs';
import { createServer } from 'node:http';
import { extname, join, normalize } from 'node:path';

const root = join(import.meta.dirname, '..', 'out');
const port = Number(process.env.PORT ?? 4317);
const BASE = '/app';
// The headers Hosting sends on every path (CSP included), so the tests run under the real policy.
const hosting = JSON.parse(
    readFileSync(join(import.meta.dirname, '..', '..', '..', 'infra', 'firebase.json'), 'utf8'),
).hosting;
const headers = Object.fromEntries(
    hosting.headers.filter((h) => h.source === '**').flatMap((h) => h.headers.map((x) => [x.key, x.value])),
);
const types = {
    '.html': 'text/html; charset=utf-8',
    '.js': 'text/javascript',
    '.css': 'text/css',
    '.txt': 'text/plain',
    '.json': 'application/json',
    '.svg': 'image/svg+xml',
    '.ico': 'image/x-icon',
};

createServer((req, res) => {
    const full = decodeURIComponent(new URL(req.url ?? '/', 'http://x').pathname);
    if (full === BASE) return void res.writeHead(301, { Location: `${BASE}/` }).end();
    if (!full.startsWith(`${BASE}/`)) return void res.writeHead(404).end();
    const path = full.slice(BASE.length);
    let file = normalize(join(root, path));
    if (!file.startsWith(root)) return void res.writeHead(400).end();
    if (existsSync(file) && statSync(file).isDirectory()) {
        if (!path.endsWith('/')) return void res.writeHead(301, { Location: `${full}/` }).end();
        file = join(file, 'index.html');
    }
    const found = existsSync(file) && statSync(file).isFile();
    res.writeHead(found ? 200 : 404, {
        ...headers,
        'Content-Type': types[extname(found ? file : '.html')] ?? 'application/octet-stream',
    });
    createReadStream(found ? file : join(root, '404.html')).pipe(res);
}).listen(port, '127.0.0.1');
