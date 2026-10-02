#!/usr/bin/env bash
# Regression test for the custom rules in .gitleaks.toml.
# Fixtures are generated here, never committed, so the history scan never sees key-shaped strings.
# Usage: .github/scripts/test_gitleaks_rules.sh <gitleaks-image>
set -euo pipefail
image=${1:?gitleaks image}
work=$(mktemp -d "${RUNNER_TEMP:-.}/gitleaks-rules.XXXX")
trap 'rm -rf "$work"' EXIT
mkdir -p "$work/pos" "$work/neg"
key=$(printf '%s' 0123456789abcdef 0123456789abcdef)            # 32 hex, assembled at runtime
secured=$(printf 'Zm9v%.0s' {1..20})                            # 80-char base64 "secured key"

# Must be caught by pi-algolia-api-key (one finding per file).
printf '{"algolia": {"appId": "ABCDEF1234",\n "apiKey": "%s"}}\n' "$key" > "$work/pos/config.js"
printf 'GET /1/indexes/*?x-algolia-api-key=%s&x-algolia-application-id=ABC\n' "$key" > "$work/pos/query.txt"
printf 'const c = algoliasearch("APPID", "%s");\n' "$key" > "$work/pos/client.js"
printf 'const opts = { searchOnlyApiKey: "%s" };\n' "$key" > "$work/pos/search-only.js"
printf '// algolia secured key\nsecuredApiKey = "%s"\n' "$secured" > "$work/pos/secured.js"
# Must not be caught by pi-algolia-api-key.
printf '# plain config, no vendor named\napiKey = "%s"\n' "$key" > "$work/neg/other-vendor.py"
printf 'algolia docs: apiKey = "<your key>"\napi_key = os.environ["ALGOLIA_API_KEY"]\n' > "$work/neg/placeholder.py"
printf 'algolia: "x-algolia-api-key": "REDACTED"\n' > "$work/neg/redacted.txt"

scan() {
  docker run --rm -v "$PWD/.gitleaks.toml:/cfg.toml:ro" -v "$work:/w" "$image" \
    dir "/w/$1" --config /cfg.toml --no-banner --exit-code 0 \
    --report-format csv --report-path "/w/$1.csv" >/dev/null 2>&1
  awk -F, 'NR > 1 && $1 == "pi-algolia-api-key" { n = split($3, p, "/"); print p[n] }' "$work/$1.csv" | sort -u
}

fail=0
caught=$(scan pos)
for f in "$work"/pos/*; do
  name=$(basename "$f")
  if grep -qx "$name" <<<"$caught"; then echo "ok   caught  $name"; else echo "FAIL missed  $name"; fail=1; fi
done
flagged=$(scan neg)
for f in "$work"/neg/*; do
  name=$(basename "$f")
  if grep -qx "$name" <<<"$flagged"; then echo "FAIL flagged $name"; fail=1; else echo "ok   clean   $name"; fi
done
exit $fail
