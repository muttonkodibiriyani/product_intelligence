'use strict';
/* Password reset in the hosted page: an unknown address reads like a sent link (no account
   enumeration); every other failure is said, and only its code is logged, never the address.
   Run: node apps/web/test/reset.test.js  (build.sh verify runs it) */
const fs = require('fs'), path = require('path'), vm = require('vm'), assert = require('assert');
const dir = path.join(__dirname, '..', 'src');
const src = ['data.js', 'model.js', 'charts.js', 'i18n.js', 'app.js'].map(f => fs.readFileSync(path.join(dir, f), 'utf8')).join('\n')
 .replace(/\nboot\(\);\s*$/, '\n');
const el = () => ({ style: {}, dataset: {}, classList: { add() {}, remove() {}, toggle() {} }, setAttribute() {}, appendChild() {}, querySelector: () => null, querySelectorAll: () => [], addEventListener() {}, focus() {} });
const root = el();
const warned = [];
let answer; // what the next identitytoolkit call does
const sandbox = {
 console: { ...console, warn: (...a) => warned.push(a) }, Intl, Date, URL, Math, JSON, Set, Map, URLSearchParams, setTimeout: () => 0, clearTimeout() {}, requestAnimationFrame: () => 0,
 localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
 location: { hostname: 'test', search: '', hash: '', pathname: '/' }, history: { replaceState() {}, pushState() {} }, navigator: {},
 matchMedia: () => ({ matches: false, addEventListener() {} }), innerWidth: 1440, innerHeight: 900, scrollTo() {}, addEventListener() {},
 document: { documentElement: el(), body: el(), activeElement: null, title: '', getElementById: id => id === 'root' ? root : null, querySelector: () => null, querySelectorAll: () => [], createElement: el, addEventListener() {} },
 fetch: async url => {
  if (String(url).startsWith('/__/firebase/init.json')) return { ok: true, json: async () => ({ apiKey: 'test-key' }) };
  if (answer === 'offline') throw new TypeError('NetworkError when attempting to fetch resource.');
  const [status, message] = answer;
  return { ok: status === 200, status, json: async () => (status === 200 ? { email: ADDR } : { error: { code: status, message } }) };
 }
};
sandbox.window = sandbox; sandbox.self = sandbox;
vm.createContext(sandbox);
vm.runInContext(src + `
;globalThis.__t = { resetPw, APP, S, t };`, sandbox, { filename: 'app-bundle.js' });
const T = sandbox.__t;
const ADDR = 'reader@example.com';

async function reset(a, lang = 'en') {
 T.S.lang = lang; T.APP.err = null; T.APP.info = null; warned.length = 0; answer = a;
 await T.resetPw(ADDR);
 return { info: T.APP.info, err: T.APP.err, warned: warned.slice() };
}

(async () => {
 for (const lang of ['en', 'ar']) {
  T.S.lang = lang;
  const sent = T.t('resetSent'), later = T.t('errResetLater');
  // A sent link, and an unknown address, give the same answer, with nothing logged.
  for (const a of [[200], [400, 'EMAIL_NOT_FOUND']]) {
   const r = await reset(a, lang);
   assert.deepStrictEqual([r.info, r.err, r.warned.length], [sent, null, 0], `${lang} ${a}: should read as sent`);
  }
  // Everything else is said; only the code is logged.
  for (const [a, code] of [[[400, 'TOO_MANY_ATTEMPTS_TRY_LATER : Too many attempts for ' + ADDR], 'TOO_MANY_ATTEMPTS_TRY_LATER'], [[400, 'RESET_PASSWORD_EXCEED_LIMIT'], 'RESET_PASSWORD_EXCEED_LIMIT'],
   [[429, 'QUOTA_EXCEEDED : Exceeded quota for email lookup.'], 'QUOTA_EXCEEDED'], [[403, 'PERMISSION_DENIED'], 'PERMISSION_DENIED'], ['offline', 'network']]) {
   const r = await reset(a, lang);
   assert.strictEqual(r.info, null, `${lang} ${code}: must not claim a link was sent`);
   assert.strictEqual(r.err, later, `${lang} ${code}: should say it couldn't send`);
   assert.deepStrictEqual(r.warned, [['password reset failed:', code]], `${lang} ${code}: logs the code only`);
   assert(!JSON.stringify(r.warned).includes(ADDR), `${lang} ${code}: the address reached the log`);
  }
  const r = await reset([400, 'INVALID_EMAIL'], lang);
  assert.deepStrictEqual([r.info, r.err], [null, T.t('errEmail')], `${lang}: a rejected address asks for a valid one`);
 }
 assert.notStrictEqual((T.S.lang = 'ar', T.t('errResetLater')), (T.S.lang = 'en', T.t('errResetLater')), 'errResetLater needs its own Arabic text');
 console.log('reset.test.js: ok');
})().catch(e => { console.error(e); process.exit(1); });
