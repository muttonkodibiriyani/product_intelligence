// @vitest-environment node
/**
 * The image-host tables and the CSP img-src that lets the browser load them are kept in separate
 * files, so a host added to a table but not to its img-src ships as a broken image, which no other
 * test catches. These pin each table to its own header:
 *  - /app: IMAGE_OWNERS (components/widgets/model.ts) and each img-src in infra/firebase.json name
 *    the same hosts. Both ways: a CSP host with no owner still shows a placeholder (imageHost()
 *    returns null), so adding it to firebase.json alone looks fixed and is not.
 *  - the root shell: IMG_HOSTS (src/model.js) and build.sh's hosted img-src name the same hosts.
 */
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { IMAGE_OWNERS } from '../components/widgets/model';

const web = join(import.meta.dirname, '..');
const read = (path: string) => readFileSync(join(web, path), 'utf8');

/** The https hosts an img-src directive allows, from a whole CSP value. */
function imgSrcHosts(csp: string): string[] {
  const directive = csp
    .split(';')
    .map((d) => d.trim().split(/\s+/))
    .find((d) => d[0] === 'img-src');
  if (!directive) throw new Error(`no img-src in: ${csp}`);
  return directive.filter((s) => s.startsWith('https://')).map((s) => new URL(s).hostname);
}

describe('/app image hosts', () => {
  const config = JSON.parse(read('../../infra/firebase.json')) as {
    hosting: { headers?: { source: string; headers: { key: string; value: string }[] }[] };
  };
  const csps = (config.hosting.headers ?? []).flatMap((rule) =>
    rule.headers
      .filter((h) => h.key.toLowerCase() === 'content-security-policy')
      .map((h) => ({ source: rule.source, hosts: imgSrcHosts(h.value) })),
  );

  it('infra/firebase.json sends a CSP', () => {
    expect(csps.length).toBeGreaterThan(0);
  });

  // Two empty lists are equal, so an emptied table must fail on its own.
  it('IMAGE_OWNERS lists at least one host', () => {
    expect(Object.keys(IMAGE_OWNERS).length).toBeGreaterThan(0);
  });

  it('every img-src in infra/firebase.json names exactly the IMAGE_OWNERS hosts', () => {
    const owners = Object.keys(IMAGE_OWNERS).sort();
    for (const csp of csps) expect([...csp.hosts].sort(), `img-src for ${csp.source}`).toEqual(owners);
  });
});

/** The first group of `re` in the file at `path`; throws if the line it reads has moved or changed shape. */
function capture(path: string, re: RegExp): string {
  const m = read(path).match(re)?.[1];
  if (m === undefined) throw new Error(`${path} no longer matches ${re}`);
  return m;
}

describe('root shell image hosts', () => {
  it("IMG_HOSTS and build.sh's hosted img-src name the same hosts", () => {
    // The object literal uses single quotes and bare keys; turn it into JSON to read the values.
    const literal = capture('src/model.js', /const IMG_HOSTS=(\{[^}]*\});/);
    const json = literal.replace(/'/g, '"').replace(/([{,])\s*(\w+)\s*:/g, '$1"$2":');
    const hosts = Object.values(JSON.parse(json) as Record<string, string>);
    const csp = capture('build.sh', /build_hosted\(\)\{[\s\S]*?local csp="([^"]*)"/);
    expect(hosts.length).toBeGreaterThan(0);
    expect(imgSrcHosts(csp).sort()).toEqual(hosts.sort());
  });
});
