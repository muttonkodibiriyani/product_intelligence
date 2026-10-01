'use strict';
/* Dataset strings are scraped text: they must never reach the DOM as markup.
   Loads the concatenated sources in a VM with a stub DOM (no npm deps) and renders with a hostile snapshot.
   Run: node apps/web/test/escape.test.js  (build.sh verify runs it) */
const fs = require('fs'), path = require('path'), vm = require('vm'), assert = require('assert');
const dir = path.join(__dirname, '..', 'src');
const src = ['data.js', 'model.js', 'charts.js', 'i18n.js', 'app.js'].map(f => fs.readFileSync(path.join(dir, f), 'utf8')).join('\n')
 .replace(/\nboot\(\);\s*$/, '\n');
const handlers = {}, el = () => ({ style: {}, dataset: {}, classList: { add() {}, remove() {}, toggle() {} }, setAttribute() {}, appendChild() {}, querySelector: () => null, querySelectorAll: () => [], addEventListener() {}, focus() {} });
const root = el();
const sandbox = {
 console, Intl, Date, URL, Math, JSON, Set, Map, URLSearchParams, setTimeout: () => 0, clearTimeout() {}, requestAnimationFrame: () => 0,
 localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
 location: { hostname: 'test', search: '', hash: '', pathname: '/' }, history: { replaceState() {}, pushState() {} }, navigator: {},
 matchMedia: () => ({ matches: false, addEventListener() {} }), innerWidth: 1440, innerHeight: 900, scrollTo() {}, addEventListener() {},
 document: { documentElement: el(), body: el(), activeElement: null, title: '', getElementById: id => id === 'root' ? root : null, querySelector: () => null, querySelectorAll: () => [], createElement: el, addEventListener: (t, f) => (handlers[t] = handlers[t] || []).push(f) }
};
sandbox.window = sandbox; sandbox.self = sandbox;
vm.createContext(sandbox);
vm.runInContext(src + `
;globalThis.__t = { hydrate, sampleContract, fixtureContract, useDS, resetAll, afterData, W, ctx, S, render, SETF_KEYS, PRESETS, viewById, launchesIn, heldAt };`, sandbox, { filename: 'app-bundle.js' });
const T = sandbox.__t;

const EVIL = '<b>x</b><zz>';
const bad = s => s.includes('<zz') || s.includes('<b>x</b>');
const ROUTES = ['dashboard', 'explorer', 'pricing', 'promotions', 'assortment', 'availability', 'compare', 'coverage', 'product'];
// sample contract (DS.real false) plus both real-data shapes, so the real-data-only panels render too
for (const [name, mk] of [['sample', () => T.sampleContract()], ['partial', () => T.fixtureContract('partial')], ['blocked', () => T.fixtureContract('blocked')]]) {
 const j = mk();
 for (const q of j.products) { q.brand = EVIL; q.name = EVIL; q.unit = '<zz>ml'; q.id = q.id + '"><zz>'; q.render = { ...(q.render || {}), cap: 'red"/><zz>', liquid: '#zzz' } }
 j.meta.cutoff = EVIL;
 const DS = T.hydrate(j);
 T.useDS(DS); T.resetAll(); T.afterData();
 const kpi = T.W.kpiBrands.r(T.ctx());
 assert(!bad(kpi), `${name}: kpiBrands renders the brand as markup: ` + kpi);
 assert(kpi.includes('&lt;b&gt;x&lt;/b&gt;'), `${name}: kpiBrands should show the escaped brand: ` + kpi);
 for (const lang of ['en', 'ar']) for (const r of ROUTES) {
  T.S.lang = lang; T.S.route = r; T.S.param = r === 'product' ? DS.products?.[0]?.id ?? null : null;
  root.innerHTML = '';
  try { T.render() } catch (e) { throw new Error(`${name} ${r}/${lang} threw: ${e.stack}`) }
  const h = String(root.innerHTML);
  assert(h.length > 500, `${name} ${r}/${lang}: page rendered nothing`);
  assert(!bad(h), `${name} ${r}/${lang}: dataset string reached the DOM as markup near: ` + h.match(/.{0,80}(<zz|<b>x<\/b>).{0,40}/)?.[0]);
 }
}

