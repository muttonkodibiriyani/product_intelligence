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
;globalThis.__t = { hydrate, sampleContract, fixtureContract, useDS, resetAll, afterData, W, ctx, S, render, SETF_KEYS, PRESETS, viewById };`, sandbox, { filename: 'app-bundle.js' });
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
  assert(!h.includes('${'), `${name} ${r}/${lang}: an uninterpolated \${...} reached the DOM near: ` + h.match(/.{0,80}\$\{.{0,40}/)?.[0]);
 }
}

// data-setf only touches whitelisted filter keys
assert.deepStrictEqual([...T.SETF_KEYS].sort(), ['band', 'brand', 'cat', 'shade']);
const click = d => handlers.click.forEach(f => f({ target: { closest: () => ({ dataset: d, closest: () => null, matches: () => false, tagName: 'BUTTON' }) }, preventDefault() {}, stopPropagation() {} }));
// a selected promo campaign is outlined with the theme ink, never a literal ${...}
{
 T.useDS(T.hydrate(T.sampleContract())); T.resetAll(); T.afterData();
 const html = () => { root.innerHTML = ''; T.render(); return String(root.innerHTML) };
 T.S.route = 'promotions'; T.S.lang = 'en';
 const id = html().match(/data-act="pc:([^"]+)"/)?.[1];
 assert(id, 'promotions renders a clickable campaign');
 click({ act: 'pc:' + id });
 const h = html();
 assert(T.S.sel && T.S.sel.src === 'promocal', 'clicking a campaign selects it');
 assert(!h.includes('${'), 'no uninterpolated ${...} with a campaign selected');
 assert(/stroke="#[0-9A-Fa-f]{6}" stroke-width="1.5"/.test(h), 'the selected campaign has an outline');
 T.resetAll();
}
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

// a blocked retailer says so without promising a re-test; an imported snapshot is dated by its import, never by a capture
{
 const render = (j, lang) => { T.useDS(T.hydrate(j)); T.resetAll(); T.afterData(); T.S.lang = lang; T.S.route = 'coverage'; root.innerHTML = ''; T.render(); return String(root.innerHTML) };
 const W = { en: ['automated collection blocked', 'snapshot imported 30 Sep 2026, capture date unknown · not in this view', /re-test/],
  ar: ['الجمع الآلي محجوب', 'لقطة مستوردة في 30 سبتمبر 2026، وتاريخ جمعها غير معروف · ليست ضمن هذا العرض', /إعادة الاختبار/] };
 for (const lang of ['en', 'ar']) {
  const [blocked, snap, retest] = W[lang];
  let h = render(T.fixtureContract('blocked'), lang);
  assert(h.includes(blocked), `${lang}: a blocked retailer reads as blocked`);
  assert(!retest.test(h), `${lang}: no re-test promise`);
  const j = T.fixtureContract('blocked'), u = j.meta.retailers.find(r => r.id === 'u');
  // importedAt is a market-local (Dubai) date, rendered as is
  Object.assign(u, { status: 'snapshot', importedAt: '2026-09-30' });
  h = render(j, lang);
  assert(h.includes(snap), `${lang}: an imported snapshot reads as imported, with its import date`);
  const none = lang === 'ar' ? 'وتاريخ جمعها غير معروف' : 'capture date unknown';
  // a timestamp is not the contract (2026-09-30T21:15Z is 1 Oct in Dubai), nor is an impossible or missing date
  for (const v of ['2026-09-30T21:15:00Z', '2026-09-31', 'not a date', undefined]) {
   u.importedAt = v;
   assert(!render(j, lang).includes(none), `${lang}: no import wording for importedAt=${v}`);
  }
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

// Ulta's offer image renders from its own host, and the photo note credits the host by exact name:
// a Sephora image whose query mentions Ulta's host is still credited to Sephora.
{
 const j = T.fixtureContract('partial');
 const u = j.products.find(q => q.offers?.u), s = j.products.find(q => q.offers?.s && q !== u);
 assert(u && s, 'fixture: needs an Ulta product and another Sephora product');
 for (const q of [u, s]) for (const o of Object.values(q.offers)) if (o) delete o.image;
 delete u.image; delete s.image;
 u.offers.u.image = 'https://media.alshaya.com/p/1.png';
 s.offers.s.image = 'https://img-product.sephora.me/p/1.jpg?src=media.alshaya.com';
 const DS = T.hydrate(j), by = Object.fromEntries(DS.products.map(p => [p.id, p]));
 const P = id => by[String(id).replace(/[^\w.:-]/g, '_')];
 assert.strictEqual(P(u.id).img, 'https://media.alshaya.com/p/1.png');
 const note = id => { T.S.lang = 'en'; T.S.route = 'product'; T.S.param = P(id).id; T.S.gal = 0; root.innerHTML = ''; T.render();
  const h = String(root.innerHTML); assert(h.includes('class="pphoto"') && !bad(h), `${id}: photo missing`);
  return (/Image shown from ([^<]*?)'s site/.exec(h.replace(/&#39;|&#x27;/g, "'")) || [])[1] }
 T.useDS(DS); T.resetAll(); T.afterData();
 const nu = note(u.id), ns = note(s.id);
 assert(nu && /ulta/i.test(nu), `Ulta photo credited to ${nu}`);
 assert(ns && /sephora/i.test(ns), `Sephora photo credited to ${ns}`);
}
console.log('escape.test.js: ok');
