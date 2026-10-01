// Serves the static export the way Firebase Hosting does (cleanUrls off, trailing slashes on),
// with no Firebase config: each test supplies /__/firebase/init.json and the API itself.
import { createReadStream, existsSync, statSync } from 'node:fs';
import { createServer } from 'node:http';
import { extname, join, normalize } from 'node:path';

const root = join(import.meta.dirname, '..', 'out');
const port = Number(process.env.PORT ?? 4317);
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
    const path = decodeURIComponent(new URL(req.url ?? '/', 'http://x').pathname);
    let file = normalize(join(root, path));
    if (!file.startsWith(root)) return void res.writeHead(400).end();
    if (existsSync(file) && statSync(file).isDirectory()) {
        if (!path.endsWith('/')) return void res.writeHead(301, { Location: `${path}/` }).end();
        file = join(file, 'index.html');
    }
    const found = existsSync(file) && statSync(file).isFile();
    res.writeHead(found ? 200 : 404, {
        'Content-Type': types[extname(found ? file : '.html')] ?? 'application/octet-stream',
    });
    createReadStream(found ? file : join(root, '404.html')).pipe(res);
}).listen(port, '127.0.0.1');
