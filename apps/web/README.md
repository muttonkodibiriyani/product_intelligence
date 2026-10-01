# apps/web — Product Intelligence dashboard (static)

The dashboard served at https://productintelligence-beeb3.web.app. Plain JavaScript and CSS,
no bundler and no npm dependencies. It reads the `pi.dataset/v1` snapshot from Firebase Storage
after sign-in; the Firebase web config is loaded at runtime from `/__/firebase/init.json`, so no
key is ever in the source or the build.

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

Infra copies the build into `infra/web-dist/` (never committed) and deploys Hosting from `infra/`:

```sh
apps/web/build.sh verify && rm -rf infra/web-dist && cp -r apps/web/dist infra/web-dist
```

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
