#!/usr/bin/env bash
# Builds the static dashboard from src/.
#   ./build.sh            -> dist/      hosted app for Firebase Hosting (copy into infra/web-dist/ to deploy)
#   ./build.sh artifact   -> artifact/  offline build with in-browser sample data (connect-src 'none')
#   ./build.sh verify     -> builds dist/ and checks it byte-for-byte against deployed.sha256
# No bundler and no npm dependencies: the JS files are concatenated in load order.
set -euo pipefail
cd "$(dirname "$0")"
MODE=${1:-hosted}
SRC=(src/data.js src/model.js src/charts.js src/i18n.js src/app.js)
TMP=$(mktemp --suffix=.js); trap 'rm -f "$TMP"' EXIT
cat "${SRC[@]}" > "$TMP"
node --check "$TMP"

page(){ # $1 extra meta, $2 csp, $3 css href, $4 script tags
cat <<HTML
<!doctype html>
<html lang="en" dir="ltr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
$1<meta http-equiv="Content-Security-Policy" content="$2">
<title>Product Intelligence · Ulta UAE vs Sephora UAE</title>
<link rel="stylesheet" href="$3">
</head>
<body>
<div id="root"></div>
<noscript>Product Intelligence needs JavaScript.</noscript>
$4
</body>
</html>
HTML
}

guard(){ # no API keys or search-service keys in anything we ship
  if grep -RIl -E "AIza[0-9A-Za-z_-]{20,}|algolia|x-algolia" "$1"; then echo "secret-like string found in $1" >&2; exit 1; fi
}

build_hosted(){
  rm -rf dist && mkdir -p dist/auth/action
  local jh ch
  jh=$(sha256sum "$TMP" | cut -c1-10); ch=$(sha256sum src/styles.css | cut -c1-10)
  cp "$TMP" "dist/app.$jh.js"; cp src/styles.css "dist/styles.$ch.css"
  local csp="default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self' https://identitytoolkit.googleapis.com https://securetoken.googleapis.com https://firebasestorage.googleapis.com; base-uri 'none'; form-action 'none'"
  page '<meta name="pi-mode" content="hosted">
<meta name="robots" content="noindex">
' "$csp" "/styles.$ch.css" "<script src=\"/app.$jh.js\"></script>" > dist/index.html
  # Firebase email action handler (password reset) uses the same shell; the app detects /auth/action
  cp dist/index.html dist/auth/action/index.html
  guard dist
}

case "$MODE" in
  hosted) build_hosted ;;
  verify)
    build_hosted
    (cd dist && find . -type f | sort | sed 's|^\./||' | xargs sha256sum) | diff -u deployed.sha256 - \
      && echo "dist/ matches deployed.sha256"
    ;;
  artifact)
    rm -rf artifact && mkdir -p artifact
    cp "${SRC[@]}" src/styles.css artifact/
    page '' "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'none'" "styles.css" '<script src="data.js"></script>
<script src="model.js"></script>
<script src="charts.js"></script>
<script src="i18n.js"></script>
<script src="app.js"></script>' > artifact/index.html
    guard artifact
    ;;
  *) echo "usage: $0 [hosted|verify|artifact]" >&2; exit 2 ;;
esac
