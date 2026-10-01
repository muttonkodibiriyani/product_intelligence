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
 console, Intl, Date, Math, JSON, Set, Map, URLSearchParams, setTimeout: () => 0, clearTimeout() {}, requestAnimationFrame: () => 0,
 localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
 location: { hostname: 'test', search: '', hash: '', pathname: '/' }, history: { replaceState() {}, pushState() {} }, navigator: {},
 matchMedia: () => ({ matches: false, addEventListener() {} }), innerWidth: 1440, innerHeight: 900, scrollTo() {}, addEventListener() {},
 document: { documentElement: el(), body: el(), activeElement: null, title: '', getElementById: id => id === 'root' ? root : null, querySelector: () => null, querySelectorAll: () => [], createElement: el, addEventListener: (t, f) => (handlers[t] = handlers[t] || []).push(f) }
};
sandbox.window = sandbox; sandbox.self = sandbox;
vm.createContext(sandbox);
vm.runInContext(src + `
;globalThis.__t = { hydrate, sampleContract, fixtureContract, useDS, resetAll, afterData, W, ctx, S, render, SETF_KEYS };`, sandbox, { filename: 'app-bundle.js' });
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
console.log('escape.test.js: ok');