// data-setf only touches whitelisted filter keys
assert.deepStrictEqual([...T.SETF_KEYS].sort(), ['band', 'brand', 'cat', 'shade']);
const click = d => handlers.click.forEach(f => f({ target: { closest: () => ({ dataset: d, closest: () => null, matches: () => false, tagName: 'BUTTON' }) }, preventDefault() {}, stopPropagation() {} }));
T.resetAll();
const before = Object.keys(T.S.f).sort().join();
click({ setf: '__proto__:x|constructor:y|toString:z|brand:Dior' });
assert.strictEqual(Object.keys(T.S.f).sort().join(), before, 'setf added a filter key');
assert.strictEqual(({}).x, undefined, 'setf polluted Object.prototype');
assert.deepStrictEqual([...T.S.f.brand], ['Dior']);

// real data leads every dashboard tab: what waits on data sits only in the one strip at the bottom
{
 const DS = T.hydrate(T.fixtureContract('blocked'));
 T.useDS(DS); T.resetAll(); T.afterData();
 assert.strictEqual(T.S.viewId, 'snap', 'a real snapshot opens on the snapshot tab');
 for (const lang of ['en', 'ar']) for (const v of T.PRESETS) {
  T.S.lang = lang; T.S.route = 'dashboard'; T.S.edit = false; T.S.viewId = v.id; T.S.layout = T.viewById(v.id).w.map(x => x.slice());
  root.innerHTML = ''; T.render();
  const h = String(root.innerHTML), strip = h.indexOf('class="card coming"');
  const gateAt = h.search(/class="wempty gate/);
  assert(gateAt < 0 || (strip >= 0 && gateAt > strip), `${v.id}/${lang}: a gated panel renders above the real data`);
  assert(strip < 0 || h.indexOf('class="widget', strip) < 0, `${v.id}/${lang}: the waiting strip is not last`);
  assert((h.match(/class="widget kpiw/g) || []).length <= 4, `${v.id}/${lang}: more than one row of KPI tiles`);
  assert(/class="widget(?! kpiw)/.test(h.slice(0, strip < 0 ? undefined : strip)), `${v.id}/${lang}: no real chart or table`);
 }
}

// images: only https on the offer's own retailer host, escaped; anything else falls back to the rendering
{
 const j = T.fixtureContract('partial');
 const [a, b, c, d] = j.products;
 const off = (q, k, image) => { if (q.offers?.[k]) q.offers[k].image = image };
 off(a, 's', 'https://img-product.sephora.me/p/1.jpg?x="><zz>');
 off(b, 's', 'https://media.alshaya.com/p/2.png');           // wrong retailer's host
 off(c, 's', 'http://img-product.sephora.me/p/3.jpg');       // not https
 d.image = 'https://user:pw@img-product.sephora.me/p/4.jpg'; // credentials
 for (const q of [b, c, d]) for (const k of ['u', 's']) if (q.offers?.[k] && q.offers[k].image === undefined) q.offers[k].image = 'https://evil.example/x.jpg';
 const DS = T.hydrate(j), by = Object.fromEntries(DS.products.map(p => [p.id, p]));
 const P = id => by[String(id).replace(/[^\w.:-]/g, '_')];
 assert(P(a.id) && a.offers?.s, 'fixture: first product needs a Sephora offer');
 assert.strictEqual(P(a.id).img, 'https://img-product.sephora.me/p/1.jpg?x=%22%3E%3Czz%3E');
 for (const q of [b, c, d]) if (P(q.id)) assert.strictEqual(P(q.id).img ?? null, null, `${q.id}: off-allowlist image kept`);
 T.useDS(DS); T.resetAll(); T.afterData();
 T.S.lang = 'en'; T.S.route = 'product'; T.S.param = P(a.id)?.id; root.innerHTML = ''; T.render();
 const h = String(root.innerHTML);
 if (P(a.id)) assert(h.includes('class="pphoto"') && h.includes('referrerpolicy="no-referrer"') && h.includes('loading="lazy"') && !bad(h), 'product photo missing or unsafe');
}
/* The sample's series share arrays with the generator and its dates follow the last dataset used,
   so the guard tests take a copy with one date per series day. */
function fullSample() {
 const j = JSON.parse(JSON.stringify(T.sampleContract()));
 const N = j.products.find(q => q.offers?.u)?.offers.u.series.price.length, end = Date.UTC(2026, 8, 30);
 j.meta.dates = Array.from({ length: N }, (_, i) => new Date(end - (N - 1 - i) * 864e5).toISOString().slice(0, 10));
 return j;
}
// prices of 0.01 or less are feed errors: read as no price for both retailers, never shown or summed
{
 const j = fullSample(), N = j.meta.dates.length;
 const both = j.products.filter(q => q.offers?.u?.series?.price && q.offers?.s?.series?.price);
 assert(both.length >= 2, 'fixture: need two products listed at both retailers');
 const cases = [[both[0], 0.01], [both[1], 0]];
 for (const [q, v] of cases) for (const k of ['u', 's']) {
  const sr = q.offers[k].series;
  sr.price[N - 1] = v;
  sr.regular = sr.regular || new Array(N).fill(null);
  sr.regular[N - 1] = v;
 }
 const DS = T.hydrate(j), by = Object.fromEntries(DS.products.map(p => [p.id, p]));
 for (const [q, v] of cases) for (const k of ['u', 's']) {
  const p = by[String(q.id).replace(/[^\w.:-]/g, '_')];
  assert(p, `${q.id}: product dropped`);
  assert.strictEqual(p.d[k].price[N - 1], null, `${k} price ${v} kept`);
  assert.strictEqual(p.d[k].regular[N - 1], null, `${k} regular ${v} kept`);
  assert(p.reg[k] == null || p.reg[k] > 0.01, `${k} regular price ${p.reg[k]} at or under 0.01`);
 }
 const kept = T.hydrate(fullSample()).products.find(p => p.id === by[String(both[0].id).replace(/[^\w.:-]/g, '_')].id);
 assert(kept.d.u.price.some(x => x > 0.01), 'a real price must survive the guard');
}
// a discount worked out from a guarded price is no discount; a guarded day is not a delisting
{
 const j = fullSample(), N = j.meta.dates.length;
 const withP = j.products.filter(q => q.offers?.u?.series?.price?.slice(-3).every(v => v != null));
 assert(withP.length >= 2, 'fixture: need products priced at Ulta on the last days');
 const [a, b] = withP, A = a.offers.u.series, B = b.offers.u.series;
 // a: last-day price 0.01 stored with the 100% discount the feed works out from it
 A.price[N - 1] = 0.01; A.promo = A.promo || new Array(N).fill(0); A.promo[N - 1] = 100;
 a.offers.u.promos = undefined;
 // b: a real price on a day whose regular price is 0.01 (a nonsense discount)
 B.regular = B.regular || new Array(N).fill(null); B.regular[N - 2] = 0.01;
 B.promo = B.promo || new Array(N).fill(0); B.promo[N - 2] = 99;
 b.offers.u.promos = undefined;
 const DS = T.hydrate(j), id = q => String(q.id).replace(/[^\w.:-]/g, '_');
 const P = Object.fromEntries(DS.products.map(p => [p.id, p])), pa = P[id(a)], pb = P[id(b)];
 assert.strictEqual(pa.d.u.promo[N - 1], 0, 'discount kept on a guarded price');
 assert.strictEqual(pb.d.u.promo[N - 2], 0, 'discount kept on a guarded regular price');
 for (const p of [pa, pb]) assert(!p.promos.some(x => x.r === 'u' && x.pct >= 99), `${p.id}: fake discount in promotions`);
 // listed, price withheld: not a 'gone' event, and the product page says why
 assert(T.heldAt(pa, 'u', N - 1) && !T.heldAt(pa, 'u', N - 2));
 T.useDS(DS); T.resetAll(); T.afterData();
 assert(!T.launchesIn([pa], 0, N - 1).some(e => e.k === 'u' && e.type === 'gone'), 'guarded last day read as delisted');
 T.S.lang = 'en'; T.S.route = 'product'; T.S.param = pa.id; root.innerHTML = ''; T.render();
 assert(String(root.innerHTML).includes('Price under review'), 'product page: no under-review note');
}
// an early capture priced at 0.01 or less carries no price either
{
 const j = T.fixtureContract('blocked');
 const q = j.products.find(q => q.offers?.u?.early && q.offers.u.series?.price);
 assert(q, 'fixture: need an early Ulta capture');
 const sr = q.offers.u.series; sr.price[sr.price.length - 1] = 0.01;
 const DS = T.hydrate(j);
 const e = DS.early.find(e => e.o === q.offers.u);
 assert(e, 'early capture dropped');
 assert.strictEqual(e.price, null, 'early price 0.01 kept');
 assert(DS.early.some(x => x !== e && x.price > 0.01), 'real early prices must survive');
}
console.log('escape.test.js: ok');
