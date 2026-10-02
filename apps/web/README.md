# apps/web — Product Intelligence dashboard (static)

The dashboard served at https://productintelligence-beeb3.web.app. Plain JavaScript and CSS,
no bundler and no npm dependencies. It reads the `pi.dataset/v1` snapshot from Firebase Storage
after sign-in; the Firebase web config is loaded at runtime from `/__/firebase/init.json`, so no
key is ever in the source or the build.

## Phase 2: the Next.js app (in progress)

The Next.js app is being built in this same folder and will replace the static dashboard once it
reaches parity. Until then the static dashboard (`src/`, `test/`, `build.sh`) is what is live, and
Infra keeps deploying it as described below. The two do not share code.

| path           | what it holds                                                                                 |
| -------------- | --------------------------------------------------------------------------------------------- |
| `app/`         | routes: `/` picks the language, `/<en\|ar>/` and `/<en\|ar>/sign-in/` (static export)         |
| `components/`  | auth provider (Firebase Auth + TanStack Query), header, sign-in, dataset status               |
| `lib/api/`     | typed read-API client; `schema.gen.ts` is generated from `docs/contracts/pi-api.openapi.json` |
| `lib/auth/`    | Firebase Auth: the web config is fetched from `/__/firebase/init.json` at runtime             |
| `lib/money.ts` | `Money` checks (exact ISO exponent) and formatting from the decimal string                    |
| `messages/`    | English and Arabic strings (same keys, checked by a test)                                     |
| `e2e/`         | Playwright tests against the static export; Firebase and the API are mocked                   |

```sh
npm ci --ignore-scripts
npm run check:api   # regenerate lib/api/schema.gen.ts from the contract; fails if it changed
npm run typecheck && npm run lint && npm run format && npm test
npm run build       # out/: static export, then a scan for secret-like strings
npx playwright install --with-deps && npm run e2e
```

How it talks to the API:

- **Bearer only.** Every call sends `Authorization: Bearer <Firebase ID token>` with
  `credentials: 'omit'`; no cookies are set or sent.
- **401:** retried once with a refreshed token; if that is refused too, the user signs in again.
- **503 `auth_unavailable`:** the API could not check the token. The client waits Retry-After
  (5 s by default), retries up to 3 times and never signs the user out.
- **409 `stale_cursor`:** `api.page()` drops the cursor and fetches page 1 (`restarted: true`).
- **429 / 503 `data_unavailable`:** shown with the server's Retry-After.
- **Any error:** only the code is kept. The server's `message` is dropped, so nothing it sends
  (or echoes from a query) reaches the screen.
- **New dataset generation:** cached queries are invalidated.

No secrets reach the client. There are no `NEXT_PUBLIC_*` keys, the Firebase web config is loaded
at runtime, and `npm run build` fails if the export contains a Google API key pattern, an Algolia
reference or a private key.

Not done yet: Hosting config for the Next build. The static export includes inline bootstrap
scripts, so its CSP needs their hashes before it can replace the dashboard.

## Build

```sh
apps/web/build.sh            # dist/: hosted build (content-hashed JS/CSS, strict CSP)
apps/web/build.sh verify     # build dist/ and compare it byte-for-byte with deployed.sha256
apps/web/build.sh artifact   # artifact/: offline build with in-browser sample data (no network)
```

Needs `node` and coreutils, with no npm packages. Every build runs `node --check` and
`test/escape.test.js`. That test renders every page in both languages from a snapshot whose brand,
name, unit, id and colour fields hold markup, and fails if any of it reaches the DOM unescaped.
`dist/` and `artifact/` are git-ignored.

`deployed.sha256` pins the build that should be live (`app.05ce45f162.js`, `styles.4e6093a7e9.css`). Run `verify` before every deploy; a source change must update that file in the
same PR (run `build.sh`, then regenerate it as in the `verify` step) and the new hashes are
what Infra deploys.

CI checks source → pin (that `dist/` matches `deployed.sha256`), not pin → live. After each deploy,
check the live site serves the pinned files: open https://productintelligence-beeb3.web.app, view the
page source and compare the `app.*.js` and `styles.*.css` names with `deployed.sha256`.

## Deploy

Hosting serves two apps from one `infra/web-dist/` (never committed): the legacy dashboard at `/`
and the Next app at `/app/` (`basePath` in `next.config.ts`). Build both, then copy:

```sh
apps/web/build.sh verify && (cd apps/web && npm ci && npm run build)
rm -rf infra/web-dist && cp -r apps/web/dist infra/web-dist && cp -r apps/web/out infra/web-dist/app
```

The Next export has inline scripts, so `infra/firebase.json` pins their `sha256` hashes in the CSP
`script-src`. The build id is a hash of the sources, so the same sources always give the same
hashes; `npm run build` fails when they no longer match. After a change, run `npm run csp:write`
and commit `infra/firebase.json` with it.

`npm run build` makes two exports: `out/` (the assistant off, as deployed today) and
`out-assistant/` (`NEXT_PUBLIC_ASSISTANT_ENABLED=true`, for switch-on). The CSP lists the union
of both builds' hashes, so it is valid for either. At switch-on the owner deploys
`out-assistant/` instead of `out/` and writes the reCAPTCHA Enterprise site key into
`infra/web-dist/app/assistant-app-check.json` as `{"recaptchaSiteKey": "<key>"}`
(`docs/runbooks/assistant-enablement.md` §10c). The key is read at runtime, never built in, so
the export and its hashes don't depend on it.

The owner runs `npx -y firebase-tools@14.27.0 deploy --only hosting` from `infra/` (see
`docs/runbooks/pi-api-deploy.md` §7). To roll back, redeploy with the legacy dashboard alone
(the first `cp` above, without `/app`), or roll back the release in the Hosting console.

## Source layout

Files are concatenated in this order into one `app.<hash>.js`:

| file | what it holds |
|---|---|
| `src/data.js` | deterministic sample generator; only used in sample mode (artifact build) |
| `src/model.js` | dataset loading, validation and derived metrics (index, gaps, coverage) |
| `src/charts.js` | SVG charts (LTR geometry, accessible labels, tooltips) |
| `src/i18n.js` | English and Arabic strings, number/currency formatting, RTL helpers |
| `src/app.js` | shell, auth screens, routes and screens |
| `src/styles.css` | all styles, including `[dir=rtl]` |

## Routes

Hash routes, all served by `/index.html` (unknown routes fall back to `#/dashboard`):
`#/dashboard`, `#/explorer`, `#/pricing`, `#/promotions`, `#/assortment`, `#/availability`,
`#/compare`, `#/assistant`, `#/coverage`, `#/product/<id>`, `#/signin`, `#/forgot`.
`/auth/action` is the password-reset landing page (Firebase email action URL).

## Partial data

With real data, a page drops panels that need data the snapshot does not have (the other retailer,
history, promotions, stock), shows panels this snapshot can fill (price bands, categories, brands,
ratings, shade ranges), and lists what is missing, and why, in one "Not available yet" card.
Categories outside the beauty list show as "Other".

## Known issues (next build)

- Opening `#/forgot` directly shows plain sign-in; the in-page "Forgot password" link works.
- On phones the explorer renders every card at once (very long page); it needs paging or "show more".
